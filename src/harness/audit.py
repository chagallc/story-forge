"""合理性审核层（v1）：LLM 剧情逻辑评审。

挂在 write/revise 之后（draft 阶段），结果进 report 供作者查看。
审核是提示性的（不拦截落笔/不自动改正文）——与 M3A 遗漏检测互补：
遗漏检测管「该记的状态没记」（确定性），本层管「写出来的剧情合不合理」（语义层）。

client 由调用方注入（与 graph.py 同模式，本模块零网络零状态）。
建议用与 writer 异构的模型（reader 通道），避免作者模型自我确认。
"""

import json
import re

LOGIC_REVIEW_PROMPT = {
    "zh": (
        "你是连载小说的连续性审稿人。审出下面这一章的合理性问题，"
        "只报有把握的问题（不吹毛求疵、不评价文笔）。严格 JSON 输出（无其他文字）：\n"
        '{{"issues": [{{"type": "因果断裂|巧合堆砌|人物OOC|时间线矛盾|设定冲突", '
        '"severity": "high|medium|low", "quote": "原文引用", "explanation": "一句话说明"}}]}}\n'
        "没有问题则 issues 为空数组。\n\n"
        "【人物动机栈（行动必须能从这里推出）】\n{motive_stack}\n\n"
        "【前一章结尾（连续性基准）】\n{prev_tail}\n\n"
        "【本章正文】\n{draft_text}"
    ),
    "en": (
        "You are a continuity editor for a serialized novel. Review the chapter below for "
        "plausibility problems. Report only confident issues. Output strict JSON (nothing else):\n"
        '{{"issues": [{{"type": "broken causality|coincidence pileup|character OOC|'
        'timeline contradiction|setting conflict", "severity": "high|medium|low", '
        '"quote": "quote from text", "explanation": "one sentence"}}]}}\n'
        "Empty issues array if none.\n\n"
        "[Character motive stacks (actions must be derivable from these)]\n{motive_stack}\n\n"
        "[Previous chapter ending (continuity baseline)]\n{prev_tail}\n\n"
        "[Chapter text]\n{draft_text}"
    ),
}

VALID_TYPES = {
    "zh": {"因果断裂", "巧合堆砌", "人物OOC", "时间线矛盾", "设定冲突"},
    "en": {"broken causality", "coincidence pileup", "character OOC",
           "timeline contradiction", "setting conflict"},
}


def motive_stack_summary(bible) -> str:
    """人物动机栈压缩摘要（评审用：只要 want/fear/contradiction/voice）。"""
    lines = []
    for c in bible.get("characters", []):
        parts = [f"【{c.get('name')}】{c.get('card', '')}"]
        for k in ("want", "fear", "contradiction"):
            if c.get(k):
                parts.append(f"  {k}：{c[k]}")
        v = c.get("voice") or {}
        if v.get("catchphrases"):
            parts.append(f"  口头禅：{v['catchphrases']}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def parse_logic_review(raw: str, lang: str = "zh") -> dict:
    """宽容解析评审 JSON；解析失败返回可读错误。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"issues": [], "parse_error": raw[:200]}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"issues": [], "parse_error": raw[:200]}
    issues = []
    valid = VALID_TYPES.get(lang, set()) | {"因果断裂", "巧合堆砌", "人物OOC", "时间线矛盾", "设定冲突"}
    for it in data.get("issues", []):
        if not isinstance(it, dict):
            continue
        t = str(it.get("type", "")).strip()
        issues.append({
            "type": t if t in valid else "设定冲突" if lang == "zh" else "setting conflict",
            "severity": it.get("severity") if it.get("severity") in ("high", "medium", "low") else "medium",
            "quote": str(it.get("quote", ""))[:120],
            "explanation": str(it.get("explanation", ""))[:200],
        })
    return {"issues": issues}


def audit_chapter(bible, ch, draft_text, prev_tail, client, lang=None) -> dict:
    """LLM 剧情逻辑评审。client 由调用方注入（建议 reader 通道，与 writer 异构）。

    返回 {"issues": [...], "model": str}。抛异常由调用方决定是否阻塞
    （约定：审核失败不阻塞落笔/微调，只降级为无审核结果）。
    """
    lang = lang or bible.get("book", {}).get("language", "zh")
    prompt = LOGIC_REVIEW_PROMPT[lang].format(
        ch=ch, motive_stack=motive_stack_summary(bible),
        prev_tail=prev_tail[:600] or "（无）", draft_text=draft_text)
    raw = client.chat(
        [{"role": "user", "content": prompt}], tag=f"audit-ch{ch:02d}")
    parsed = parse_logic_review(raw)
    parsed["model"] = getattr(client, "model", "?")
    return parsed


def audit_summary(audit_result: dict) -> str:
    """人读摘要：⚠️ N 项（high X / medium Y）或 ✅ 无问题。"""
    issues = audit_result.get("issues", [])
    if not issues:
        return "✅ 合理性审核：无问题"
    high = sum(1 for i in issues if i.get("severity") == "high")
    med = sum(1 for i in issues if i.get("severity") == "medium")
    return f"⚠️ 合理性审核：{len(issues)} 项（high {high} / medium {med}）"
