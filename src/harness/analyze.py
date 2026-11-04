"""试点批次快速分析：硬泄漏 + 软泄漏（读者猜测关键词命中）+ 张力曲线 + 钩子执行。

用法：python -m src.harness.analyze [runs...]（默认 A1/B1/C1）
"""
import glob
import json
import os
import sys

from .metrics import motive_curve, motive_flags
from .style_lint import lint_run

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS_DIR = os.path.join(ROOT, "experiments", "exp001", "runs")

# 每条暗账的"底牌关键词"：读者猜测文本命中即视为软泄漏信号（回收章之后命中不算）
F_KEYWORDS = {
    "F1": ["私生子", "兄长", "同父", "亲兄弟", "血缘", "兄弟"],
    "F2": ["换药", "停药", "降压药", "维生素", "药板", "换成"],
    "F3": ["安眠药", "下药", "自认凶手", "以为是凶手", "下了药"],
    "F4": ["矿难", "矿工", "复仇", "报仇", "矿主"],
    "F5": ["细线", "钓鱼线", "线轴", "门闩", "拉上", "密室手法"],
}
REVEAL_CH = {"F1": 7, "F2": 9, "F3": 10, "F4": 8, "F5": 6}
CANARIES = {"F1": "蓝鬃", "F2": "七弦", "F3": "锡盒", "F4": "鹤嘴", "F5": "冰弦"}


def load_chapters(run_dir):
    files = sorted(glob.glob(os.path.join(run_dir, "chapters", "ch*.md")))
    out = []
    for p in files:
        with open(p, encoding="utf-8") as f:
            out.append(f.read())
    return out


def load_reader(run_dir):
    files = sorted(glob.glob(os.path.join(run_dir, "reader", "ch*.json")))
    out = []
    for p in files:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        out.append(d if not d.get("parse_error") else {})
    return out


def analyze(run_ref: str):
    if "/" in run_ref:
        exp, run_name = run_ref.split("/", 1)
    else:
        exp, run_name = "exp001", run_ref
    run_dir = os.path.join(ROOT, "experiments", exp, "runs", run_name)
    chapters = load_chapters(run_dir)
    readers = load_reader(run_dir)

    # 金丝雀出现章（含回收章及之后）
    canary_presence = {f: [] for f in CANARIES}
    for idx, text in enumerate(chapters, start=1):
        for f, word in CANARIES.items():
            if word in text:
                canary_presence[f].append(idx)
    # 钩子执行：canary 在回收章（或之后一章内）出现
    hook_executed = {
        f: any(REVEAL_CH[f] <= ch <= REVEAL_CH[f] + 1 for ch in chs)
        for f, chs in canary_presence.items()
    }
    hard_leaks = {f: [ch for ch in chs if ch < REVEAL_CH[f]] for f, chs in canary_presence.items()}

    # 软泄漏：读者猜测命中底牌关键词（回收章之前）
    soft = []
    desire = []
    for idx, r in enumerate(readers, start=1):
        desire.append(r.get("desire_next"))
        for g in r.get("guesses", []) or []:
            content = str(g.get("content", ""))
            for f, kws in F_KEYWORDS.items():
                if idx < REVEAL_CH[f] and any(k in content for k in kws):
                    soft.append({
                        "foreshadow": f, "chapter": idx,
                        "confidence": g.get("confidence"),
                        "guess": content[:60],
                    })
                    break

    return {
        "run": run_name,
        "chapters": len(chapters),
        "avg_chars": round(sum(len(c) for c in chapters) / max(1, len(chapters))),
        "hard_leaks": {f: v for f, v in hard_leaks.items() if v},
        "hard_leak_count": sum(len(v) for v in hard_leaks.values()),
        "hook_executed_all": all(hook_executed.values()),
        "hook_executed": hook_executed,
        "soft_leak_first": {f: min([s["chapter"] for s in soft if s["foreshadow"] == f], default=None) for f in F_KEYWORDS},
        "soft_leak_count": len(soft),
        "soft_examples": soft[:6],
        "desire_curve": desire,
        "motive_curve": motive_curve(readers),
        "motive_flags": motive_flags(readers),
        "style_lint": lint_run(chapters),
    }


def main():
    runs = sys.argv[1:] or ["A1", "B1", "C1"]
    for r in runs:
        print(json.dumps(analyze(r), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
