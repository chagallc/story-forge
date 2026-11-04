#!/usr/bin/env python3
"""朱雀 AIGC 检测 API 驱动（腾讯云 EdgeOne Makers @makers/zhuque-text）。

用法：python tools/zhuque_api.py <文本文件...>
凭证：D:\\credential\\朱雀阅读.txt（sk- 开头，不打印）
响应解读：labels_ratio "0"=人工 / "1"=AI / "2"=疑似AI；softmax_confidence 越大越可能 AI。
"""
import json
import os
import sys
import urllib.request

KEY_PATH = r"D:\credential\朱雀阅读.txt"
ENDPOINT = "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify"


def detect(text: str, is_merge: bool = True) -> dict:
    key = open(KEY_PATH, encoding="utf-8").read().strip()
    body = {"text": text, "is_merge": is_merge}
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def summarize(name: str, text: str) -> dict:
    data = detect(text)
    ratio = data.get("labels_ratio", {})
    row = {
        "sample": name,
        "chars": len(text),
        "human": round(ratio.get("0", 0) * 100, 1),
        "ai": round(ratio.get("1", 0) * 100, 1),
        "suspect": round(ratio.get("2", 0) * 100, 1),
        "softmax": data.get("softmax_confidence"),
        "status": data.get("status"),
        "tokens": data.get("makers_models_usage", {}).get("total_tokens"),
    }
    return row, data


def main():
    paths = sys.argv[1:]
    rows = []
    for p in paths:
        text = open(p, encoding="utf-8").read()
        label = p.replace("\\", "/").split("/")[-3] + "/" + p.replace("\\", "/").split("/")[-1]
        row, full = summarize(label, text)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
        # 保存完整分段结果供分析
        out = p + ".zhuque.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=1)
    print("\n=== 汇总（AI占比越低越好） ===")
    for r in rows:
        print(f"{r['sample']:50} 人工{r['human']:6}%  AI{r['ai']:6}%  疑似{r['suspect']:6}%  softmax={r['softmax']}")


if __name__ == "__main__":
    main()
