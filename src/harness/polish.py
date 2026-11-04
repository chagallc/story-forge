"""润色层（第三防线）：lint 定向修复，不做全面重写。

原则（决策 0004 / shuorenhua 思想）：
- 只修 lint flags 列出的问题，evidence 给出命中句，改写有靶子
- 硬性禁区：情节、事件、对话含义、信息揭示顺序不动；金丝雀词与人名原样保留
- Tier 意识：超标处修复即止，不过度打磨，不磨掉刻意保留的粗粝质感
- 修复后复验 lint，最多两轮
"""
import json

from .style_lint import lint_chapter

POLISH_SYSTEM = {
    "zh": "你是一位挑剔的中文文学编辑。你的任务是消除文本中的机器腔，让文字回到人写的质感。你只做编辑，不做作者。",
    "en": "You are a demanding English-language fiction editor. Your task is to remove machine-flavored "
          "prose and restore human texture. You are an editor, not a co-author.",
}

POLISH_PROMPT = {
    "zh": (
        "以下是本章正文。编辑任务：只修复【修复目标】列出的问题，其余一字不动。\n\n"
        "【硬性禁区】\n"
        "- 不得改变任何情节、事件、对话含义、信息揭示顺序\n"
        "- 不得改动人物名、地名、物品名\n"
        "- 以下词是叙事标记，必须原样保留、不得改写或删除：{canaries}\n"
        "- 不得新增总结式句子、不得新增解释\n\n"
        "【修复目标】（lint 检出）\n{targets}\n\n"
        "【命中句样本】（这些句子必须改写；其余句子尽量不动）\n{evidence}\n\n"
        "【改写要求】\n"
        "- 用具体动作和细节替代模板腔；删掉总结腔而非改写它\n"
        "- 破折号改用逗号或句号；外文词换成中文说法\n"
        "- 保留原有口吻、节奏与粗粝感，不要把文字磨光\n\n"
        "直接输出修改后的全文，不要任何说明。"
    ),
    "en": (
        "Below is the chapter text. Editing task: fix ONLY the issues listed under TARGETS; touch nothing else.\n\n"
        "[HARD CONSTRAINTS]\n"
        "- Do not change any plot event, dialogue meaning, or information reveal order\n"
        "- Do not alter character names, place names, or item names\n"
        "- These strings are narrative markers; keep them verbatim: {canaries}\n"
        "- Do not add summarizing or explanatory sentences\n\n"
        "[TARGETS] (lint findings)\n{targets}\n\n"
        "[HIT SENTENCES] (these must be rewritten; leave other sentences alone)\n{evidence}\n\n"
        "[CRAFT RULES]\n"
        "- Replace stock beats with concrete action and specific detail; delete summarizing closers rather than rephrasing them\n"
        "- Replace em-dashes with commas or periods\n"
        "- Keep the existing voice, rhythm and rough edges; do not polish the text smooth\n\n"
        "Output only the full revised text, no commentary."
    ),
}


def _format_targets(flags: list[str]) -> str:
    return "\n".join(f"- {f}" for f in flags)


def _format_evidence(evidence: dict) -> str:
    if not evidence:
        return "（无具体命中句，按目标全局自查）"
    lines = []
    for k, samples in evidence.items():
        lines.append(f"[{k}]")
        lines.extend(f"  {s}" for s in samples)
    return "\n".join(lines)


class Polisher:
    """lint 驱动的定向润色。client 是专用 LLMClient（可复用 writer 模型）。"""

    def __init__(self, client, spec: dict, max_rounds: int = 2):
        self.client = client
        self.lang = spec.get("language", "zh")
        self.canaries = sorted({e["canary"] for e in spec.get("ledger", [])})
        self.names = sorted({c["name"] for c in spec.get("characters", [])})
        self.max_rounds = max_rounds
        self.rounds_used = 0

    def polish_chapter(self, text: str, chapter: int, *, tag: str = "") -> tuple[str, dict]:
        """返回 (润色后文本, 报告)。报告含每轮 flags 与最终 canary 完整性。"""
        report = {"chapter": chapter, "rounds": [], "canary_intact": True}
        cur = text
        for rnd in range(1, self.max_rounds + 1):
            lint = lint_chapter(cur, self.lang)
            if not lint["flags"]:
                break
            prompt = POLISH_PROMPT[self.lang].format(
                canaries="、".join(self.canaries + self.names) if self.lang == "zh"
                else ", ".join(self.canaries + self.names),
                targets=_format_targets(lint["flags"]),
                evidence=_format_evidence(lint.get("evidence", {})),
            )
            msgs = [
                {"role": "system", "content": POLISH_SYSTEM[self.lang]},
                {"role": "user", "content": prompt + "\n\n【正文】\n" + cur},
            ]
            polished = self.client.chat(msgs, tag=f"{tag}polish-ch{chapter:02d}-r{rnd}").strip()
            round_info = {"round": rnd, "flags_before": lint["flags"], "changed_chars": len(polished) - len(cur)}
            # 金丝雀完整性检查：原文本含有的金丝雀词，润色后不得丢失
            lost = [c for c in self.canaries if c in cur and c not in polished]
            lost += [n for n in self.names if n in cur and n not in polished]
            if lost:
                round_info["lost_markers"] = lost
                report["canary_intact"] = False
                # 回滚本轮：安全优先
                break
            cur = polished
            report["rounds"].append(round_info)
            self.rounds_used += 1
        final_lint = lint_chapter(cur, self.lang)
        report["flags_after"] = final_lint["flags"]
        report["resolved"] = not final_lint["flags"]
        return cur, report


def polish_run(chapters: list[str], polisher: Polisher) -> tuple[list[str], list[dict]]:
    out, reports = [], []
    for i, text in enumerate(chapters, start=1):
        polished, report = polisher.polish_chapter(text, i)
        out.append(polished)
        reports.append(report)
    return out, reports
