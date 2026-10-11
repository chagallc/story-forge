"""暗账：hook（可见）与 reveal_plan（秘密）的物理拆分与投影。

防火墙的核心数据结构。规则：
- hook：效果级指令，到埋设章对写作 agent 可见
- reveal_plan + canary：只在回收章随指令放行，此前任何臂 C 路径都拿不到
- 臂 A/B 可见完整暗账（对照组）
"""


class Ledger:
    def __init__(self, spec: dict):
        self.entries = spec["ledger"]

    def full_text(self) -> str:
        """臂 A/B 用：完整暗账（含底牌与金丝雀词）。"""
        blocks = []
        for e in self.entries:
            blocks.append(
                f"[{e['id']}] 第{e['plant_chapter']}章埋设，第{e['reveal_chapter']}章回收\n"
                f"钩子：{e['hook']}\n"
                f"底牌（回收章前绝不可泄露）：{e['reveal_plan']}"
            )
        return "\n\n".join(blocks)

    def directive_for(self, chapter: int) -> str:
        """臂 B/C 共用的本章确定性指令：只含效果指令与到期底牌，无未来信息。"""
        lines = []
        for e in self.entries:
            if e["plant_chapter"] == chapter:
                lines.append(f"- 本章钩子：{e['hook']}")
            if e["reveal_chapter"] == chapter:
                lines.append(f"- 本章回收：{e['reveal_plan']}")
        if chapter < max(e["reveal_chapter"] for e in self.entries):
            lines.append("- 纪律：本章不得解释任何旧物、药品、门锁细节的来历或原理，它们只是存在。")
        if not lines:
            return "- 本章无特殊指令，按大纲推进。"
        return "\n".join(lines)
