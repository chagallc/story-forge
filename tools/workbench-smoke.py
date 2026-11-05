#!/usr/bin/env python3
"""工作台冒烟测试 v3（M2：正史提交/角色认知/上下文投影/豁免状态，工单验收 #1~#4）。

主流程（BOOK=smoke-wb，清空重建，真实 LLM，投影关=M1 行为）：
  new(schema v3) → char(v3 四分区 JSON seed) → discuss(选分支) → lock(章节卡 id 化) →
  write(draft+delta+lint 三件套，前文只读 canon) → commit(canon+state 原子推进+备份) →
  再 commit（负样本：revision 不匹配必须拒绝）

离线段（FakeClient 假客户端，零 LLM）：
  - 写 ch2 上下文断言：投影开=HOT/WARM（无 COLD、无 shadows、无 ch1 drafts 内容）
  - 投影关=M1 E 臂形态（全文历史+完整暗账），前文同样是 canon 优先
  - delta 预清洗：name→id 改写 / 非白名单 op 丢弃 / evidence 非子串丢弃
  - commit ch2：state.revision 推进、characters.knowledge 确定性推进（验收 #5）
  - 豁免生命周期：exempt → lint 过滤 → 正文改动后豁免失效
  - state.py 4 组负样本（revision 不匹配/非白名单/非子串/never_learn 冲突）

迁移段：
  - smoke-wb-m1copy（M1 格式真实副本）：status 迁移 v2→v3（id 生成/card.json 改写/written→drafted）
    → write 续写（draft 跨迁移版本递增）→ commit 建正史
  - smoke-wb-legacy（v1 cell 格式）：status 迁移 → write 直通 → commit（无卡跳过回填）

依赖：experiments/exp003 + config/models.local.json；真实 LLM 约 6 次调用（讨论1+卡1+主书写作2+副本写作2）。
"""
import json
import os
import shutil
import subprocess
import sys
import io
import contextlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import workbench as wb  # noqa: E402
from src.harness.context import build_context  # noqa: E402
from src.harness.engine import build_engine_directive  # noqa: E402
from src.harness.schema import validate_card  # noqa: E402
from src.harness.state import StoryState, text_sha1  # noqa: E402

BOOK = "smoke-wb"            # 主流程：v3 全流程（真实 LLM）
M1COPY = "smoke-wb-m1copy"   # M1 格式真实副本：迁移续写（真实 LLM）
LEGACY = "smoke-wb-legacy"   # v1 cell 格式：离线直通验证

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
RESULTS = []


