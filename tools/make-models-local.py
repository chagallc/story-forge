#!/usr/bin/env python3
"""从 Hana provider-catalog.json 生成 story-forge/config/models.local.json。

产物含 key，已被 .gitignore 排除，绝不入库。
"""
import json
import os

CATALOG = os.path.expanduser("~/.hanako/provider-catalog.json")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "models.local.json")

# 引擎使用的 provider 映射：本地别名 -> catalog 键
MAPPING = {
    "zhipu": "zhipu-coding",
    "kimi": "kimi-coding",
    "qwen": "qwen",
}

catalog = json.load(open(CATALOG, encoding="utf-8"))["providers"]
local = {}
for alias, key in MAPPING.items():
    p = catalog.get(key, {})
    if p.get("api_key") and p.get("base_url"):
        local[alias] = {"base_url": p["base_url"], "api_key": p["api_key"]}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(local, f, ensure_ascii=False, indent=2)
print(f"written: {OUT}")
for k, v in local.items():
    print(f"  {k}: {v['base_url']} (key {len(v['api_key'])} chars)")
