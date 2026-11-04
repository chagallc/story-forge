#!/usr/bin/env python3
"""异构润色实验：用 K3.1-pro（Kimi）润色 GLM 的英文稿，朱雀前后对比。

背景：GLM 润色 GLM 使 AI 率 44.5%→72.5%（同族润色失效假设）。
假设：换家族润色能打破统计指纹。
"""
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

kimi_cfg = {**cfg["writer"], "api_key": local["kimi"]["api_key"], "base_url": local["kimi"]["base_url"],
            "model": "k3.1-pro", "temperature": 1, "max_tokens": 8192, "extra_body": {}}
client = LLMClient(kimi_cfg, os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare", "usage-polish.jsonl"))
polisher = Polisher(client, spec)

src_path = os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare", "ch01-glm-5.3-flash.md")
text = open(src_path, encoding="utf-8").read()
before = detect(text)
print("BEFORE: ai =", round(before["labels_ratio"].get("1", 0) * 100, 1),
      "human =", round(before["labels_ratio"].get("0", 0) * 100, 1),
      "softmax =", before.get("softmax_confidence"))

polished, report = polisher.polish_chapter(text, 1, tag="xeno-glm2k3-")
print("polish rounds:", len(report["rounds"]), "canary_intact:", report["canary_intact"],
      "flags_after:", report.get("flags_after"))

out_path = src_path.replace(".md", "-k3polished.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(polished)

after = detect(polished)
print("AFTER:  ai =", round(after["labels_ratio"].get("1", 0) * 100, 1),
      "human =", round(after["labels_ratio"].get("0", 0) * 100, 1),
      "softmax =", after.get("softmax_confidence"))
json.dump(after, open(out_path + ".zhuque.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
