#!/usr/bin/env python3
"""Qwen3.8-max 异构润色实验：GLM 稿（AI 52.7%）→ Qwen 润色 → 朱雀前后对比。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.harness.config import load_config  # noqa: E402
from src.harness.llm import LLMClient  # noqa: E402
from src.harness.polish import Polisher  # noqa: E402
from tools.zhuque_api import detect  # noqa: E402

spec = json.load(open(os.path.join(ROOT, "experiments", "_smoke_en", "spec.json"), encoding="utf-8"))
cfg = load_config(os.path.join(ROOT, "experiments", "_smoke_en"))
local = json.load(open(os.path.join(ROOT, "config", "models.local.json"), encoding="utf-8"))

qwen_cfg = {**cfg["writer"], "api_key": local["qwen"]["api_key"], "base_url": local["qwen"]["base_url"],
            "model": "qwen3.8-max", "temperature": 0.8, "max_tokens": 8192, "extra_body": {}}
client = LLMClient(qwen_cfg, os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare", "usage-polish-qwen.jsonl"))
polisher = Polisher(client, spec)

src_path = os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare", "ch01-glm-5.3-flash.md")
text = open(src_path, encoding="utf-8").read()

polished, report = polisher.polish_chapter(text, 1, tag="xeno-glm2qwen-")
print("polish rounds:", len(report["rounds"]), "canary_intact:", report["canary_intact"],
      "flags_after:", report.get("flags_after"))

out_path = src_path.replace(".md", "-qwenpolished.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(polished)

after = detect(polished)
row = {"stage": "GLM稿→Qwen润色", "human": round(after["labels_ratio"].get("0", 0) * 100, 1),
       "ai": round(after["labels_ratio"].get("1", 0) * 100, 1),
       "suspect": round(after["labels_ratio"].get("2", 0) * 100, 1),
       "softmax": after.get("softmax_confidence"), "chars": len(polished)}
print(json.dumps(row, ensure_ascii=False))
json.dump(after, open(out_path + ".zhuque.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
