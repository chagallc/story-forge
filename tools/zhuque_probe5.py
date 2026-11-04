#!/usr/bin/env python3
"""取朱雀页面上 API 文档链接。"""
import json
import sys

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

r = evaluate(
    'JSON.stringify(Array.from(document.querySelectorAll("a")).map(function(a){return {t: a.innerText.trim().slice(0,20), h: a.href}}).filter(function(x){return x.t.indexOf("API") >= 0 || (x.h||"").indexOf("api") >= 0 || (x.h||"").indexOf("doc") >= 0}))',
    "ai-detect",
)
print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
