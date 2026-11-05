"""章节卡 card.json 校验（工单 M1 P1）。

validate_card(card, bible, expected_chapter=None) -> list[str]
返回违规清单，空列表 = 通过。校验项（工单规定）：
- 必填字段（章节卡 17 项 + engine 细胞字段族）
- char 必须在 bible.characters（pov.character 与 pressure[].char）
- engine.amplitude / engine.end_hook / pressure[].motive 枚举
- pressure[].force 与 plan/disruption 同源：关键词重叠启发式
  （zh 取 CJK 二字组 + 英数词，en 取去停用词词元，要求与 plan∪disruption 有交集）
- chapter 必须是 int（可选 expected_chapter 比对）

语言相关枚举按 bible.book.language 切换：zh 用中文枚举，en 用英文枚举
（end_hook: new-information|dilemma|about-to-act|quiet-close）。
"""
import re

AMPLITUDES = ("XL", "L", "M", "S", "B")
MOTIVES = ("want", "need", "wound", "value", "fear", "contradiction")
END_HOOKS_ZH = ("新信息型", "两难型", "即将行动型", "轻收束")
END_HOOKS_EN = ("new-information", "dilemma", "about-to-act", "quiet-close")
PROMISE_TYPES_ZH = ("信息", "情绪", "事件", "画面")
PROMISE_TYPES_EN = ("info", "emotion", "event", "visual")
TENSES = ("past", "present")

REQUIRED_TOP = (
    "chapter_type", "pov", "time_place", "opening_state", "objective", "obstacle",
    "choice", "intended_consequence", "recorded_consequence", "reader_promise",
    "ending_state", "allowed_fact_ids", "prohibited_developments",
    "active_hook_ids", "dialogue_budget", "engine",
)
REQUIRED_STR_TOP = (
    "chapter_type", "time_place", "opening_state", "objective", "obstacle",
    "intended_consequence", "ending_state",
)
REQUIRED_ENGINE_STR = (
    "arc_label", "amplitude", "plan", "disruption", "crisis", "improvisation", "end_hook",
)

_EN_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "but", "with", "for", "at",
    "by", "from", "as", "is", "are", "was", "were", "be", "been", "that", "this", "it",
    "its", "his", "her", "their", "he", "she", "they", "them", "not", "no", "so", "if",
    "then", "than", "when", "while", "after", "before", "into", "out", "up", "down",
    "over", "under", "again", "must", "will", "would", "can", "could", "has", "have",
    "had", "do", "does", "did", "who", "whom", "which", "what", "where", "why", "how",
}


def _zh_ngrams(text: str) -> set:
    """CJK 二字组 + 英数词（长度>=2），用作关键词重叠的词袋。"""
    grams = set()
    for seg in re.findall(r"[一-鿿]+|[A-Za-z0-9]+", text or ""):
        if re.fullmatch(r"[A-Za-z0-9]+", seg):
            if len(seg) >= 2:
                grams.add(seg.lower())
        else:
            grams.update(seg[i:i + 2] for i in range(len(seg) - 1))
    return grams


def _en_tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z'-]{2,}", (text or "").lower())
            if w not in _EN_STOP}


def _same_source(force: str, plan: str, disruption: str, lang: str) -> bool:
    """同源启发式：force 与 plan/disruption 至少共享一个关键词。"""
    if lang == "en":
        return bool(_en_tokens(force) & (_en_tokens(plan) | _en_tokens(disruption)))
    return bool(_zh_ngrams(force) & (_zh_ngrams(plan) | _zh_ngrams(disruption)))


def _nonempty_str(val) -> bool:
    return isinstance(val, str) and bool(val.strip())


def char_refs(bible) -> set:
    """人物合法引用集合：id 为主（M2 P3），name 作显示名兼容接受。"""
    refs = set()
    for c in bible.get("characters", []):
        if isinstance(c, dict):
            if c.get("id"):
                refs.add(c["id"])
            if c.get("name"):
                refs.add(c["name"])
    return refs


