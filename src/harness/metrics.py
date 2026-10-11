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
