#!/usr/bin/env python3
"""对已有 run 目录的章节做离线润色，产物写入 <run>-polished/，不覆盖原文件。

用法：python tools/polish-run.py <exp_name>/<run_name> [--lang zh|en]
润色前后 lint 对比自动打印。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.harness.config import load_config  # noqa: E402
from src.harness.llm import LLMClient  # noqa: E402
from src.harness.polish import Polisher  # noqa: E402
from src.harness.style_lint import lint_chapter  # noqa: E402


def main():
    run_ref = sys.argv[1]
    exp, run_name = run_ref.split("/", 1) if "/" in run_ref else ("exp002", run_ref)
    exp_dir = os.path.join(ROOT, "experiments", exp)
    run_dir = os.path.join(exp_dir, "runs", run_name)
    out_dir = run_dir + "-polished"
    os.makedirs(out_dir, exist_ok=True)

    spec = json.load(open(os.path.join(exp_dir, "spec.json"), encoding="utf-8"))
    lang = spec.get("language", "zh")
    cfg = load_config(exp_dir)
    pol_cfg = {**cfg["writer"]}
    if isinstance(cfg.get("polish"), dict):
        pol_cfg.update(cfg["polish"])
    client = LLMClient(pol_cfg, os.path.join(out_dir, "usage.jsonl"))
    polisher = Polisher(client, spec)

    ch_files = sorted(f for f in os.listdir(os.path.join(run_dir, "chapters")) if f.startswith("ch") and f.endswith(".md"))
    reports = []
    for fname in ch_files:
        text = open(os.path.join(run_dir, "chapters", fname), encoding="utf-8").read()
        before = lint_chapter(text, lang)
        ch_no = int(fname[2:4])
        polished, report = polisher.polish_chapter(text, ch_no)
        after = lint_chapter(polished, lang)
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(polished)
        reports.append({"file": fname, "flags_before": before["flags"], "flags_after": after["flags"],
                        "canary_intact": report["canary_intact"], "rounds": report["rounds"]})
        print(f"{fname}: {before['flags'] or ['clean']} -> {after['flags'] or ['clean']}  canary_intact={report['canary_intact']}")

    with open(os.path.join(out_dir, "polish-report.json"), "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    print(f"\npolished -> {out_dir}")


if __name__ == "__main__":
    main()
