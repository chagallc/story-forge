"""三个角色的 prompt 组装：writer（三臂三种可见性）、reader（只读正文的模拟读者）。"""
import json
import re

WRITER_SYSTEM = (
    "你是一位中文悬疑小说家。要求：每章约1000字；以场景、动作、对白推进故事，"
    "靠细节与潜台词制造悬念；禁止上帝视角解释人物动机；禁止总结式收尾；"
    "严格遵循给定的大纲与指令。输出纯正文，不要标题、不要注释。"
)

READER_SYSTEM = (
    "你是一位普通悬疑小说读者，从未看过本书的任何设定资料，只读已发表的正文章节。"
    "请诚实给出你的阅读反应，不装聪明也不装笨。"
)


def _story_block(spec: dict) -> str:
    chars = "\n".join(f"- {c['name']}：{c['card']}" for c in spec["characters"])
    beats = "\n".join(spec["beats"])
    return (
        f"《{spec['title']}》\n\n前提：{spec['premise']}\n\n"
        f"人物：\n{chars}\n\n全书大纲：\n{beats}"
    )


def _history_block(chapters: list[str]) -> str:
    if not chapters:
        return "（这是第一章，暂无前文）"
    parts = [f"【第{i}章】\n{text}" for i, text in enumerate(chapters, start=1)]
    return "已完成的章节：\n\n" + "\n\n".join(parts)


def build_writer_messages(arm: str, spec: dict, ledger, chapters: list[str], chapter: int):
    """按臂组装写作上下文。arm: A=单体全知 / B=分工无墙 / C=分工有墙。"""
    blocks = [_story_block(spec)]
    if arm == "A":
        blocks.append(f"完整的伏笔设定（你是唯一作者，统管埋设与回收）：\n{ledger.full_text()}")
        blocks.append(f"任务：请写第{chapter}章。")
    elif arm == "B":
        blocks.append(f"完整的伏笔设定（供你参考）：\n{ledger.full_text()}")
        blocks.append(f"本章指令（来自大纲调度）：\n{ledger.directive_for(chapter)}")
        blocks.append(f"任务：请写第{chapter}章。")
    elif arm == "C":
        blocks.append(f"本章指令（来自大纲调度）：\n{ledger.directive_for(chapter)}")
        blocks.append(f"任务：请写第{chapter}章。")
    else:
        raise ValueError(f"unknown arm: {arm}")
    blocks.append(_history_block(chapters))
    return [
        {"role": "system", "content": WRITER_SYSTEM},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def build_reader_messages(title: str, chapters: list[str]):
    parts = [f"【第{i}章】\n{text}" for i, text in enumerate(chapters, start=1)]
    user = (
        f"以下是《{title}》已发表的第1~{len(chapters)}章：\n\n" + "\n\n".join(parts)
        + "\n\n请严格用如下 JSON 回复（不要输出任何其他内容）：\n"
        "{\n"
        '  "guesses": [{"content": "你猜测的真相或走向", "confidence": 1到10的整数, "evidence": "支撑这个猜测的原文引用"}],\n'
        '  "desire_next": 1到10的整数（想读下一章的欲望）,\n'
        '  "notes": "一句话总评"\n'
        "}"
    )
    return [
        {"role": "system", "content": READER_SYSTEM},
        {"role": "user", "content": user},
    ]


def parse_reader_json(raw: str) -> dict:
    """宽容解析：截取首个 { 到末个 } 之间的内容。"""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"parse_error": True, "raw": raw}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"parse_error": True, "raw": raw}
