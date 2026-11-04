#!/usr/bin/env python3
"""DeepSeek 英文写作朱雀检测：v4-flash / v4-pro 各写一章同题英文。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.harness.agents import build_writer_messages  # noqa: E402
from src.harness.llm import LLMClient  # noqa: E402
from src.harness.ledger import Ledger  # noqa: E402
from tools.zhuque_api import detect  # noqa: E402

spec = json.load(open(os.path.join(ROOT, "experiments", "_smoke_en", "spec.json"), encoding="utf-8"))
ledger = Ledger(spec)
msgs = build_writer_messages("E", spec, ledger, [], 1)

catalog = json.load(open(os.path.expanduser("~/.hanako/provider-catalog.json"), encoding="utf-8"))["providers"]
ds = catalog["deepseek"]

OUT = os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare")
results = []
for model in ["deepseek-v4-flash", "deepseek-v4-pro"]:
    out_path = os.path.join(OUT, f"ch01-{model}.md")
    if os.path.exists(out_path):
        text = open(out_path, encoding="utf-8").read()
    else:
        client = LLMClient({"base_url": ds["base_url"], "api_key": ds["api_key"], "model": model,
                            "temperature": 0.8, "max_tokens": 8192},
                           os.path.join(OUT, "usage-ds.jsonl"))
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

print("\n=== DeepSeek 英文对比（AI占比越低越好） ===")
for r in results:
    print(f"{r['model']:20} 人工{r['human']:6}%  AI{r['ai']:6}%  疑似{r['suspect']:6}%  softmax={r['softmax']}")
