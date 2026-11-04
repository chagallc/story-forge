#!/usr/bin/env python3
"""story-forge 模型阵容连通性测试。

从 Hana provider-catalog.json 读各家 key，对六条线各发一个最小 chat 请求。
key 只在内存中使用，不打印、不落盘。
"""
import json
import os
import sys
import urllib.request

CATALOG = os.path.expanduser("~/.hanako/provider-catalog.json")
BALANCE = os.path.expanduser("~/.hanako/plugin-data/token-tracker/balance-config.json")
PROXY = "http://127.0.0.1:7897"

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

catalog = load(CATALOG)["providers"]

def chat(base, key, model, proxy=False, max_tokens=32):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：在线"}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    handler = urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}) if proxy else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with opener.open(req, timeout=60) as r:
        data = json.load(r)
    msg = data["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    usage = data.get("usage", {})
    return content[:40], usage.get("total_tokens")

def codex_oauth(token, model="gpt-5.6-terra"):
    """ChatGPT OAuth 走 codex responses 端点。"""
    body = {
        "model": model,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "回复两个字：在线"}]}],
        "max_output_tokens": 64,
        "stream": False,
    }
    handler = urllib.request.ProxyHandler({"https": PROXY, "http": PROXY})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(
        "https://chatgpt.com/backend-api/codex/responses",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with opener.open(req, timeout=90) as r:
        data = json.load(r)
    texts = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                texts.append(c.get("text", ""))
    return (" ".join(texts).strip()[:40], data.get("usage", {}).get("total_tokens"))

tests = []

zp = catalog.get("zhipu-coding", {})
if zp.get("api_key"):
    tests.append(("zhipu glm-5.3-flash (主力)", zp["base_url"], zp["api_key"], "glm-5.3-flash", False))
    tests.append(("zhipu glm-5.3", zp["base_url"], zp["api_key"], "glm-5.3", False))

km = catalog.get("kimi-coding", {})
if km.get("api_key"):
    tests.append(("kimi k3.1-pro", km["base_url"], km["api_key"], "k3.1-pro", False))

qw = catalog.get("qwen", {})
if qw.get("api_key"):
    tests.append(("qwen qwen3.8-max", qw["base_url"], qw["api_key"], "qwen3.8-max", False))
    tests.append(("qwen qwen3.8-flash", qw["base_url"], qw["api_key"], "qwen3.8-flash", False))

only = sys.argv[1] if len(sys.argv) > 1 else None
results = {}
for name, base, key, model, proxy in tests:
    if only and only not in name:
        continue
    try:
        content, tok = chat(base, key, model, proxy)
        results[name] = "OK"
        print(f"[OK]   {name:30} -> {content!r}  (tokens={tok})")
    except Exception as e:
        results[name] = f"FAIL: {e}"
        msg = str(e)[:160]
        print(f"[FAIL] {name:30} -> {msg}")

if "gpt" in (only or "gpt") or not only:
    try:
        bal = load(BALANCE)
        token = bal.get("gptOAuthToken")
        if token:
            content, tok = codex_oauth(token)
            print(f"[OK]   gpt-5.6-terra (codex oauth)  -> {content!r}  (tokens={tok})")
            results["gpt"] = "OK"
        else:
            print("[SKIP] gpt: 无 OAuth token")
    except Exception as e:
        print(f"[FAIL] gpt-5.6-terra (codex oauth)  -> {str(e)[:200]}")
        results["gpt"] = "FAIL"

print("\n汇总:", json.dumps(results, ensure_ascii=False))
