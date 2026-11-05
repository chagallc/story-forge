"""HOT/WARM/COLD 上下文投影（M2 P4）。

设计：docs/plans/M2-workorder.md P4 / 蓝图「逐章逐消费者生成投影」。
- HOT（writer 必注入）：本章章节卡（含 engine 细胞指令，经 build_engine_directive 复用，
  engine.py 零改动）、出场人物动机栈+声口卡（mes_example 取 1 条）+动态状态、
  Ledger.directive_for(chapter)、前一章 canon 末 300 字、人物 id↔name 对照
- WARM（writer 注入摘要）：最近 2 章 canon 摘要（各 200 字，确定性截取，零 token）、
  未闭合 hook 列表、弧锚点、相关人物关系
- COLD（默认不注入）：完整 bible、全部旧正文、shadow、未到期 reveal_plan——只返回清单，
  仅供显式检索授权；本模块不提供任何把 COLD 拼进 writer 上下文的路径

硬约束：shadows 永不进任何投影；reader 只读 canon；Ledger.full_text() 仅供臂 A/B
实验与作者规划（本模块只用 directive_for）。

build_context(bible, state, spec, chapter, config) -> {"hot": [块], "warm": [块], "cold": [块]}
config: {"id_name_map": {id: name}, "canon_texts": {ch: text}, "card": card|None,
         "prev_source": {ch: "canon"|"draft(迁移回退)"|None}}
"""
from .engine import build_engine_directive, MOTIVE_FIELD_NOTE
from .ledger import Ledger


class SafeLedger(Ledger):
    """空暗账兜底（M1 起的 workbench 侧 shim，M2 收编到 context.py）。

    Ledger.directive_for 对空 entries 会 max() 空序列崩溃；Ledger 类不许动，
    这里仅在 entries 为空时返回无指令行，非空行为与 Ledger 完全一致。
    """

    def directive_for(self, chapter: int) -> str:
        if not self.entries:
            return "- 本章无特殊指令，按大纲推进。"
        return super().directive_for(chapter)


