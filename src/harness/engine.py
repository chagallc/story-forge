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
    return "\n".join(line for line in lines if line)
