"""章节级 AI 腔 lint：确定性、零 token、不退稿只报告。

检查项与阈值见 docs/style-guard.md。原则：风格信号只观察；
lint 结果作为 analyze 报告的一节，供人工与评审 agent 参考。
"""
import re

# ---------- 中文规则（zh） ----------

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


# ---------- 英文规则（en） ----------

EN_SLOP_WORDS = [
    "delve", "tapestry", "testament", "embark", "navigate", "shimmer", "myriad",
    "intricate", "palpable", "ethereal", "mesmerizing", "captivating", "enthralling",
    "breathtaking", "awe-inspiring", "symphony", "kaleidoscope", "unspoken",
]
EN_SLOP_RE = re.compile(
    r"\b(" + "|".join(EN_SLOP_WORDS) + r")\b", re.IGNORECASE)
EN_NOT_JUST_RE = re.compile(
    r"\bnot (?:just|merely|only|simply) [^.!?]{1,60}\b(?:but|rather|it was)\b", re.IGNORECASE)
EN_WASNT_JUST_RE = re.compile(r"\b(?:was|were)n't just\b", re.IGNORECASE)
EN_STOCK_BEATS = [
    "breath she didn't know she was holding", "breath he didn't know he was holding",
    "little did she know", "little did he know", "little did they know",
    "something shifted", "the air was thick with", "and then, everything changed",
    "time seemed to slow", "the weight of the world",
]
EN_EYES_RE = re.compile(r"eyes (?:gleamed|glinted|darkened|softened) with", re.IGNORECASE)
EN_PARTICIPIAL_RE = re.compile(
    r", (?:signaling|marking|bringing|heralding|promising|heralding) ", re.IGNORECASE)
EN_LY_RE = re.compile(r"\b\w+ly\b")
EN_TRICOLON_RE = re.compile(r"\w+, \w+, and \w+[.!?\"]\s*$")


def lint_chapter_en(text: str) -> dict:
    words = len(re.findall(r"\b\w+\b", text))
    n_500 = max(words / 500, 0.001)
    sents = _sentences(text)
    lens = [len(s.split()) for s in sents] or [0]
    mean_len = sum(lens) / len(lens)
    std = (sum((x - mean_len) ** 2 for x in lens) / len(lens)) ** 0.5 if len(lens) > 1 else 0.0
    cv = std / mean_len if mean_len else 0.0

    checks = {
        "not-just-but": len(EN_NOT_JUST_RE.findall(text)) + len(EN_WASNT_JUST_RE.findall(text)),
        "slop词密度": round(len(EN_SLOP_RE.findall(text)) / n_500, 3),
        "stock beats": sum(text.lower().count(p) for p in EN_STOCK_BEATS) + len(EN_EYES_RE.findall(text)),
        "句长CV": round(cv, 3),
        "em-dash密度": round(text.count("—") / n_500, 3),
        "participial tail": len(EN_PARTICIPIAL_RE.findall(text)),
        "-ly副词密度": round(len(EN_LY_RE.findall(text)) / n_500, 3),
        "词数": words,
    }
    closer = sents[-1] if sents else ""
    checks["tricolon收尾"] = 1 if EN_TRICOLON_RE.search(closer.strip()) else 0

    flags = []
    if checks["not-just-but"] >= 2:
        flags.append("not-just-but×2+")
    if checks["slop词密度"] >= 1:
        flags.append("slop词超标")
    if checks["stock beats"] > 0:
        flags.append("stock beats")
    if 0 < checks["句长CV"] < 0.45:
        flags.append("句长过匀")
    if checks["em-dash密度"] >= 2:
        flags.append("em-dash超标")
    if checks["participial tail"] >= 2:
        flags.append("participial尾巴")
    if checks["-ly副词密度"] >= 8:
        flags.append("-ly副词堆叠")
    if checks["tricolon收尾"]:
        flags.append("tricolon收尾")
    return {"checks": checks, "flags": flags}


def lint_chapter(text: str, lang: str = "zh") -> dict:
    if lang == "en":
        return lint_chapter_en(text)
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


def lint_run(chapters: list[str], lang: str = "zh") -> dict:
    per_ch = [lint_chapter(t, lang) for t in chapters]
    flagged = [i + 1 for i, r in enumerate(per_ch) if r["flags"]]
    return {
        "per_chapter": per_ch,
        "flagged_chapters": flagged,
        "summary": f"{len(flagged)}/{len(chapters)} 章触发观察级信号" + (f"：{flagged}" if flagged else ""),
    }
