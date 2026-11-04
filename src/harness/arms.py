"""三臂运行器：逐章写作 → 读者测量 → 落盘。"""
import json
import os
from datetime import datetime, timezone

from .agents import build_reader_messages, build_writer_messages, parse_reader_json
from .config import load_config
from .ledger import Ledger
from .llm import LLMClient


def _maybe_polisher(cfg: dict, spec: dict, outdir: str):
    """cfg 含 polish 配置时启用润色层；否则返回 None。polish 角色缺省复用 writer 端点。"""
    pol = cfg.get("polish")
    if not pol:
        return None
    role_cfg = dict(cfg["writer"] if isinstance(pol, bool) or pol is True else {**cfg["writer"], **pol})
    client = LLMClient(role_cfg, os.path.join(outdir, "usage.jsonl"))
    from .polish import Polisher
    return Polisher(client, spec)


def run_arm(arm: str, run_idx: int, spec: dict, cfg: dict, outdir: str, chapters_override: int = None):
    os.makedirs(outdir, exist_ok=True)
    ch_dir = os.path.join(outdir, "chapters")
    rd_dir = os.path.join(outdir, "reader")
    os.makedirs(ch_dir, exist_ok=True)
    os.makedirs(rd_dir, exist_ok=True)

    ledger = Ledger(spec)
    writer = LLMClient(cfg["writer"], os.path.join(outdir, "usage.jsonl"))
    reader = LLMClient(cfg["reader"], os.path.join(outdir, "usage.jsonl"))
    polisher = _maybe_polisher(cfg, spec, outdir)
    total = chapters_override or cfg.get("chapters", len(spec["beats"]))

    meta = {
        "arm": arm, "run": run_idx, "chapters": total,
        "writer_model": writer.model, "reader_model": reader.model,
        "writer_temperature": writer.temperature, "reader_temperature": reader.temperature,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    chapters: list[str] = []
    for ch in range(1, total + 1):
        ch_path = os.path.join(ch_dir, f"ch{ch:02d}.md")
        rd_path = os.path.join(rd_dir, f"ch{ch:02d}.json")
        # 断点续跑：已有非空产物的章节直接读盘，不重复调用
        if os.path.exists(ch_path) and os.path.getsize(ch_path) > 0:
            with open(ch_path, encoding="utf-8") as f:
                chapters.append(f.read())
            print(f"  [arm {arm} run {run_idx}] chapter {ch}/{total} resumed from disk")
        else:
            msgs = build_writer_messages(arm, spec, ledger, chapters, ch)
            text = writer.chat(msgs, tag=f"arm{arm}-run{run_idx}-ch{ch:02d}")
            if polisher:
                text, prep = polisher.polish_chapter(text, ch, tag=f"arm{arm}-run{run_idx}-")
                os.makedirs(os.path.join(outdir, "polish"), exist_ok=True)
                with open(os.path.join(outdir, "polish", f"ch{ch:02d}.json"), "w", encoding="utf-8") as f:
                    json.dump(prep, f, ensure_ascii=False, indent=2)
            chapters.append(text)
            with open(ch_path, "w", encoding="utf-8") as f:
                f.write(text)
            note = f" (polished: {'resolved' if prep.get('resolved') else prep.get('flags_after') or 'clean'})" if polisher else ""
            print(f"  [arm {arm} run {run_idx}] chapter {ch}/{total} written ({len(text)} chars){note}")

        if not (os.path.exists(rd_path) and os.path.getsize(rd_path) > 0):
            rmsgs = build_reader_messages(spec["title"], chapters, lang=spec.get("language", "zh"))
            raw = reader.chat(rmsgs, tag=f"arm{arm}-run{run_idx}-reader-ch{ch:02d}")
            parsed = parse_reader_json(raw)
            with open(rd_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)

    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    meta["writer_tokens"] = writer.total_tokens
    meta["reader_tokens"] = reader.total_tokens
    with open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return chapters
