"""三个角色的 prompt 组装：writer（三臂三种可见性）、reader（只读正文的模拟读者）。"""
import json
import re

from .engine import arc_summary, build_engine_directive, motive_stack_block

WRITER_SYSTEM = {
    "zh": (
        "你是一位中文小说家。要求：每章约1000字；以场景、动作、对白推进故事，"
        "靠细节与潜台词制造悬念；禁止上帝视角解释人物动机，人物动机只能通过选择、行动与代价呈现；"
        "每个人物的重要行动必须满足动机链四问（想要什么/什么拦住/为什么是现在/为什么是她），"
        "行动必须付出可见代价；禁止总结式收尾；"
        "严格遵循给定的大纲与指令。输出纯正文，不要标题、不要注释。"
        "\n\n文风守门：\n"
        "1. 禁用「不是A，而是B」式对仗句；\n"
        "2. 禁用模板腔：值得注意的是/从某种意义上说/仿佛在诉说/空气仿佛凝固/不知过了多久/眼神里闪过一丝/嘴角勾起一抹；\n"
        "3. 允许自然重复用词，刻意避免重复反而不像人写的；\n"
        "4. 句长要有波动，短句与长句混着来；\n"
        "5. 少用破折号与冒号总结腔；段落不要都碎成两三行。"
    ),
    "en": (
        "You are an English-language novelist writing serialized web fiction. Requirements: each chapter "
        "about 1,100 words; advance the story through scene, action and dialogue; build tension through "
        "detail and subtext; never explain a character's motives from a god's-eye view — motives may only "
        "surface through choices, actions and visible costs; every significant action must satisfy the "
        "motive chain (what does she want / what blocks her / why now / why her); no summarizing endings; "
        "follow the given outline and directives strictly. Output prose only: no headings, no notes.\n\n"
        "Style guard:\n"
        "1. Ban \"not just X, but Y\" / \"it wasn't X; it was Y\" constructions;\n"
        "2. Ban slop vocabulary: delve, tapestry, testament to, embark, navigate (metaphorical), shimmer, "
        "dance/symphony/whisper (metaphorical), myriad, intricate, palpable, ethereal, breathtaking;\n"
        "3. Ban stock beats: \"let out a breath she didn't know she was holding\", \"little did they know\", "
        "\"something shifted\", \"the air was thick with\", \"eyes gleamed with + abstract noun\";\n"
        "4. Vary sentence length aggressively; fragments are fine in action; allow natural word repetition;\n"
        "5. Em-dashes at most one per chapter; no tricolon closers; paragraphs need not be uniform."
    ),
}

READER_SYSTEM = {
    "zh": (
        "你是一位普通小说读者，从未看过本书的任何设定资料，只读已发表的正文章节。"
        "请诚实给出你的阅读反应，不装聪明也不装笨。"
        "特别地：对每个人物的行动判断“这个人会不会这么做”，对不可信的行动直说原因。"
    ),
    "en": (
        "You are an ordinary web-fiction reader who has never seen any of this book's setting materials; "
        "you only read the published chapters. Give your honest reading reactions; neither play smart nor "
        "play dumb. In particular: for each character's action, judge whether this person would really do "
        "this, and say plainly why for any action you find unconvincing."
    ),
}


def _story_block(spec: dict) -> str:
    chars = "\n".join(f"- {c['name']}：{c['card']}" for c in spec["characters"])
    beats = "\n".join(spec["beats"])
    return (
        f"《{spec['title']}》\n\n前提：{spec['premise']}\n\n"
        f"人物：\n{chars}\n\n全书大纲：\n{beats}"
    )


def _story_block_engine(spec: dict) -> str:
    """引擎模式：不给出逐章节拍，只给前提、人物（含动机栈）与弧线锄点。"""
    chars = "\n".join(f"- {c['name']}：{c['card']}" for c in spec["characters"])
    motive = motive_stack_block(spec)
    return (
        f"《{spec['title']}》\n\n前提：{spec['premise']}\n\n"
        f"人物：\n{chars}\n\n"
        + (f"{motive}\n\n" if motive else "")
        + f"全书弧线（仅锄点，不给逐章内容）：{arc_summary(spec)}"
    )


def _history_block(chapters: list[str]) -> str:
    if not chapters:
        return "（这是第一章，暂无前文）"
    parts = [f"【第{i}章】\n{text}" for i, text in enumerate(chapters, start=1)]
    return "已完成的章节：\n\n" + "\n\n".join(parts)


def build_writer_messages(arm: str, spec: dict, ledger, chapters: list[str], chapter: int):
    """按臂组装写作上下文。arm: A=单体全知 / B=分工无墙 / C=分工有墙 / E=引擎模式（B 可见性）。"""
    lang = spec.get("language", "zh")
    system = WRITER_SYSTEM[lang]
    if arm == "E":
        blocks = [_story_block_engine(spec)]
        blocks.append(f"完整的伏笔设定（供你参考）：\n{ledger.full_text()}")
        blocks.append(f"本章引擎指令（叙事引擎下发）：\n{build_engine_directive(spec, chapter)}")
        blocks.append(f"伏笔调度：\n{ledger.directive_for(chapter)}")
        blocks.append(f"任务：请写第{chapter}章。")
        blocks.append(_history_block(chapters))
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(blocks)},
        ]
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
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def build_reader_messages(title: str, chapters: list[str], lang: str = "zh"):
    parts = [f"【第{i}章】\n{text}" if lang == "zh" else f"[Chapter {i}]\n{text}"
             for i, text in enumerate(chapters, start=1)]
    if lang == "en":
        user = (
            f"Below are chapters 1~{len(chapters)} of \"{title}\" as published:\n\n" + "\n\n".join(parts)
            + "\n\nReply strictly with the following JSON (nothing else):\n"
            "{\n"
            '  "guesses": [{"content": "your guess at the truth or direction", "confidence": integer 1-10, "evidence": "quote from the text"}],\n'
            '  "desire_next": integer 1-10 (desire to read the next chapter),\n'
            '  "motive_check": [{"char": "name", "action": "one significant action by that character", "believable": integer 1-10 (would this person do this?), "why": "one sentence"}],\n'
            '  "notes": "one-sentence overall impression"\n'
            "}"
        )
    else:
        user = (
            f"以下是《{title}》已发表的第1~{len(chapters)}章：\n\n" + "\n\n".join(parts)
            + "\n\n请严格用如下 JSON 回复（不要输出任何其他内容）：\n"
            "{\n"
            '  "guesses": [{"content": "你猜测的真相或走向", "confidence": 1到10的整数, "evidence": "支撑这个猜测的原文引用"}],\n'
            '  "desire_next": 1到10的整数（想读下一章的欲望）,\n'
            '  "motive_check": [{"char": "人物名", "action": "该人物本章一个重要行动", "believable": 1到10的整数（这个人会不会这么做）, "why": "一句话理由"}],\n'
            '  "notes": "一句话总评"\n'
            "}"
        )
    return [
        {"role": "system", "content": READER_SYSTEM[lang]},
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
