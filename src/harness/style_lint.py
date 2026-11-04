"""章节级 AI 腔 lint：确定性、零 token、不退稿只报告。

检查项与阈值见 docs/style-guard.md。原则：风格信号只观察；
lint 结果作为 analyze 报告的一节，供人工与评审 agent 参考。
"""
import re

TEMPLATE_PHRASES = [
    "值得注意的是", "从某种意义上说", "仿佛在诉说", "空气仿佛凝固", "不知过了多久",
    "时光仿佛静止", "眼神里闪过一丝", "嘴角勾起一抹", "声音不大却清晰",
    "空气中弥漫着", "一股无形的压力", "说不清道不明", "某种难以言喻",
    "无声的呐喊", "内心深处",
]

OPPOSITION_RE = re.compile(r"不是[^。！？]{1,12}[，,]而是")
COLON_SUMMARY_RE = re.compile(r"[一-龥]{2,6}[：:]")
EURO_RE = re.compile(r"(?:^|[。！？」』\"\s])(?:被|使得|作为|对于)")
FOREIGN_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]{3,}(?![A-Za-z])")  # 独立外文词（中文正文异常）


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?]+", text)
    return [p for p in (s.strip() for s in parts) if p]


def lint_chapter(text: str) -> dict:
    n_chars = max(len(text), 1)
    n_k = n_chars / 1000
    sents = _sentences(text)
    lens = [len(s) for s in sents] or [0]
    mean_len = sum(lens) / len(lens)
    std = (sum((x - mean_len) ** 2 for x in lens) / len(lens)) ** 0.5 if len(lens) > 1 else 0.0
    cv = std / mean_len if mean_len else 0.0

    paras = [p for p in (q.strip() for q in text.split("\n")) if p]
    short_paras = [p for p in paras if len(p) <= 4]
    para_len = sum(len(p) for p in paras) / len(paras) if paras else 0

    checks = {
        "对仗句式": len(OPPOSITION_RE.findall(text)),
        "模板句": sum(text.count(p) for p in TEMPLATE_PHRASES) / n_k,
        "句长CV": round(cv, 3),
        "冒号总结腔": len(COLON_SUMMARY_RE.findall(text)) / n_k,
        "破折号密度": text.count("——") / n_k,
        "欧化腔": len(EURO_RE.findall(text)) / n_k,
        "外文混入": len(FOREIGN_RE.findall(text)),
        "超短段占比": len(short_paras) / len(paras) if paras else 0,
        "平均段长": round(para_len, 1),
    }

    flags = []
    if checks["对仗句式"] >= 2:
        flags.append("对仗句式≥2")
    if checks["模板句"] >= 1:
        flags.append("模板句超标")
    if 0 < checks["句长CV"] < 0.5:
        flags.append("句长过匀")
    if checks["冒号总结腔"] >= 3:
        flags.append("冒号总结腔")
    if checks["破折号密度"] >= 2:
        flags.append("破折号密度")
    if checks["欧化腔"] >= 2:
        flags.append("欧化腔")
    if checks["外文混入"] > 0:
        flags.append("外文词混入")
    if para_len < 60 and len(paras) > 20:
        flags.append("分节碎")
    if paras and checks["超短段占比"] > 0.15:
        flags.append("假深刻独词句")

    return {"checks": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in checks.items()},
            "flags": flags}


def lint_run(chapters: list[str]) -> dict:
    per_ch = [lint_chapter(t) for t in chapters]
    flagged = [i + 1 for i, r in enumerate(per_ch) if r["flags"]]
    return {
        "per_chapter": per_ch,
        "flagged_chapters": flagged,
        "summary": f"{len(flagged)}/{len(chapters)} 章触发观察级信号" + (f"：{flagged}" if flagged else ""),
    }
