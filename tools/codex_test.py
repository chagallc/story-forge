#!/usr/bin/env python3
"""GPT Codex OAuth 推理测试（流式 SSE）。"""
import json
import os
import sys
import urllib.request
import uuid

a = json.load(open(os.path.expanduser("~/.hanako/auth.json"), encoding="utf-8"))["openai-codex"]
tok, acct = a["access"], a["accountId"]

model = sys.argv[1] if len(sys.argv) > 1 else "gpt-5.6-terra"
prompt = sys.argv[2] if len(sys.argv) > 2 else "Reply with exactly two words: on line"

body = {
    "model": model,
    "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
    "max_output_tokens": 1024,
    "stream": True,
    "store": False,
}
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {tok}",
    "chatgpt-account-id": acct,
    "OpenAI-Beta": "responses=experimental",
    "session_id": str(uuid.uuid4()),
    "originator": "codex_cli_rs",
    "Accept": "text/event-stream",
}
req = urllib.request.Request(
    "https://chatgpt.com/backend-api/codex/responses",
    data=json.dumps(body).encode(),
    headers=headers,
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": "http://127.0.0.1:7897"}))
with opener.open(req, timeout=180) as resp:
    texts, model_used, usage = [], None, {}
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        etype = evt.get("type", "")
        if etype == "response.output_text.delta":
            texts.append(evt.get("delta", ""))
        elif etype == "response.completed":
            resp_obj = evt.get("response", {})
            model_used = resp_obj.get("model")
            usage = resp_obj.get("usage", {})
            for item in resp_obj.get("output", []):
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        texts.append(c.get("text", ""))
            break

out = "".join(texts).strip()
print("model:", model_used)
print("usage:", json.dumps(usage))
print("content:", repr(out[:200]))
