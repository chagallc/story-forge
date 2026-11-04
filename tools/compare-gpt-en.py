#!/usr/bin/env python3
"""GPT 英文写作对比：gpt-5.6-terra / gpt-5.5 各写一章同题英文 → 朱雀检测。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.harness.agents import build_writer_messages  # noqa: E402
from src.harness.llm import CodexClient  # noqa: E402
from src.harness.ledger import Ledger  # noqa: E402
from tools.zhuque_api import detect  # noqa: E402

spec = json.load(open(os.path.join(ROOT, "experiments", "_smoke_en", "spec.json"), encoding="utf-8"))
ledger = Ledger(spec)
msgs = build_writer_messages("E", spec, ledger, [], 1)

OUT = os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare")
os.makedirs(OUT, exist_ok=True)

models = sys.argv[1:] or ["gpt-5.6-terra", "gpt-5.5"]
results = []
for model in models:
    out_path = os.path.join(OUT, f"ch01-{model}.md")
    if os.path.exists(out_path):
        text = open(out_path, encoding="utf-8").read()
        print(f"{model}: resumed from disk ({len(text)} chars)")
    else:
        client = CodexClient({"model": model, "max_tokens": 12288, "budget": 200000},
                             os.path.join(OUT, "usage-codex.jsonl"))
        print(f"writing with {model} ...")
        text = client.chat(msgs, tag=f"compare-{model}")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    d = detect(text)
    ratio = d.get("labels_ratio", {})
    row = {"model": model, "chars": len(text),
           "human": round(ratio.get("0", 0) * 100, 1), "ai": round(ratio.get("1", 0) * 100, 1),
           "suspect": round(ratio.get("2", 0) * 100, 1), "softmax": d.get("softmax_confidence")}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False))
    json.dump(d, open(out_path + ".zhuque.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("\n=== GPT 英文对比（AI占比越低越好；DS-flash 基准 31.8%） ===")
for r in results:
    print(f"{r['model']:16} 人工{r['human']:6}%  AI{r['ai']:6}%  疑似{r['suspect']:6}%  softmax={r['softmax']}")
