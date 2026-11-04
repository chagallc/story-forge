"""实验配置加载：展开 $provider 引用并注入本地 key（config/models.local.json）。

config.json 中的 writer/reader 条目可写 {"$provider": "zhipu", "model": ...}，
展开时从 config/models.local.json 取 base_url 与 api_key（该文件不入 git）。
无 $provider 的条目照旧（兼容 exp001/exp002 的 api_key_env 方式）。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_PATH = os.path.join(ROOT, "config", "models.local.json")


def load_local() -> dict:
    if not os.path.exists(LOCAL_PATH):
        return {}
    with open(LOCAL_PATH, encoding="utf-8") as f:
        return json.load(f)


def expand_entry(entry: dict, local: dict) -> dict:
    if "$provider" not in entry:
        return entry
    prov = entry.pop("$provider")
    base = local.get(prov)
    if not base:
        raise KeyError(f"provider '{prov}' not in config/models.local.json")
    merged = dict(base)
    merged.update(entry)
    return merged


def load_config(exp_dir: str) -> dict:
    with open(os.path.join(exp_dir, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    local = load_local()
    for role in ("writer", "reader"):
        if role in cfg:
            cfg[role] = expand_entry(cfg[role], local)
    return cfg