def run(args, input=None, timeout=600):
    return subprocess.run([sys.executable, "workbench.py", *args], input=input,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, cwd=ROOT, env=ENV)


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    RESULTS.append(cond)
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail and not cond else ""))
    return cond


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class FakeClient:
    """离线假客户端：按序返回预设回复并记录收到的 messages。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, *, tag="", **kw):
        self.calls.append({"tag": tag, "messages": messages})
        return self.replies.pop(0) if self.replies else "（FakeClient 无更多回复）"


def _short_paras_prose(extra_sentences=()):
    """确定性正文：24 个短段（触发 lint「分节碎」），附可作 evidence 的完整句。"""
    lines = ["「按规矩说，死当不问来路。」", "雨夜。柜上灯昏。", "贺三刀喝茶。茶是好茶。",
             "「这物件不干净。」", "陆小满不接话。", "怀表在柜面上躺着。",
             "「喝茶喝茶，急什么。」", "雨声密了。", "陆小满把怀表贴在耳边，表芯的声音像有人在敲门。",
             "「当票呢？」", "「没有。」", "贺三刀的茶碗停在半空。",
             "灯花爆了一下。", "「死当也是当。」", "陆小满低着头。",
             "「行会的规矩，你不是不知道。」", "「我知道。」", "雨点砸在窗纸上。",
             "贺三刀笑。笑得很慢。", "「三天。三天后来收。」",
             "门关上了。", "陆小满才抬头。", "他决定今晚就把地名查清楚。", "表还停在那一刻。"]
    return "\n".join(list(lines) + [s for s in extra_sentences])


CHARACTERS_V3 = [
    {"id": "char_01", "name": "陆小满", "card": "24岁，九门典当行学徒，眼力毒，嘴更快。",
     "anchors": ["守规矩", "重师徒"],
     "want": "赎回师父留下的怀表，弄清他失踪那晚去了哪",
     "need": "承认师父可能自己有秘密，而非只有受害者叙事",
     "wound": "孤儿，师父是唯一给过他姓氏的人",
     "value": "当铺规矩：死当不问来路——但他今天想破例",
     "fear": "师父是自愿消失的，根本没打算带上他",
     "contradiction": "守规矩的学徒要做一行里最破规矩的事",
     "voice": {"catchphrases": ["按规矩说", "这物件不干净"], "speech_habits": ["短句", "先报价后说话"],
               "forbidden": ["不说完整性解释句"], "sample_line": "按规矩说，死当不问来路。",
               "mes_example": ["「按规矩说，死当不问来路。」陆小满把当票推回去。",
                               "「这物件不干净。」他隔着柜台看那块表。"]},
     "knowledge_rules": {"learn": [{"fact_id": "F1_HOOK", "when": "亲自看见怀表背面刻痕"}],
                         "never_learn": ["F1_REVEAL"]},
     "lorebook": [{"fact_id": "F1_HOOK", "keywords": ["怀表", "刻痕"], "content_ref": "ledger:F1.hook"}]},
    {"id": "char_02", "name": "贺三刀", "card": "55岁，行会老理事，笑面，账算得极清。",
     "anchors": ["行会秩序"],
     "want": "把九门典当行并进行会统一管理",
     "need": "挽回三十年前他亲手做砸的一桩局",
     "wound": "当年他师父也是这样消失的，他选择了闭嘴",
     "value": "行会秩序高于个人恩怨",
     "fear": "陆小满查到当年的局和他有关",
     "contradiction": "最讲规矩的人靠破坏规矩起家",
     "voice": {"catchphrases": ["喝茶喝茶"], "speech_habits": ["绕着说", "从不先出价"],
               "sample_line": "喝茶喝茶，急什么。"},
     "knowledge_rules": {"learn": [], "never_learn": []}},
]

LEDGER_SEED = [{"id": "F1", "plant_chapter": 1, "reveal_chapter": 3,
                "hook": "怀表背面刻着一个不属于师父籍贯的地名，只给特写不解释",
                "reveal_plan": "地名是师父三十年前当学徒的旧铺号，贺三刀当年就在那里", "canary": "泉 lock"},
               {"id": "F1_REVEAL", "plant_chapter": 3, "reveal_chapter": 6,
                "hook": "（底牌登记用）贺三刀与旧铺号的关系",
                "reveal_plan": "贺三刀当年就在旧铺号当学徒", "canary": "旧铺"}]


def seed_v3_book(bible):
    """char(四分区 JSON seed)+ledger+branches seed（工单指定 seed 模式）。"""
    bible["characters"] = json.loads(json.dumps(CHARACTERS_V3))
    bible["ledger"] = json.loads(json.dumps(LEDGER_SEED))
    wb.save_bible(BOOK, bible)


def seed_branches(bible):
    os.makedirs(os.path.join(wb.ws_dir(BOOK), "discussions"), exist_ok=True)
    bf = wb.branches_file(BOOK, 1)
    branches = [
        {"id": "A", "summary": "开场即夜班收表：怀表死当落在柜上，贺三刀同一夜登门喝茶施压",
         "beats": ["夜里收进师父的怀表，背面刻着不属于师父籍贯的地名",
                   "贺三刀登门喝茶，全程场面话施压要把行并走",
                   "陆小满按规矩收下死当，但决定破例暗查地名",
                   "章末发现怀表停在师父失踪那晚的时刻"],
         "choice": "接下死当并背着行会私查怀表地名",
         "motive_cost": "压陆小满的fear（师父可能自愿消失）；代价是私查留下把柄",
         "reader_payoff": "信息：地名刻痕；事件：怀表停摆的时刻",
         "risks": ["开场信息密度偏高"]},
        {"id": "B", "summary": "行会饭局开局：贺三刀当众宣布并行意向，散席后怀表死当才落到柜上",
         "beats": ["行会饭局，贺三刀场面话宣布并行意向", "陆小满替病着的师父挡酒周旋",
                   "散席回铺，深夜有人送来怀表死当", "章末发现送当人的靴子沾着行会的茶渍"],
         "choice": "瞒下行会收下怀表", "motive_cost": "压陆小满的value；代价是违背自己的规矩",
         "reader_payoff": "画面：饭局暗流；信息：茶渍线索", "risks": ["饭局戏节奏偏慢"]},
        {"id": "C", "summary": "怀表先失窃：死当当夜怀表被人截走，陆小满追赃追出地名线索",
         "beats": ["怀表死当当夜被人从柜上截走", "陆小满凭眼力追到当铺街后巷",
                   "截当人丢下怀表逃走，表盖新添一道刻痕", "章末刻痕地名指向三十年前的旧铺号"],
         "choice": "追赃（公然与截当人结怨）", "motive_cost": "压陆小满的want；代价是结怨",
         "reader_payoff": "事件：当街追赃", "risks": ["动作戏偏重，对话密度难保"]},
    ]
    wb._write_json(bf, {"chapter": 1, "branches": branches})
    bible["chapters"]["1"] = {"status": "branching", "branches_path": wb.rel_path(BOOK, bf)}
    wb.save_bible(BOOK, bible)


def seed_ch2_card(bible):
    """离线段素材：给 ch2 造一张合法卡（复制 ch1 卡改章号），走文件权威。"""
    base = load_json(wb.card_file(BOOK, 1))
    card2 = json.loads(json.dumps(base))
    card2["chapter"] = 2
    card2["base_state_revision"] = 0
    os.makedirs(wb.chapter_dir(BOOK, 2), exist_ok=True)
    wb._write_json(wb.card_file(BOOK, 2), card2)
    bible["chapters"]["2"] = {"status": "locked", "card_path": wb.rel_path(BOOK, wb.card_file(BOOK, 2)),
                              "card": card2}
    wb.save_bible(BOOK, bible)
    return card2


def seed_m1_copy():
    """按 M1 提交态构造 M1 格式工作区（schema v2、人物无 id、ch1 written + name 卡 + v001 草稿）。

    程序化构造而非复制 smoke-wb：保证 smoke 可重复跑（不依赖仓库里的工作区状态）。
    """
    d = wb.ws_dir(M1COPY)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "chapters", "ch01", "drafts"), exist_ok=True)
    os.makedirs(os.path.join(d, "discussions"), exist_ok=True)
    card_m1 = {
        "chapter": 1, "chapter_type": "A", "base_state_revision": 4,
        "pov": {"character": "陆小满", "tense": "past"},
        "time_place": "当夜，九门典当行", "opening_state": "怀表落在柜上",
        "objective": "查清地名来历", "obstacle": "行会并局施压",
        "choice": {"selected": "私查地名", "irreversible": True, "cost": "留下把柄"},
        "intended_consequence": "拿到第一条线索", "recorded_consequence": None,
        "reader_promise": {"type": "信息", "content": "地名指向旧铺号"},
        "ending_state": "怀表停在失踪那晚的时刻",
        "allowed_fact_ids": ["F1"], "prohibited_developments": ["不揭示地名含义"],
        "active_hook_ids": ["F1"], "dialogue_budget": {"min_ratio": 0.4},
        "engine": {"arc_label": "开局：扰动落地", "amplitude": "L",
                   "plan": "陆小满按规矩收下死当怀表，凑钱赎表",
                   "disruption": "贺三刀夜访施压并行，怀表背面刻着不属于师父的地名",
                   "crisis": "收下死当就得罪行会，不接就丢了查师父的唯一线索",
                   "improvisation": "表面答应并行条款，私下记下地名准备暗查",
                   "pressure": [{"char": "陆小满", "motive": "fear",
                                 "force": "怀表停在师父失踪那晚，怕师父自愿消失", "cost": "私查留把柄"},
                                {"char": "贺三刀", "motive": "contradiction",
                                 "force": "用规矩话术破坏规矩推行并局", "cost": "深夜登门留下把柄"}],
                   "end_hook": "新信息型"},
    }
    chars_m1 = []
    for c in json.loads(json.dumps(CHARACTERS_V3)):
        c.pop("id", None)
        c.pop("anchors", None)
        c.pop("knowledge_rules", None)
        c.pop("lorebook", None)
        if isinstance(c.get("voice"), dict):
            c["voice"].pop("forbidden", None)
            c["voice"].pop("mes_example", None)
        chars_m1.append(c)
    bible_m1 = {
        "schema_version": 2, "revision": 4,
        "book": {"title": "雾锁九门", "genre": "都市悬疑", "language": "zh",
                 "platform": "qidian", "logline": "M1 格式迁移验证"},
        "opening_contract": {"want_visible_by": 1500, "disturbance_in_ch1": True,
                             "dialogue_ratio_min": 0.40, "no_info_dump": True},
        "characters": chars_m1,
        "world": {"setting": "九十年代末，某南方城市的老九门典当行街", "glossary": []},
        "compass": {"ending_direction": "旧铺号", "reader_promise": "计划被推翻", "active_long_line_ids": []},
        "arc": {"template": "悬疑假设弧", "anchors": ["开局：扰动落地@第1章"],
                "total_chapters": 12, "locked_through": 1, "planned_through": 12},
        "ledger": json.loads(json.dumps(LEDGER_SEED)),
        "shadows": [],
        "chapters": {"1": {"status": "written", "card_path": "chapters/ch01/card.json",
                           "card": card_m1, "selected_branch": "A",
                           "branches_path": "discussions/ch01.branches.json",
                           "discussion": "discussions/ch01.jsonl"}},
    }
    with open(wb.bible_path(M1COPY), "w", encoding="utf-8") as f:
        json.dump(bible_m1, f, ensure_ascii=False, indent=2)
    wb._write_json(os.path.join(d, "chapters", "ch01", "card.json"), card_m1)
    with open(os.path.join(d, "chapters", "ch01", "drafts", "v001.md"), "w", encoding="utf-8") as f:
        f.write("雨夜，柜上收进一块怀表。「按规矩说，死当不问来路。」陆小满把当票压在算盘底下，"
                "怀表背面刻痕在灯下一清二楚。贺三刀的茶碗停在半空，笑得很慢。")
    with open(os.path.join(d, "discussions", "ch01.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "user", "content": "选分支A"}, ensure_ascii=False) + "\n")


def main():
    print(f"=== workbench smoke (M2 canon/projection/exempt) ROOT={ROOT} ===")

    # ============ 0. M1 格式真实副本（按 M1 提交态程序化构造，可重复跑） ============
    seed_m1_copy()
    pre = load_json(wb.bible_path(M1COPY))
    check("副本确为 M1 格式（schema v2、人物无 id、ch1 written）",
          pre.get("schema_version") == 2 and "id" not in pre["characters"][0]
          and (pre["chapters"].get("1") or {}).get("status") == "written")

    # ============ 1. 主流程：new → … → commit（真实 LLM，投影关） ============
    if os.path.isdir(wb.ws_dir(BOOK)):
        shutil.rmtree(wb.ws_dir(BOOK))
    new_input = ("雾锁九门\n都市悬疑\nzh\nqidian\n"
                 "典当行学徒发现每件死当品里都住着一个未完成的执念，而最新的一件，是他失踪师父的怀表。\n"
                 "九十年代末，某南方城市的老九门典当行街\n悬疑假设弧\n12\n"
                 "真相埋在三十年前师父学徒的旧铺号\n每章都有一次计划被推翻的爽感\n")
    r = run(["new", BOOK], input=new_input)
    check("new 退出码 0", r.returncode == 0, r.stderr[-500:])
    bible = wb.load_bible(BOOK)
    check("bible schema v3 + 投影默认关",
          bible.get("schema_version") == 3
          and (bible["book"].get("context_projection")) is False)
    check("compass/arc/shadows 默认齐全",
          bible.get("shadows") == [] and bible["arc"].get("locked_through") == 0
          and bible["compass"].get("active_long_line_ids") == [])

    bible = wb.load_bible(BOOK)
    seed_v3_book(bible)
    r = run(["char", BOOK, "list"])
    check("char list 显示 id 与 never_learn", "char_01" in r.stdout and "F1_REVEAL" in r.stdout)

    bible = wb.load_bible(BOOK)
    seed_branches(bible)
    r = run(["discuss", BOOK, "1"], input="A\nlock\n")
    check("discuss 退出码 0", r.returncode == 0, (r.stderr or "")[-500:])
    bible = wb.load_bible(BOOK)
    check("status=discussed 且选中分支 A",
          (bible["chapters"].get("1") or {}).get("status") == "discussed"
          and bible["chapters"]["1"].get("selected_branch") == "A")

    r = run(["lock", BOOK, "1"], input="y\n")
    print("--- lock 输出尾部 ---")
    print((r.stdout or r.stderr)[-400:])
    check("card.json 已落盘", os.path.exists(wb.card_file(BOOK, 1)))
    if os.path.exists(wb.card_file(BOOK, 1)):
        card = load_json(wb.card_file(BOOK, 1))
        bible = wb.load_bible(BOOK)
        check("card.json 通过 validate_card", validate_card(card, bible, expected_chapter=1) == [],
              str(validate_card(card, bible, expected_chapter=1)))
        check("pov/pressure 已归一为人物 id",
              card["pov"]["character"].startswith("char_")
              and all(p["char"].startswith("char_") for p in card["engine"]["pressure"]))
        check("card 含 P3 引用字段",
              card.get("recorded_consequence", "missing") is None)
    else:
        RESULTS.append(False)

    r = run(["write", BOOK, "1"])
    print("--- write 输出尾部 ---")
    print((r.stdout or r.stderr)[-500:])
    draft1 = os.path.join(wb.drafts_dir(BOOK, 1), "v001.md")
    delta1 = os.path.join(wb.drafts_dir(BOOK, 1), "v001.delta.json")
    lint1 = os.path.join(wb.drafts_dir(BOOK, 1), "v001.lint.json")
    check("drafts/v001.md 已产出", os.path.exists(draft1) and os.path.getsize(draft1) > 300)
    check("v001.delta.json 三件套结构",
          os.path.exists(delta1) and (lambda d: d.get("chapter") == 1 and d.get("draft") == "v001"
                                      and d.get("base_state_revision") == 0
                                      and isinstance(d.get("ops"), list))(load_json(delta1)))
    check("v001.lint.json 绑定正文 hash",
          os.path.exists(lint1)
          and load_json(lint1).get("source_text_sha1") == text_sha1(open(draft1, encoding="utf-8").read()))
    bible = wb.load_bible(BOOK)
    check("状态机 drafted", (bible["chapters"]["1"] or {}).get("status") == "drafted")
    check("write 不产 canon.md", not os.path.exists(wb.canon_file(BOOK, 1)))

    # commit（离线交互）：never_learn 冲突时自动修 delta（模拟作者手工删冲突 op）后重跑
    r = run(["commit", BOOK, "1"], input="y\n\n")
    if "never_learn" in (r.stdout or "") or "never_learn" in (r.stderr or ""):
        print("[flaky 防护] delta 撞 never_learn 红名单，模拟作者移除冲突 op 后重跑 commit")
        dp = os.path.join(drafts_dir(BOOK, 1), "v001.delta.json")
        dj = load_json(dp)
        bad = [o for o in dj.get("ops", [])
               if o.get("op") == "learn" and any(
                   o.get("fact_id") in nl for c in wb.load_bible(BOOK)["characters"]
                   if c.get("id") == o.get("character_id")
                   for nl in [c.get("knowledge_rules", {}).get("never_learn", [])])]
        dj["ops"] = [o for o in dj.get("ops", []) if o not in bad]
        with open(dp, "w", encoding="utf-8") as f:
            json.dump(dj, f, ensure_ascii=False, indent=1)
        r = run(["commit", BOOK, "1"], input="y\n\n")
    print("--- commit 输出尾部 ---")
    print((r.stdout or r.stderr)[-500:])
    canon1 = wb.canon_file(BOOK, 1)
    check("canon.md = draft 全文",
          os.path.exists(canon1) and open(canon1, encoding="utf-8").read()
          == open(draft1, encoding="utf-8").read())
    st = StoryState(wb.state_path(BOOK))
    check("state.revision 推进 + 备份存在 + as_of_chapter=1",
          st.revision == 1 and st.data["as_of_chapter"] == 1
          and os.path.exists(wb.state_path(BOOK) + ".bak-0"))
    check("card.recorded_consequence 已回填",
          (load_json(wb.card_file(BOOK, 1)).get("recorded_consequence") or "") != "")
    bible = wb.load_bible(BOOK)
    check("状态机 committed", bible["chapters"]["1"].get("status") == "committed")
    delta1d = load_json(delta1)
    if any(op.get("op") == "learn" for op in delta1d["ops"]):
        fact_ids = {op["fact_id"] for op in delta1d["ops"] if op.get("op") == "learn"}
        knows = set()
        for cdata in st.data["characters"].values():
            knows |= set((cdata.get("knowledge") or {}).get("knows") or [])
        check("delta learn 已推进 state.knowledge", fact_ids <= knows, f"{fact_ids} vs {knows}")

    # commit 负样本：同 delta 再 commit → base_state_revision 不匹配拒绝
    r = run(["commit", BOOK, "1"], input="y\n\n")
    check("重复 commit 被拒（revision 不匹配）", r.returncode == 1 and "不匹配" in r.stdout)

    # ============ 2. 离线段：FakeClient 写 ch2（投影双模式/canon 截断/版本递增） ============
    real_client_for = wb.client_for
    try:
        bible = wb.load_bible(BOOK)
        card2 = seed_ch2_card(bible)
        # canon 已提交；往 ch1 draft 追加草稿独有标记（canon 不受影响）
        with open(draft1, "a", encoding="utf-8") as f:
            f.write("\nDRAFT-ONLY-MARKER-草稿独有内容不应进入下一章上下文。")
        bible = wb.load_bible(BOOK)
        bible["shadows"] = [{"id": "S1", "note": "SHADOW-MARKER-绝不可见"}]
        wb.save_bible(BOOK, bible)

        # —— 投影开 ——
        bible["book"]["context_projection"] = True
        wb.save_bible(BOOK, bible)
        fake = FakeClient([_short_paras_prose(), json.dumps(
            {"chapter": 2, "draft": "v001", "base_state_revision": 1, "ops": [
                {"op": "learn", "character_id": "陆小满", "fact_id": "F1_HOOK",
                 "evidence": "陆小满把怀表贴在耳边，表芯的声音像有人在敲门。"},
                {"op": "teleport", "character_id": "char_01", "evidence": "雨夜。"},
                {"op": "set_location", "character_id": "char_01", "value": "典当行阁楼",
                 "evidence": "这句话不在正文里，应被丢弃。"},
                {"op": "set_location", "character_id": "char_01", "value": "典当行阁楼",
                 "evidence": "他决定今晚就把地名查清楚。"}]}, ensure_ascii=False)])
        wb.client_for = lambda *a, **k: fake
        wb.cmd_write(["smoke-wb", "2"])
        full = "\n".join(m["content"] for c in fake.calls if c["tag"] == "wb-ch02"
                         for m in c["messages"])
        canon1_text = open(canon1, encoding="utf-8").read().strip()
        tail10 = canon1_text[-10:]
        check("投影开：写 ch2 上下文不含 ch1 drafts（DRAFT-ONLY-MARKER 隔离）",
              "DRAFT-ONLY-MARKER" not in full)
        check("投影开：前章 canon 进 HOT（末300字）", tail10 in full)
        check("投影开：WARM 有摘要/未闭合钩子/锚点",
              "canon 摘要" in full and "未闭合钩子" in full and "锚点" in full)
        check("投影开：无 E 臂全文暗账、无 COLD、无 shadows",
              "完整的伏笔设定" not in full and "SHADOW-MARKER" not in full
              and "默认不注入" not in full)
        check("投影开：章节卡合约+对话密度进 HOT", "作者合约" in full and "对话密度" in full)
        delta2 = load_json(os.path.join(wb.drafts_dir(BOOK, 2), "v001.delta.json"))
        check("delta 预清洗：name→id 改写 + 非白名单/坏 evidence op 丢弃",
              len(delta2["ops"]) == 2
              and all(op.get("character_id", "").startswith("char_") for op in delta2["ops"]
                      if "character_id" in op)
              and all(op["op"] in ("learn", "set_location") for op in delta2["ops"]),
              json.dumps(delta2, ensure_ascii=False))
        check("delta base_state_revision 取自代码（=state.revision）",
              delta2["base_state_revision"] == StoryState(wb.state_path(BOOK)).revision)
        check("ch2 首稿 v001（draft 版本号按章内递增）",
              os.path.exists(os.path.join(wb.drafts_dir(BOOK, 2), "v001.md")))

        # —— commit ch2（离线）：验收 #5 的确定性 state 推进 ——
        wb.client_for = real_client_for
        r = run(["commit", BOOK, "2"], input="y\n\n")
        check("commit ch2 退出码 0", r.returncode == 0, (r.stderr or "")[-400:])
        st = StoryState(wb.state_path(BOOK))
        c01 = st.data["characters"].get("char_01") or {}
        check("验收5：characters.knowledge 正确推进（knows=F1_HOOK，location 回填）",
              st.revision == 2 and "F1_HOOK" in (c01.get("knowledge") or {}).get("knows", [])
              and c01.get("location") == "典当行阁楼"
              and os.path.exists(wb.state_path(BOOK) + ".bak-1"),
              json.dumps(st.data["characters"], ensure_ascii=False)[:200])

        # —— 投影关（M1 行为）——
        bible = wb.load_bible(BOOK)
        bible["book"]["context_projection"] = False
        wb.save_bible(BOOK, bible)
        fake = FakeClient([_short_paras_prose(), json.dumps(
            {"chapter": 2, "draft": "v002", "base_state_revision": 2, "ops": [
                {"op": "learn", "character_id": "char_01", "fact_id": "F1_REVEAL",
                 "evidence": "他决定今晚就把地名查清楚。"}]}, ensure_ascii=False)])
        wb.client_for = lambda *a, **k: fake
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            wb.cmd_write(["smoke-wb", "2"])
        out2 = buf.getvalue()
        full = "\n".join(m["content"] for c in fake.calls if c["tag"] == "wb-ch02"
                         for m in c["messages"])
        check("投影关：M1 E 臂形态（全文历史+完整暗账）",
              "完整的伏笔设定" in full and "已完成的章节" in full)
        check("投影关：前文仍是 canon（不含 ch1 草稿独有内容）",
              "DRAFT-ONLY-MARKER" not in full and tail10 in full)
        check("投影关：never_learn 冲突提前警告（不丢弃，commit 才硬拒）",
              "never_learn 冲突" in out2, out2[-300:])
        check("draft 版本按章内递增 v002",
              os.path.exists(os.path.join(wb.drafts_dir(BOOK, 2), "v002.md")))
    finally:
        wb.client_for = real_client_for

    # —— 豁免生命周期（P6，离线） ——
    r = run(["exempt", BOOK, "2", "分节碎", "结构刻意短句，保留"])
    check("exempt 登记成功", r.returncode == 0 and "豁免已登记" in r.stdout, (r.stdout or r.stderr)[-300:])
    st = StoryState(wb.state_path(BOOK))
    exs = [e for e in st.data["exemptions"] if e["scope"]["chapter"] == 2]
    check("豁免入 state 且指纹 16 位", exs and len(exs[-1]["fingerprint"]) == 16)
    v002 = os.path.join(wb.drafts_dir(BOOK, 2), "v002.md")
    lint3 = load_json(os.path.join(wb.drafts_dir(BOOK, 2), "v002.lint.json"))
    check("ch2 v002 lint 确定性触发分节碎", "分节碎" in lint3["flags"], str(lint3["flags"]))
    kept, exempted = st.filter_flags(lint3["flags"], 2, text_sha1(open(v002, encoding="utf-8").read()))
    check("豁免后 lint 不再报该项", "分节碎" not in kept and "分节碎" in exempted)
    with open(v002, "a", encoding="utf-8") as f:
        f.write("\n正文改动：作者把这一段重写了，豁免应失效。")
    kept, exempted = st.filter_flags(lint3["flags"], 2, text_sha1(open(v002, encoding="utf-8").read()))
    check("正文改动后豁免自动失效", "分节碎" in kept and "分节碎" not in exempted)

    # ============ 3. state.py 负样本（验收 #4，离线） ============
    stx = StoryState(os.path.join(wb.ws_dir(BOOK), "state", "neg-test.json"))
    stx.ensure_characters(["char_01"])
    TEXT = "陆小满把怀表翻过来，背面刻痕在灯下一清二楚。他决定今晚就查。"
    ok = {"chapter": 1, "draft": "v001", "base_state_revision": 0, "ops": [
        {"op": "learn", "character_id": "char_01", "fact_id": "F1_HOOK", "evidence": "背面刻痕在灯下一清二楚"}]}
    check("合法 delta 零违规", stx.validate_delta(ok, TEXT) == [])
    v = stx.validate_delta(dict(ok, base_state_revision=9), TEXT)
    check("负样本：base_state_revision 不匹配给出明确错误",
          v and "不匹配" in v[0], str(v))
    v = stx.validate_delta({"chapter": 1, "draft": "v001", "base_state_revision": 0,
                            "ops": [{"op": "teleport", "evidence": "x"}]}, TEXT)
    check("负样本：非白名单 op 给出明确错误", v and "非白名单" in v[0], str(v))
    v = stx.validate_delta({"chapter": 1, "draft": "v001", "base_state_revision": 0,
                            "ops": [{"op": "learn", "character_id": "char_01", "fact_id": "F1",
                                     "evidence": "这句不在正文里"}]}, TEXT)
    check("负样本：evidence 非子串给出明确错误", v and "子串" in v[0], str(v))
    v = stx.validate_delta({"chapter": 1, "draft": "v001", "base_state_revision": 0,
                            "ops": [{"op": "learn", "character_id": "char_01",
                                     "fact_id": "F1_REVEAL", "evidence": "他决定今晚就查"}]},
                           TEXT, {"char_01": {"never_learn": ["F1_REVEAL"]}})
    check("负样本：never_learn 冲突硬拒绝", v and "硬拒绝" in v[0] and "never_learn" in v[0], str(v))

    # ============ 4. M1 格式副本迁移续写（真实 LLM） ============
    r = run(["status", M1COPY])
    check("M1 副本 status 不报错", r.returncode == 0, (r.stderr or "")[-400:])
    mig = load_json(wb.bible_path(M1COPY))
    mcard_file = load_json(wb.card_file(M1COPY, 1))
    check("M1 副本迁移 v2→v3：id 生成/card.json 改写/written→drafted/投影默认关",
          mig.get("schema_version") == 3
          and mig["characters"][0].get("id") == "char_01"
          and mcard_file["pov"]["character"] == "char_01"
          and mig["chapters"]["1"]["status"] == "drafted"
          and mig["book"]["context_projection"] is False)
    r = run(["write", M1COPY, "1"])
    print("--- M1 副本 write 输出尾部 ---")
    print((r.stdout or r.stderr)[-400:])
    check("M1 副本续写出 v002（跨迁移版本递增）+ delta/lint 三件套",
          os.path.exists(os.path.join(wb.drafts_dir(M1COPY, 1), "v002.md"))
          and os.path.exists(os.path.join(wb.drafts_dir(M1COPY, 1), "v002.delta.json"))
          and os.path.exists(os.path.join(wb.drafts_dir(M1COPY, 1), "v002.lint.json")))
    r = run(["commit", M1COPY, "1"], input="y\n\n")
    check("M1 副本 commit 建正史（canon+state+备份）",
          r.returncode == 0 and os.path.exists(wb.canon_file(M1COPY, 1))
          and StoryState(wb.state_path(M1COPY)).revision == 1
          and os.path.exists(wb.state_path(M1COPY) + ".bak-0"), (r.stdout or r.stderr)[-400:])

    # ============ 5. v1 cell 格式（离线：status 迁移 + fake write 直通 + commit） ============
    if os.path.isdir(wb.ws_dir(LEGACY)):
        shutil.rmtree(wb.ws_dir(LEGACY))
    os.makedirs(wb.ws_dir(LEGACY), exist_ok=True)
    legacy_bible = {
        "book": {"title": "雾锁九门（旧格式）", "genre": "都市悬疑", "language": "zh",
                 "platform": "qidian", "logline": "迁移验证"},
        "characters": [{"name": "陆小满", "card": "学徒", "want": "查师父", "fear": "师父自愿消失"}],
        "world": {"setting": "s", "glossary": []},
        "arc": {"template": "悬疑假设弧", "anchors": [], "total_chapters": 12},
        "ledger": [LEDGER_SEED[0]],
        "chapters": {"1": {"status": "locked", "cell": {
            "chapter": 1, "arc_label": "开局", "amplitude": "L",
            "plan": "陆小满按规矩收下死当怀表凑钱赎表",
            "disruption": "贺三刀夜访施压并行，怀表背面刻着陌生地名",
            "crisis": "收下死当就得罪行会", "improvisation": "表面答应私下暗查",
            "pressure": [{"char": "陆小满", "motive": "fear",
                          "force": "怀表停在师父失踪那晚，怕师父自愿消失", "cost": "私查留把柄"}],
            "end_hook": "新信息型"}}},
    }
    with open(wb.bible_path(LEGACY), "w", encoding="utf-8") as f:
        json.dump(legacy_bible, f, ensure_ascii=False, indent=2)
    r = run(["status", LEGACY])
    check("v1 status 迁移不报错", r.returncode == 0 and "migrated" in r.stdout)
    lmig = load_json(wb.bible_path(LEGACY))
    check("v1 迁移链：cell 原样保留 + 包装卡 id 化",
          lmig["schema_version"] == 3
          and lmig["chapters"]["1"]["cell"]["pressure"][0]["char"] == "陆小满"
          and lmig["chapters"]["1"]["card"]["engine"]["pressure"][0]["char"] == "char_01")
    spec0 = {"language": "zh", "characters": legacy_bible["characters"], "ledger": legacy_bible["ledger"],
             "engine": {"cells": [legacy_bible["chapters"]["1"]["cell"]]}}
    directive0 = build_engine_directive(spec0, 1)
    bible_l = wb.load_bible(LEGACY)
    spec1 = wb.bible_to_spec(LEGACY, bible_l)
    check("v1 迁移后细胞指令逐字等价", build_engine_directive(spec1, 1) == directive0)

    real_client_for = wb.client_for
    try:
        fake = FakeClient([_short_paras_prose(), json.dumps(
            {"chapter": 1, "draft": "v001", "base_state_revision": 0, "ops": [
                {"op": "learn", "character_id": "陆小满", "fact_id": "F1",
                 "evidence": "雨点砸在窗纸上。"}]}, ensure_ascii=False)])
        wb.client_for = lambda *a, **k: fake
        wb.cmd_write([LEGACY, "1"])
        check("v1 write 直通（fake client）出三件套",
              os.path.exists(os.path.join(wb.drafts_dir(LEGACY, 1), "v001.md"))
              and os.path.exists(os.path.join(wb.drafts_dir(LEGACY, 1), "v001.delta.json")))
    finally:
        wb.client_for = real_client_for
    r = run(["commit", LEGACY, "1"], input="y\n\n")
    check("v1 commit 直通（无卡跳过 recorded_consequence 回填）",
          r.returncode == 0 and "跳过 recorded_consequence" in r.stdout
          and StoryState(wb.state_path(LEGACY)).revision == 1, (r.stdout or r.stderr)[-300:])

    # ============ 6. 投影单元断言：shadows 永不进投影 ============
    bible_p = wb.load_bible(BOOK)
    spec_p = wb.bible_to_spec(BOOK, bible_p)
    state_p = StoryState(wb.state_path(BOOK))
    canon_texts, prev_source = wb.prev_canon_texts(BOOK, 3)
    config = {"id_name_map": {c["id"]: c["name"] for c in bible_p["characters"]},
              "canon_texts": canon_texts, "prev_source": prev_source,
              "card": load_json(wb.card_file(BOOK, 2))}
    ctx = build_context(bible_p, state_p, spec_p, 3, config)
    joined = "\n".join(ctx["hot"] + ctx["warm"])
    check("投影单元：shadows/COLD 内容绝不进 hot+warm",
          "SHADOW-MARKER" not in joined and "默认不注入" not in joined)
    check("投影单元：canon 优先来源标注", prev_source.get(1) == "canon" and prev_source.get(2) == "canon")

    # ============ 7. status 总览 ============
    r = run(["status", BOOK])
    check("status 展示 committed/正史行", r.returncode == 0 and "★" in r.stdout
          and "state.revision" in r.stdout)

    n_fail = RESULTS.count(False)
    print(f"\n=== smoke 完成：{len(RESULTS) - n_fail}/{len(RESULTS)} 项通过 ===")
    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