def validate_card(card, bible, expected_chapter=None) -> list:
    """校验章节卡，返回违规信息清单（zh 面向作者，空列表 = 通过）。

    M2 P3：pov.character / pressure[].char 以人物 id 为准（name 兼容接受，
    迁移与 lock 产出都会归一到 id）。
    """
    if not isinstance(card, dict):
        return ["card 必须是 JSON 对象"]
    v = []
    lang = (bible.get("book") or {}).get("language", "zh")
    refs = char_refs(bible)

    # ---- chapter：int（工单硬性要求）----
    ch = card.get("chapter")
    if isinstance(ch, bool) or not isinstance(ch, int):
        v.append(f"chapter 必须是 int（实际为 {ch!r}）")
    elif expected_chapter is not None and ch != expected_chapter:
        v.append(f"chapter={ch} 与目标章节 {expected_chapter} 不符")

    # ---- base_state_revision：int（M2 commit 校验的基线，M1 起即锁定类型）----
    bsr = card.get("base_state_revision")
    if isinstance(bsr, bool) or not isinstance(bsr, int):
        v.append(f"base_state_revision 必须是 int（实际为 {bsr!r}）")

    # ---- 必填字段 ----
    for k in REQUIRED_TOP:
        if k not in card:
            v.append(f"缺少必填字段：{k}")
    for k in REQUIRED_STR_TOP:
        if k in card and not _nonempty_str(card.get(k)):
            v.append(f"字段 {k} 必须是非空字符串")

    # ---- pov ----
    if "pov" in card:
        pov = card.get("pov")
        if not isinstance(pov, dict):
            v.append("pov 必须是对象 {character, tense}")
        else:
            if not _nonempty_str(pov.get("character")):
                v.append("pov.character 必须是非空字符串（人物 id）")
            elif pov.get("character") not in refs:
                v.append(f"pov.character {pov.get('character')!r} 不在 bible.characters（id 或 name）")
            if pov.get("tense") not in TENSES:
                v.append(f"pov.tense {pov.get('tense')!r} 不在枚举 {list(TENSES)}")

    # ---- choice ----
    if "choice" in card:
        choice = card.get("choice")
        if not isinstance(choice, dict):
            v.append("choice 必须是对象 {selected, irreversible, cost}")
        else:
            for k in ("selected", "cost"):
                if not _nonempty_str(choice.get(k)):
                    v.append(f"choice.{k} 必须是非空字符串")
            if not isinstance(choice.get("irreversible"), bool):
                v.append("choice.irreversible 必须是 bool")

    # ---- reader_promise ----
    if "reader_promise" in card:
        rp = card.get("reader_promise")
        if not isinstance(rp, dict):
            v.append("reader_promise 必须是对象 {type, content}")
        else:
            if not _nonempty_str(rp.get("content")):
                v.append("reader_promise.content 必须是非空字符串")
            allowed = PROMISE_TYPES_ZH + (PROMISE_TYPES_EN if lang == "en" else ())
            if rp.get("type") not in allowed:
                v.append(f"reader_promise.type {rp.get('type')!r} 不在枚举 {list(allowed)}")

    # ---- dialogue_budget ----
    if "dialogue_budget" in card:
        db = card.get("dialogue_budget")
        ratio = db.get("min_ratio") if isinstance(db, dict) else None
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            v.append("dialogue_budget.min_ratio 必须是数字")
        elif not 0 <= ratio <= 1:
            v.append(f"dialogue_budget.min_ratio={ratio} 必须在 0~1 之间")

    # ---- 列表字段 ----
    for k in ("allowed_fact_ids", "prohibited_developments", "active_hook_ids"):
        if k in card:
            val = card.get(k)
            if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
                v.append(f"{k} 必须是字符串数组")

    # ---- recorded_consequence：null 或字符串（M1 恒为 null，写完回填） ----
    if "recorded_consequence" in card:
        rc = card.get("recorded_consequence")
        if rc is not None and not _nonempty_str(rc):
            v.append("recorded_consequence 必须是 null 或非空字符串")

    # ---- engine（细胞字段族，原样透传给 spec.engine.cells）----
    if "engine" in card:
        eng = card.get("engine")
        if not isinstance(eng, dict):
            v.append("engine 必须是对象（细胞字段族）")
        else:
            for k in REQUIRED_ENGINE_STR:
                if not _nonempty_str(eng.get(k)):
                    v.append(f"engine.{k} 必须是非空字符串")
            if "amplitude" in eng and eng.get("amplitude") not in AMPLITUDES:
                v.append(f"engine.amplitude {eng.get('amplitude')!r} 不在枚举 {list(AMPLITUDES)}")
            hooks = END_HOOKS_EN if lang == "en" else END_HOOKS_ZH
            if "end_hook" in eng and eng.get("end_hook") not in hooks:
                v.append(f"engine.end_hook {eng.get('end_hook')!r} 不在枚举 {list(hooks)}")
            if "pressure" not in eng:
                v.append("缺少必填字段：engine.pressure")
            else:
                pressures = eng.get("pressure")
                if not isinstance(pressures, list) or not pressures:
                    v.append("engine.pressure 必须是非空数组")
                else:
                    for i, p in enumerate(pressures):
                        if not isinstance(p, dict):
                            v.append(f"pressure[{i}] 必须是对象 {{char, motive, force, cost}}")
                            continue
                        if p.get("char") not in refs:
                            v.append(f"pressure[{i}].char {p.get('char')!r} 不在 bible.characters（id 或 name）")
                        if p.get("motive") not in MOTIVES:
                            v.append(f"pressure[{i}].motive {p.get('motive')!r} 不在枚举 {list(MOTIVES)}")
                        for k in ("force", "cost"):
                            if not _nonempty_str(p.get(k)):
                                v.append(f"pressure[{i}].{k} 必须是非空字符串")
                        if (_nonempty_str(p.get("force")) and _nonempty_str(eng.get("plan"))
                                and _nonempty_str(eng.get("disruption"))
                                and not _same_source(p["force"], eng["plan"], eng["disruption"], lang)):
                            v.append(f"pressure[{i}].force 与 plan/disruption 缺少关键词重叠（须同源）")
    return v
