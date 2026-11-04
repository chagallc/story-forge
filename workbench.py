#!/usr/bin/env python3
"""story-forge 写作工作台 v1：人机协作章节工作流。

用法：
  python workbench.py new <书名>            # 建 workspace（交互式）
  python workbench.py char <书名> add       # 加人物卡（动机栈+声口）
  python workbench.py char <书名> list      # 人物列表
  python workbench.py discuss <书名> <章号>  # 章节剧情讨论（REPL，AI 联合编剧）
  python workbench.py lock <书名> <章号>    # 讨论结论固化为引擎细胞
  python workbench.py write <书名> <章号>   # 落笔（E臂+lint+润色）
  python workbench.py status <书名>         # 全书状态板

设计：docs/decisions/0003（动机压力层）/ 0005（开场契约）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from src.harness.agents import build_writer_messages  # noqa: E402
from src.harness.config import load_config  # noqa: E402
from src.harness.ledger import Ledger  # noqa: E402
from src.harness.llm import make_client  # noqa: E402
from src.harness.style_lint import lint_chapter  # noqa: E402

WS_ROOT = os.path.join(ROOT, "workspaces")


def ws_dir(book):
    return os.path.join(WS_ROOT, book)


def bible_path(book):
    return os.path.join(ws_dir(book), "story-bible.json")


def load_bible(book):
    with open(bible_path(book), encoding="utf-8") as f:
        return json.load(f)


def save_bible(book, bible):
    with open(bible_path(book), "w", encoding="utf-8") as f:
        json.dump(bible, f, ensure_ascii=False, indent=2)
    print(f"saved: {bible_path(book)}")


def client_for(bible, role="writer", book=""):
    cfg = load_config(os.path.join(ROOT, "experiments", "exp003"))
    role_cfg = dict(cfg[role])
    if bible.get("book", {}).get("language") == "en":
        role_cfg["model"] = "gpt-5.6-terra"
        role_cfg["api_style"] = "codex"
        role_cfg.pop("extra_body", None)
    return make_client(role_cfg, os.path.join(ws_dir(book), "usage-workbench.jsonl"))


# ---------------- new ----------------

def cmd_new(args):
    book = args[0] if len(args) > 0 else input("书名（目录名，英文）: ").strip()
    d = ws_dir(book)
    os.makedirs(os.path.join(d, "chapters"), exist_ok=True)
    os.makedirs(os.path.join(d, "discussions"), exist_ok=True)
    print("== 建书（回车跳过）==")
    bible = {
        "book": {
            "title": input("书名/标题: ").strip() or book,
            "genre": input("类型（如 修仙系统流/悬疑/progression fantasy）: ").strip(),
            "language": (input("语言 zh/en（默认 zh）: ").strip() or "zh"),
            "platform": input("目标平台（webnovel/qidian/...）: ").strip(),
            "logline": input("一句话故事: ").strip(),
        },
        "opening_contract": {
            "want_visible_by": 1500,
            "disturbance_in_ch1": True,
            "dialogue_ratio_min": 0.40,
            "no_info_dump": True,
            "notes": "见 docs/decisions/0005",
        },
        "characters": [],
        "world": {"setting": input("世界观一句话: ").strip(), "glossary": []},
        "arc": {"template": input("弧线模板（英雄之旅/悬疑假设弧/爽文蓄放弧）: ").strip(),
                "anchors": [], "total_chapters": int(input("规划章数（默认12）: ").strip() or 12)},
        "ledger": [],
        "chapters": {},
    }
    save_bible(book, bible)
    print(f"\nworkspace 就绪：{d}\n下一步：python workbench.py char {book} add")


# ---------------- char ----------------

CHAR_FIELDS = [
    ("card", "一句话人物卡（身份/年龄/外貌要点）"),
    ("want", "want：表层欲望（他自己知道且承认）"),
    ("need", "need：深层需求（他自己没意识到）"),
    ("wound", "wound：旧伤（解释他为什么这样行事）"),
    ("value", "value：底线（可让他翻脸/越线的东西）"),
    ("fear", "fear：恐惧（压力测试点）"),
    ("contradiction", "contradiction：内在矛盾"),
]


def cmd_char(args):
    book = args[0]
    bible = load_bible(book)
    sub = args[1] if len(args) > 1 else "list"
    if sub == "add":
        name = input("姓名: ").strip()
        c = {"name": name}
        for key, prompt in CHAR_FIELDS:
            c[key] = input(f"{prompt}: ").strip() or None
        c = {k: v for k, v in c.items() if v}
        c["voice"] = {
            "catchphrases": [x.strip() for x in input("口头禅/标志行为（逗号分隔，可空）: ").split(",") if x.strip()],
            "speech_habits": [x.strip() for x in input("说话习惯（逗号分隔，可空）: ").split(",") if x.strip()],
            "sample_line": input("一句代表性台词（可空）: ").strip() or None,
        }
        c["voice"] = {k: v for k, v in c["voice"].items() if v}
        bible["characters"].append(c)
        save_bible(book, bible)
    elif sub == "list":
        for c in bible["characters"]:
            print(f"- {c['name']}：{c.get('card','')}")
            print(f"  want={c.get('want','-')} | fear={c.get('fear','-')}")
            if c.get("voice", {}).get("catchphrases"):
                print(f"  口头禅: {c['voice']['catchphrases']}")
    else:
        print("用法: char <书名> add|list")


# ---------------- 讨论 ----------------

def bible_summary(bible):
    chars = "\n".join(
        f"- {c['name']}：{c.get('card','')}｜want={c.get('want','-')}｜fear={c.get('fear','-')}"
        + (f"｜口头禅={c['voice']['catchphrases']}" if c.get('voice', {}).get('catchphrases') else "")
        for c in bible["characters"])
    ledger = "\n".join(f"- {e['id']}: {e.get('hook','')}" for e in bible.get("ledger", [])) or "（暂无）"
    lang = bible["book"].get("language", "zh")
    return (f"《{bible['book']['title']}》 类型:{bible['book'].get('genre')} 平台:{bible['book'].get('platform')}\n"
            f"一句话：{bible['book'].get('logline')}\n世界观：{bible['world'].get('setting','-')}\n"
            f"弧线：{bible['arc'].get('template')}，全书 {bible['arc'].get('total_chapters')} 章，锚点：{bible['arc'].get('anchors') or '待定'}\n"
            f"人物：\n{chars}\n暗账：\n{ledger}"), lang


def cmd_discuss(args):
    book, ch = args[0], int(args[1])
    bible = load_bible(book)
    summary, lang = bible_summary(bible)
    client = client_for(bible, "writer", book)

    ch_dir = os.path.join(ws_dir(book), "discussions")
    os.makedirs(ch_dir, exist_ok=True)
    log_path = os.path.join(ch_dir, f"ch{ch:02d}.jsonl")

    if lang == "en":
        system = ("You are the co-writer of this serialized novel. Your job in this session: discuss the "
                  "direction of one chapter with the author BEFORE any prose is written. For the chapter in "
                  "question, propose 2-3 candidate directions, each with: where the disturbance lands, what the "
                  "protagonist's plan and its disruption are, motive pressure on which character, expected "
                  "dialogue density, and how it advances the arc anchor. Push back when the author's idea breaks "
                  "continuity or weakens motive chains. Never write prose.")
        opener_q = f"Book state:\n{summary}\n\nWe are discussing Chapter {ch}. Please propose candidate directions (with the checklist above)."
    else:
        system = ("你是这部连载小说的联合编剧。本次会话任务：在动笔之前与作者讨论一章的剧情方向。"
                  "请针对目标章节提出 2-3 个候选方向，每个方向说明：扰动落在哪、主角的计划与被推翻方式、"
                  "动机压力压在谁身上、预估对话密度、以及它如何推进弧线锚点。"
                  "作者的想法如果破坏连续性或削弱动机链，你要直说并给出修正。全程不写正文。")
        opener_q = f"书况：\n{summary}\n\n我们来讨论第 {ch} 章。请先给出候选方向（附上面的清单）。"

    msgs = [{"role": "system", "content": system}, {"role": "user", "content": opener_q}]
    turns = [{"role": "user", "content": opener_q}]
    print(f"=== 第 {ch} 章剧情讨论（输入内容回车发送；'lock' 结束并固化细胞；'quit' 放弃）===")
    while True:
        reply = client.chat(msgs, tag=f"discuss-ch{ch:02d}")
        msgs.append({"role": "assistant", "content": reply})
        turns.append({"role": "ai", "content": reply})
        print(f"\n【编剧】\n{reply}\n")
        user = input("【你】> ").strip()
        if not user:
            continue
        if user == "quit":
            print("讨论放弃。")
            return
        if user == "lock":
            break
        msgs.append({"role": "user", "content": user})
        turns.append({"role": "user", "content": user})

    with open(log_path, "w", encoding="utf-8") as f:
        for t in turns:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    bible["chapters"][str(ch)] = {"status": "discussed", "discussion": log_path}
    save_bible(book, bible)
    print(f"\n讨论已存档：{log_path}\n下一步：python workbench.py lock {book} {ch}")


# ---------------- lock：讨论 → 细胞 ----------------

def cmd_lock(args):
    book, ch = args[0], int(args[1])
    bible = load_bible(book)
    meta = bible["chapters"].get(str(ch)) or {}
    log_path = meta.get("discussion")
    if not log_path or not os.path.exists(log_path):
        print("该章没有已存档的讨论。先 discuss。")
        return
    turns = [json.loads(l) for l in open(log_path, encoding="utf-8")]
    dialogue = "\n\n".join(f"【{'编剧' if t['role']=='ai' else '作者'}】{t['content']}" for t in turns)
    client = client_for(bible, "writer", book)
    lang = bible["book"].get("language", "zh")

    names = [c["name"] for c in bible["characters"]]
    if lang == "en":
        prompt = (f"Below is the co-writing discussion for chapter {ch}. Distill the agreed direction into ONE "
                  f"engine cell as strict JSON (no other text), keys: chapter(int), arc_label(str), "
                  f"amplitude(XL|L|M|S|B), plan, disruption, crisis, improvisation, end_hook(one of: "
                  f"new-information|dilemma|about-to-act|quiet-close), "
                  f"pressure: array of {{char(one of {names}), motive(want|need|wound|value|fear|contradiction), force, cost}}.\n"
                  f"Rules: pressure.force must share the same source as plan/disruption; visible cost required; "
                  f"chapter={ch}.\n\nDiscussion:\n{dialogue}")
    else:
        prompt = (f"以下是第 {ch} 章的联合编剧讨论记录。把已达成的方向提炼为一个引擎细胞，输出严格 JSON"
                  f"（不要其他文字），键：chapter(int)、arc_label(str)、amplitude(XL|L|M|S|B)、plan、disruption、"
                  f"crisis、improvisation、end_hook(新信息型|两难型|即将行动型|轻收束)、"
                  f"pressure: 数组，元素 {{char(限 {names})、motive(want|need|wound|value|fear|contradiction)、force、cost}}。\n"
                  f"规则：pressure.force 必须与 plan/disruption 同源；代价必须可见；chapter={ch}。\n\n讨论记录：\n{dialogue}")

    raw = client.chat([{"role": "user", "content": prompt}], tag=f"lock-ch{ch:02d}")
    m0, m1 = raw.find("{"), raw.rfind("}")
    if m0 < 0 or m1 <= m0:
        print("细胞生成失败（无 JSON）：", raw[:200])
        return
    try:
        cell = json.loads(raw[m0:m1 + 1])
    except json.JSONDecodeError as e:
        print("JSON 解析失败:", e, "\n原文：", raw[:300])
        return

    print(json.dumps(cell, ensure_ascii=False, indent=1))
    ok = input("确认固化此细胞？(y=确认 / 其他=放弃): ").strip().lower()
    if ok != "y":
        print("放弃。")
        return
    bible["chapters"][str(ch)]["cell"] = cell
    bible["chapters"][str(ch)]["status"] = "locked"
    # 弧线锚点回填
    anchors = bible["arc"].setdefault("anchors", [])
    tag = f"{cell.get('arc_label','')}@第{ch}章"
    if tag not in anchors:
        anchors.append(tag)
    save_bible(book, bible)
    print(f"\n第 {ch} 章细胞已锁定。下一步：python workbench.py write {book} {ch}")


# ---------------- write：落笔 ----------------

def bible_to_spec(bible):
    """把 story-bible 转成引擎 spec（复用 E 臂管线）。"""
    cells = []
    for k, meta in sorted(bible["chapters"].items(), key=lambda kv: int(kv[0])):
        if meta.get("cell"):
            cells.append(meta["cell"])
    return {
        "id": bible["book"]["title"],
        "language": bible["book"].get("language", "zh"),
        "title": bible["book"]["title"],
        "premise": bible["book"].get("logline", ""),
        "characters": bible["characters"],
        "beats": ["（工作台模式：见 engine.cells）"],
        "ledger": bible.get("ledger", []),
        "engine": {"template": bible["arc"].get("template", ""), "arc": [], "envelope": [], "cells": cells},
    }


def cmd_write(args):
    book, ch = args[0], int(args[1])
    bible = load_bible(book)
    meta = bible["chapters"].get(str(ch)) or {}
    if not meta.get("cell"):
        print("该章还没有锁定的细胞。先 discuss + lock。")
        return
    spec = bible_to_spec(bible)
    total = spec["engine"]["cells"][-1]["chapter"]
    cfg = load_config(os.path.join(ROOT, "experiments", "exp003"))
    client = client_for(bible, "writer", book)
    ledger = Ledger(spec)
    ch_path = os.path.join(ws_dir(book), "chapters", f"ch{ch:02d}.md")
    os.makedirs(os.path.dirname(ch_path), exist_ok=True)

    prev = []
    for p in range(1, ch):
        pp = os.path.join(ws_dir(book), "chapters", f"ch{p:02d}.md")
        if os.path.exists(pp):
            prev.append(open(pp, encoding="utf-8").read())
    msgs = build_writer_messages("E", spec, ledger, prev, ch)
    print(f"writing chapter {ch} ...")
    text = client.chat(msgs, tag=f"wb-ch{ch:02d}")

    # lint + 可选润色
    lint = lint_chapter(text, spec.get("language", "zh"))
    print("lint flags:", lint["flags"] or ["clean"])

    with open(ch_path, "w", encoding="utf-8") as f:
        f.write(text)
    bible["chapters"][str(ch)]["status"] = "written"
    save_bible(book, bible)
    print(f"\n落笔完成：{ch_path}（{len(text)} chars）")
    if spec.get("language", "zh") == "zh":
        print(f"金丝雀检查：{[e['canary'] for e in ledger.entries if e['canary'] in text and ch < e['reveal_chapter'] and ch != e['plant_chapter']] or '无泄漏'}")


# ---------------- status ----------------

def cmd_status(args):
    book = args[0]
    bible = load_bible(book)
    total = bible["arc"].get("total_chapters", 12)
    print(f"《{bible['book']['title']}》 {bible['book'].get('genre')} | {bible['book'].get('platform')} | {bible['book'].get('language')}")
    print(f"人物 {len(bible['characters'])} | 暗账 {len(bible.get('ledger', []))} 条 | 弧线 {bible['arc'].get('template')}")
    for ch in range(1, total + 1):
        meta = bible["chapters"].get(str(ch)) or {}
        status = meta.get("status", "empty")
        mark = {"empty": "·", "discussed": "◇", "locked": "◆", "written": "★"}.get(status, "?")
        cell = meta.get("cell") or {}
        print(f"  {mark} 第{ch:>2}章 [{status:<9}] {cell.get('arc_label','')} {cell.get('amplitude','')} {cell.get('plan','')[:30]}")


def main():
    cmds = {"new": cmd_new, "char": cmd_char, "discuss": cmd_discuss,
            "lock": cmd_lock, "write": cmd_write, "status": cmd_status}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        return
    if sys.argv[1] != "new" and len(sys.argv) < 3:
        print("缺书名参数。示例：python workbench.py status <书名>")
        return
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
