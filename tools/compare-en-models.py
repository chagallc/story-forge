#!/usr/bin/env python3
"""英文写作模型对比：同 prompt 三家各写一章 → 朱雀检测 AI 占比。

对比对象：glm-5.3-flash / k3.1-pro / qwen3.8-max
写作 prompt 直接复用引擎的 E 臂组装器（真实际化路径）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.harness.agents import build_writer_messages  # noqa: E402
from src.harness.config import load_config  # noqa: E402
from src.harness.ledger import Ledger  # noqa: E402
from src.harness.llm import LLMClient  # noqa: E402
from tools.zhuque_api import detect  # noqa: E402

spec = json.load(open(os.path.join(ROOT, "experiments", "_smoke_en", "spec.json"), encoding="utf-8"))
cfg = load_config(os.path.join(ROOT, "experiments", "_smoke_en"))
ledger = Ledger(spec)

MODELS = [
    ("glm-5.3-flash", {"model": "glm-5.3-flash", "temperature": 0.8, "max_tokens": 8192,
                       "api_key": cfg["writer"]["api_key"], "base_url": cfg["writer"]["base_url"],
                       "extra_body": {"thinking": {"type": "disabled"}}}),
]

# kimi / qwen key 从 models.local.json 读
local = json.load(open(os.path.join(ROOT, "config", "models.local.json"), encoding="utf-8"))
MODELS.append(("k3.1-pro", {"api_key": local["kimi"]["api_key"], "base_url": local["kimi"]["base_url"],
                           "model": "k3.1-pro", "temperature": 1, "max_tokens": 8192}))
MODELS.append(("qwen3.8-max", {"api_key": local["qwen"]["api_key"], "base_url": local["qwen"]["base_url"],
                               "model": "qwen3.8-max", "temperature": 0.8, "max_tokens": 8192}))

OUT = os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare")
os.makedirs(OUT, exist_ok=True)

# 已有产物的模型跳过（断点续跑）
DONE = {f[5:-3] for f in os.listdir(OUT) if f.startswith("ch01-") and f.endswith(".md")}
MODELS = [(n, c) for n, c in MODELS if n not in DONE]

msgs = build_writer_messages("E", spec, ledger, [], 1)
results = []
for name, mcfg in MODELS:
    client = LLMClient(mcfg, os.path.join(OUT, "usage.jsonl"))
    print(f"writing with {name} ...")
    text = client.chat(msgs, tag=f"compare-{name}")
    with open(os.path.join(OUT, f"ch01-{name}.md"), "w", encoding="utf-8") as f:
        f.write(text)
    d = detect(text)
    ratio = d.get("labels_ratio", {})
    row = {"model": name, "chars": len(text),
           "human": round(ratio.get("0", 0) * 100, 1), "ai": round(ratio.get("1", 0) * 100, 1),
           "suspect": round(ratio.get("2", 0) * 100, 1), "softmax": d.get("softmax_confidence")}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False))

print("\n=== 英文写作模型对比（AI占比越低越好） ===")
for r in sorted(results, key=lambda x: x["ai"]):
    print(f"{r['model']:16} 人工{r['human']:6}%  AI{r['ai']:6}%  疑似{r['suspect']:6}%  softmax={r['softmax']}")
