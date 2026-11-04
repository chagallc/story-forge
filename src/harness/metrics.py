"""金丝雀硬泄漏扫描：确定性，不经过任何 LLM。

规则：暗账条目的金丝雀词在回收章之前的章节出现 = 硬泄漏。
"""


def canary_hits(chapters: list[str], ledger) -> list[dict]:
    hits = []
    for idx, text in enumerate(chapters, start=1):
        for e in ledger.entries:
            if idx < e["reveal_chapter"] and e["canary"] in text:
                hits.append({
                    "chapter": idx,
                    "foreshadow": e["id"],
                    "canary": e["canary"],
                    "reveal_chapter": e["reveal_chapter"],
                })
    return hits


def desire_curve(reader_results: list[dict]) -> list[int]:
    """从读者 JSON 里提取逐章欲望分，构成张力曲线。"""
    curve = []
    for r in reader_results:
        v = r.get("desire_next")
        curve.append(v if isinstance(v, int) else None)
    return curve


def motive_curve(reader_results: list[dict]) -> list[float | None]:
    """逐章人物行动可信度均值曲线（动机压力层验收指标）。"""
    curve = []
    for r in reader_results:
        checks = r.get("motive_check") or []
        scores = [c.get("believable") for c in checks if isinstance(c.get("believable"), (int, float))]
        curve.append(round(sum(scores) / len(scores), 2) if scores else None)
    return curve


def motive_flags(reader_results: list[dict]) -> list[dict]:
    """汇总所有可信度 ≤5 的行动（出戏行动清单）。"""
    flags = []
    for idx, r in enumerate(reader_results, start=1):
        for c in r.get("motive_check") or []:
            if isinstance(c.get("believable"), (int, float)) and c["believable"] <= 5:
                flags.append({"chapter": idx, **c})
    return flags
