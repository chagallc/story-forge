#!/usr/bin/env python3
"""对照组实验：《了不起的盖茨比》开头（公版人类文本，1925，Project Gutenberg #64317）
同时喂朱雀 + GPTZero，裁决"DS flash 英文到底多 AI"。

GPTZero 判人类经典也 100% → 它对小说文体误报，我们的 31.8% 更可信
GPTZero 刟盖茨比低分而判我们 100% → DS flash 真的重，朱雀漏报
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")

GATSBY = """In my younger and more vulnerable years my father gave me some advice that I've been turning over in my mind ever since.

"Whenever you feel like criticizing any one," he told me, "just remember that all the people in this world haven't had the advantages that you've had."

He didn't say any more, but we've always been unusually intimate in a peculiar way, and I understood that he meant a great deal more than that. In consequence, I'm inclined to reserve all judgments, a habit that has opened up many curious natures to me and also made me the victim of not a few veteran bores. The abnormal mind is quick to detect and attach itself to this quality when it appears in a normal person, and so it came about that in college I was unjustly accused of being a politician, as I was, at one time or another, privy to the secret griefs of wild, unknown men. Most of the confidences were unsought — frequently I have feigned sleep, preoccupation, or a hostile levity when I realized by some unmistakable sign that an intimate revelation was quivering on the horizon; for the intimate revelations of young men, or at least the terms in which they express them, are usually plagiaristic and marred by obvious suppressions. Reserving judgments is a matter of infinite hope. I am still a little afraid of missing something if I forget that, as my father snobbishly suggested, and I snobbishly repeat, a sense of the fundamental decencies is parcelled out unequally at birth.

And, after boasting this way of my tolerance, I come to the admission that it has a limit. Conduct may be founded on the hard rock or the wet marshes, but after a certain point I don't care what it's founded on. When I came back from the East last autumn I felt that I wanted the world to be in uniform and at a sort of moral attention forever; I wanted no more riotous excursions with privileged glimpses into the human heart. Only Gatsby, the man who gives his name to this book, was exempt from my reaction — Gatsby, who represented everything for which I have an unaffected scorn. If personality is an unbroken series of successful gestures, then there was something gorgeous about him, some heightened sensitivity to the promises of life, as if he were related to one of those intricate machines that register earthquakes ten thousand miles away. This responsiveness had nothing to do with that flabby impressionability which is dignified under the name of the "creative temperament" — it was an extraordinary gift for hope, a romantic readiness such as I have never found in any other person and which it is not likely I shall ever find again. No — Gatsby turned out all right at the end; it is what preyed on Gatsby, what foul dust floated in the wake of his dreams that temporarily closed out my interest in the abortive sorrows and short-winded elations of men."""

out_dir = os.path.join(ROOT, "experiments", "_smoke_en", "runs", "control")
os.makedirs(out_dir, exist_ok=True)
ctrl_path = os.path.join(out_dir, "gatsby-ch1-excerpt.txt")
with open(ctrl_path, "w", encoding="utf-8") as f:
    f.write(GATSBY)
print(f"盖茨比对照样本: {len(GATSBY)} chars, {len(GATSBY.split())} words -> {ctrl_path}")

# 朱雀测人类文本
from tools.zhuque_api import detect  # noqa: E402

d = detect(GATSBY)
ratio = d.get("labels_ratio", {})
row = {"sample": "盖茨比（人类公版）", "human": round(ratio.get("0", 0) * 100, 1),
       "ai": round(ratio.get("1", 0) * 100, 1), "suspect": round(ratio.get("2", 0) * 100, 1),
       "softmax": d.get("softmax_confidence")}
print("朱雀判人类经典:", json.dumps(row, ensure_ascii=False))
json.dump(d, open(ctrl_path + ".zhuque.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# 同样保存 DS flash 的对照数据（已有）
print("\n对照表：")
print("  盖茨比(人类):", json.dumps(row, ensure_ascii=False))
ds = json.load(open(os.path.join(ROOT, "experiments", "_smoke_en", "runs", "model-compare", "ch01-deepseek-v4-flash.md.zhuque.json"), encoding="utf-8"))
dr = ds.get("labels_ratio", {})
print(f"  DS-flash引擎稿: 人工{round(dr.get('0',0)*100,1)}% AI{round(dr.get('1',0)*100,1)}% 疑似{round(dr.get('2',0)*100,1)}%")

# 生成 GPTZero 检测指令
print("\n下一步：把盖茨比样本注入 GPTZero（python tools/gptzero_fullflow.py 此文件路径）")