def _tail(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return "…" + text[-n:]


def _summary(text: str, n: int) -> str:
    """确定性摘要（零 token）：首半 + 省略 + 尾半。"""
    text = (text or "").strip()
    if len(text) <= n:
        return text
    half = n // 2
    return text[:half] + "……" + text[-half:]


def _lang(spec_or_bible) -> str:
    if "book" in spec_or_bible:
        return (spec_or_bible.get("book") or {}).get("language", "zh")
    return spec_or_bible.get("language", "zh")


def _char_block(bible, state, cid, id_name_map, lang) -> str:
    """出场人物块：动机栈（作者全知层，全量可见）+ 声口卡 + 动态状态。"""
    meta = next((c for c in bible.get("characters", []) if c.get("id") == cid), None)
    if meta is None:  # 兼容仍以 name 引用的旧数据
        meta = next((c for c in bible.get("characters", []) if c.get("name") == cid), None)
    if meta is None:
        return f"【{cid}】（不在 bible.characters，跳过）"
    name = meta.get("name", cid)
    lines = [f"【{cid}（{name}）】{meta.get('card', '')}"]
    for k in ("want", "need", "wound", "value", "fear", "contradiction"):
        if meta.get(k):
            note = MOTIVE_FIELD_NOTE.get(lang, {}).get(k, k)
            lines.append(f"  {k}：{meta[k]}（{note}）" if lang == "zh" else f"  {k}: {meta[k]} ({note})")
    if meta.get("anchors"):
        lines.append(f"  人格锚点（不可变）：{'；'.join(meta['anchors'])}")
    voice = meta.get("voice") or {}
    if voice.get("catchphrases"):
        lines.append(f"  口头禅：{'、'.join(voice['catchphrases'])}")
    if voice.get("speech_habits"):
        lines.append(f"  说话习惯：{'、'.join(voice['speech_habits'])}")
    if voice.get("forbidden"):
        lines.append(f"  禁说：{'、'.join(voice['forbidden'])}")
    if voice.get("sample_line"):
        lines.append(f"  代表台词：{voice['sample_line']}")
    mes = voice.get("mes_example") or []
    if mes:
        lines.append(f"  对话样本（取1条）：{mes[0]}")
    kr = meta.get("knowledge_rules") or {}
    if kr.get("never_learn"):
        lines.append(f"  知识边界（never_learn，绝不可让其获知）：{'、'.join(kr['never_learn'])}")
    st = (state.data.get("characters") or {}).get(cid) or {}
    dyn = []
    if st.get("location"):
        dyn.append(f"位置={st['location']}")
    if st.get("inventory"):
        dyn.append(f"物品={', '.join(st['inventory'])}")
    knows = (st.get("knowledge") or {}).get("knows") or []
    if knows:
        dyn.append(f"已知事实={', '.join(map(str, knows))}")
    fb = (st.get("knowledge") or {}).get("false_beliefs") or []
    if fb:
        dyn.append(f"错误信念={'; '.join(fb)}")
    if dyn:
        lines.append("  动态状态：" + "｜".join(dyn))
    return "\n".join(lines)


def build_context(bible, state, spec, chapter: int, config: dict) -> dict:
    lang = _lang(spec)
    id_name_map = config.get("id_name_map") or {}
    canon_texts = config.get("canon_texts") or {}
    card = config.get("card")

    # ---------- HOT ----------
    hot = []
    if card:
        eng = card.get("engine") or {}
        choice = card.get("choice") or {}
        lines = ["本章章节卡（作者合约，须严格兑现）：",
                 f"目标：{card.get('objective', '')}｜阻力：{card.get('obstacle', '')}",
                 f"关键选择：{choice.get('selected', '')}（不可逆={choice.get('irreversible')}，"
                 f"代价：{choice.get('cost', '')}）",
                 f"读者承诺：{card.get('reader_promise', '')}",
                 f"结尾状态：{card.get('ending_state', '')}",
                 f"对话密度下限：{(card.get('dialogue_budget') or {}).get('min_ratio', 0.4)}",
                 f"允许事实：{card.get('allowed_fact_ids', [])}｜禁止展开：{card.get('prohibited_developments', [])}"]
        hot.append("\n".join(lines))
        directive = build_engine_directive(spec, chapter)
        if directive:
            hot.append(f"本章引擎指令（叙事引擎下发）：\n{directive}")
        db = (card.get("dialogue_budget") or {}).get("min_ratio")
        if db:
            note = (f"对话密度硬指标：本章对白占比不低于 {int(db * 100)}%。"
                    if lang == "zh" else f"Hard floor: dialogue must be at least {int(db * 100)}% of this chapter.")
            hot.append(note)
    ids_in_card = []
    if card:
        pov = (card.get("pov") or {}).get("character")
        if pov:
            ids_in_card.append(pov)
        for p in (card.get("engine") or {}).get("pressure") or []:
            if p.get("char"):
                ids_in_card.append(p["char"])
    seen = []
    for cid in ids_in_card:
        if cid not in seen:
            seen.append(cid)
    if seen:
        hot.append("出场人物（动机栈+声口+动态状态）：\n" + "\n\n".join(
            _char_block(bible, state, cid, id_name_map, lang) for cid in seen))
        hot.append("人物 id 对照：" + "，".join(f"{cid}={id_name_map.get(cid, cid)}" for cid in seen))
    hot.append(f"伏笔调度：\n{SafeLedger(spec).directive_for(chapter)}")
    prev_text = canon_texts.get(chapter - 1)
    if prev_text:
        src = (config.get("prev_source") or {}).get(chapter - 1)
        tag = "" if src in (None, "canon") else f"（来源：{src}，迁移期回退）"
        hot.append(f"前一章 canon 结尾（末300字）{tag}：\n{_tail(prev_text, 300)}")

    # ---------- WARM ----------
    warm = []
    for p in (chapter - 2, chapter - 1):
        t = canon_texts.get(p)
        if p >= 1 and t:
            warm.append(f"第{p}章 canon 摘要（200字）：{_summary(t, 200)}")
    open_hooks = []
    for e in spec.get("ledger", []):
        if e.get("reveal_chapter", 0) >= chapter:
            open_hooks.append(f"[{e['id']}] 第{e['plant_chapter']}章埋设、第{e['reveal_chapter']}章回收：{e.get('hook', '')}")
    hooks_state = state.data.get("hooks") or {}
    for hid, h in hooks_state.items():
        if h.get("status") != "payoff":
            open_hooks.append(f"[{hid}] 当前状态 {h.get('status')}（第{h.get('chapter')}章）")
    if open_hooks:
        warm.append("未闭合钩子：\n" + "\n".join(f"- {x}" for x in open_hooks))
    anchors = (bible.get("arc") or {}).get("anchors") or []
    if anchors:
        warm.append("弧线锚点：" + "；".join(map(str, anchors)))
    rel_lines = []
    for cid in seen:
        st = (state.data.get("characters") or {}).get(cid) or {}
        for other, r in (st.get("relationships") or {}).items():
            rel_lines.append(f"{id_name_map.get(cid, cid)} → {id_name_map.get(other, other)}："
                             f"{r.get('type', '')}（第{r.get('chapter')}章）")
    if rel_lines:
        warm.append("相关人物关系：\n" + "\n".join(f"- {x}" for x in rel_lines))

    # ---------- COLD（只给清单，绝不给内容；默认不注入） ----------
    cold = ["COLD 层（默认不注入，仅供显式检索授权）：",
            f"- 完整 bible（story-bible.json，revision {bible.get('revision', 0)}）",
            f"- shadow 条目 {len(bible.get('shadows') or [])} 条（永不进 writer 投影）",
            "- 未到期 reveal_plan " + str(sum(1 for e in spec.get('ledger', [])
                                              if e.get('reveal_chapter', 0) > chapter)) + " 条（随 directive_for 到期放行）",
            f"- 全部旧 canon（本函数只携带第 1~{chapter - 1} 章的 HOT/WARM 摘要）"]
    return {"hot": hot, "warm": warm, "cold": cold}
