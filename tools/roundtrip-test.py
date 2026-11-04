#!/usr/bin/env python3
"""翻译往返实验（lynote-ai humanize-text 思路）：GLM英文 → 中文 → 回译英文 → 朱雀检测。

原理：两次翻译重组句法结构与用词分布，打乱 AI 检测器的统计指纹。
保护：金丝雀词/人名在往返中必须存活（翻译指令里硬约束 + 事后校验）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.harness.config import load_config  # noqa: E402
from src.harness.llm import LLMClient  # noqa: E402
from tools.zhuque_api import detect  # noqa: E402

spec = json.load(open(os.path.join(ROOT, "experiments", "_smoke_en", "spec.json"), encoding="utf-8"))
cfg = load_config(os.path.join(ROOT, "experiments", "_smoke_en"))
canaries = sorted({e["canary"] for e in spec.get("ledger", [])})
names = sorted({c["name"] for c in spec.get("characters", [])})

client = LLMClient(cfg["writer"], os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare", "usage-roundtrip.jsonl"))

src_path = os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare", "ch01-glm-5.3-flash.md")
text = open(src_path, encoding="utf-8").read()

# 第一步：英译中
zh_prompt = (
    "把下面的英文小说章节翻译成中文。要求：文学化翻译，句式自然，保留全部情节与对话含义。"
    f"以下词是专有标记，译文中必须保留原样：{', '.join(canaries + names)}\n\n正文：\n{text}"
)
zh = client.chat([{"role": "user", "content": zh_prompt}], tag="rt-en2zh")
print(f"中文版: {len(zh)} chars")

# 第二步：中译回英文
en_prompt = (
    "Translate the following Chinese novel chapter into English. Requirements: vivid serialized-web-fiction "
    "prose, natural varied sentence rhythms, concrete verbs, keep all plot events and dialogue meanings. "
    f"These strings are proper markers and must appear verbatim in the output: {', '.join(canaries + names)}\n\n"
    f"Chinese text:\n{zh}"
)
en = client.chat([{"role": "user", "content": en_prompt}], tag="rt-zh2en")
print(f"回译英文版: {len(en)} chars")

out_path = src_path.replace(".md", "-roundtrip.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(en)

lost = [m for m in canaries + names if m in text and m not in en]
print("标记存活检查:", "PASS" if not lost else f"LOST: {lost}")

after = detect(en)
row = {"stage": "GLM稿→翻译往返", "human": round(after["labels_ratio"].get("0", 0) * 100, 1),
       "ai": round(after["labels_ratio"].get("1", 0) * 100, 1),
       "suspect": round(after["labels_ratio"].get("2", 0) * 100, 1),
       "softmax": after.get("softmax_confidence"), "chars": len(en), "markers_lost": lost}
print(json.dumps(row, ensure_ascii=False))
json.dump(after, open(out_path + ".zhuque.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
