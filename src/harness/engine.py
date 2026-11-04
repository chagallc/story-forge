"""故事引擎层：弧线 → 包络 → 细胞。

负责把 spec["engine"] 里的结构化数据拼成写作指令。
设计文档见 docs/story-engine-spec.md。
"""

AMPLITUDE_NOTE = {
    "XL": "本章是全书级大转折（计划摧毁），笔墨给足，冲击优先。",
    "L": "本章是大转折，节奏沉重。",
    "M": "本章是中强度转折：计划被迫修正，但不摧毁。",
    "S": "本章低强度：信息啃咬与小钩子，篇幅可短。",
    "B": "本章是呼吸拍（sequel）：反应-困境-新决定。禁止新灾难、禁止新钩子，写情绪、关系与质感，章末轻收束。",
}

HOOK_NOTE = {
    "新信息型": "章末收在一个刚刚浮现、改变一切的发现上。",
    "两难型": "章末收在两个都不想要的选项之间，不解决。",
    "即将行动型": "章末收在下一个动作扣动扳机的瞬间。",
    "轻收束": "章末安静落地，允许闭合，不吊钩。",
}

MOTIVE_FIELD_NOTE = {
    "want": "表层欲望（他自己知道且承认）",
    "need": "深层需求（他自己没有意识到，主题层）",
    "wound": "旧伤（解释他为什么这样行事）",
    "value": "底线（可以让他翻脸或越线的东西）",
    "fear": "恐惧（压力测试点）",
    "contradiction": "内在矛盾（欲望与需求/底线的冲突形式）",
}

MOTIVE_CHAIN_RULE = (
    "动机链四问（每个重要行动必须无声地全部成立，以场景、选择与代价呈现，禁止旁白解释）：\n"
    "1. 她此刻想要什么；\n"
    "2. 什么拦住了她；\n"
    "3. 为什么是现在（时机压力）；\n"
    "4. 为什么是她（换一个人不会这么做）。\n"
    "行动必须付出可见代价：花钱、冒险、留把柄，至少其一。"
)


def motive_stack_block(spec: dict) -> str:
    """全员动机栈总表（作者全知层，随人物卡注入写作上下文）。"""
    chars = spec.get("characters", [])
    if not chars or "want" not in chars[0]:
        return ""
    lines = ["人物动机栈（写作时人物行动的总依据）："]
    for c in chars:
        lines.append(f"【{c['name']}】{c.get('card', '')}")
        for k in ("want", "need", "wound", "value", "fear", "contradiction", "voice"):
            if c.get(k):
                lines.append(f"  {k}：{c[k]}（{MOTIVE_FIELD_NOTE.get(k, k)}）")
    return "\n".join(lines)


def pressure_block(spec: dict, chapter: int) -> str:
    """本章动机压力指令：谁的第几个动机被什么力压制，代价是什么。"""
    cell = cell_for(spec, chapter) or {}
    pressures = cell.get("pressure", [])
    if not pressures:
        return ""
    lines = ["本章动机压力（与本章计划/颠覆同源，写人物行动时必须兑现）："]
    for p in pressures:
        lines.append(
            f"- {p['char']} 的[{MOTIVE_FIELD_NOTE.get(p.get('motive', ''), p.get('motive', ''))}]"
            f"受压：{p['force']}；行动代价：{p['cost']}"
        )
    if cell.get("amplitude") == "B":
        lines.append(
            "本章是呼吸拍：写出受压角色的反应-困境-决定三步，决定必须体现他对动机排序的重新排列（这是本章真正的产出）。"
        )
    return "\n".join(lines)


def cell_for(spec: dict, chapter: int) -> dict | None:
    cells = spec.get("engine", {}).get("cells", [])
    for c in cells:
        if c["chapter"] == chapter:
            return c
    return None


def arc_summary(spec: dict) -> str:
    eng = spec.get("engine", {})
    arc = eng.get("arc", [])
    return "；".join(f"{a['name']}@第{a['chapter']}章" for a in arc)


def build_engine_directive(spec: dict, chapter: int) -> str:
    """组装本章引擎指令（弧线位置 + 振幅约束 + 四元组 + 断章钩子）。"""
    cell = cell_for(spec, chapter)
    if cell is None:
        return "- 本章无引擎指令，按大纲推进。"
    lines = [
        f"弧线位置：{cell['arc_label']}（振幅 {cell['amplitude']}）",
        AMPLITUDE_NOTE.get(cell["amplitude"], ""),
        f"主角本章的计划：{cell['plan']}",
        f"颠覆（新信息推翻计划）：{cell['disruption']}",
        f"危机（失败的代价具象化）：{cell['crisis']}",
        f"临场应变（用新信息重构计划）：{cell['improvisation']}",
        f"断章钩子：{HOOK_NOTE.get(cell['end_hook'], cell['end_hook'])}（{cell['end_hook']}）",
        "写法要求：让读者先看见计划，再让它被推翻。回收的真相以『计划崩塌』的方式到达，禁止以旁白公布答案。",
    ]
    pressure = pressure_block(spec, chapter)
    if pressure:
        lines.append(pressure)
    lines.append(MOTIVE_CHAIN_RULE)
    return "\n".join(line for line in lines if line)
