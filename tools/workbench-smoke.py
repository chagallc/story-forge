#!/usr/bin/env python3
"""工作台冒烟测试 v2（M1 card 流程，工单验收 #1/#2/#3/#4）。

主流程（BOOK=smoke-wb，每次清空重建）：
  new(schema v2) → char(手工 JSON seed) → discuss(seed 分支文件+选分支) →
  lock(章节卡生成+校验+确认) → write(硬门禁+drafts/v001.md) → status
  外加 write 硬门禁负样本（坏卡/无卡必须拒绝）。

迁移兼容（LEGACY=smoke-wb-legacy）：旧格式 bible（meta.cell）→ status 不报错 +
自动迁移 + 细胞指令等价（build_engine_directive 逐字比对）+ write 直通落笔。

schema 负样本（验收 #3）：5 组非法 card（缺字段/错枚举/未知人物/不同源），
逐组断言给出明确违规信息。

依赖 LLM（experiments/exp003 + config/models.local.json），跑一次约 4~6 次调用。
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import workbench as wb  # noqa: E402
from src.harness.engine import build_engine_directive  # noqa: E402
from src.harness.schema import validate_card  # noqa: E402

BOOK = "smoke-wb"
LEGACY = "smoke-wb-legacy"

_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
RESULTS = []


def run(args, input=None, timeout=600):
    return subprocess.run([sys.executable, "workbench.py", *args], input=input,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, cwd=ROOT, env=_ENV)


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    RESULTS.append(cond)
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail and not cond else ""))
    return cond


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


CHARACTERS = [
    {"name": "陆小满", "card": "24岁，九门典当行学徒，眼力毒，嘴更快。",
     "want": "赎回师父留下的怀表，弄清他失踪那晚去了哪",
     "need": "承认师父可能自己有秘密，而非只有受害者叙事",
     "wound": "孤儿，师父是唯一给过他姓氏的人",
     "value": "当铺规矩：死当不问来路——但他今天想破例",
     "fear": "师父是自愿消失的，根本没打算带上他",
     "contradiction": "守规矩的学徒要做一行里最破规矩的事",
     "voice": {"catchphrases": ["按规矩说", "这物件不干净"], "speech_habits": ["短句", "先报价后说话"],
               "sample_line": "按规矩说，死当不问来路。"}},
    {"name": "贺三刀", "card": "55岁，行会老理事，笑面，账算得极清。",
     "want": "把九门典当行并进行会统一管理",
     "need": "挽回三十年前他亲手做砸的一桩局",
     "wound": "当年他师父也是这样消失的，他选择了闭嘴",
     "value": "行会秩序高于个人恩怨",
     "fear": "陆小满查到当年的局和他有关",
     "contradiction": "最讲规矩的人靠破坏规矩起家",
     "voice": {"catchphrases": ["喝茶喝茶"], "speech_habits": ["绕着说", "从不先出价"], "sample_line": "喝茶喝茶，急什么。"}},
]

BRANCHES = [
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
     "beats": ["行会饭局，贺三刀场面话宣布并行意向",
               "陆小满替病着的师父挡酒周旋",
               "散席回铺，深夜有人送来怀表死当",
               "章末陆小满发现送当人的靴子沾着行会的茶渍"],
     "choice": "瞒下行会收下怀表",
     "motive_cost": "压陆小满的value（死当不问来路）；代价是违背自己的规矩",
     "reader_payoff": "画面：饭局上的暗流；信息：茶渍线索",
     "risks": ["开局一场饭局戏节奏偏慢"]},
    {"id": "C", "summary": "怀表先失窃：死当当夜怀表被人截走，陆小满追赃追出地名线索",
     "beats": ["怀表死当当夜被人从柜上截走",
               "陆小满凭眼力追到当铺街后巷",
               "截当人丢下怀表逃走，表盖新添一道刻痕",
               "章末刻痕里的地名指向三十年前的旧铺号"],
     "choice": "追赃（公然与截当人结怨）",
     "motive_cost": "压陆小满的want（查师父下落）；代价是与来历不明者结怨",
     "reader_payoff": "事件：当街追赃；画面：后巷对峙",
     "risks": ["第一章动作戏偏重，对话密度难保 40%"]},
]


def seed_branches(bible):
    """工单要求：smoke seed 用 branches 文件而非旧 discussion 格式。"""
    os.makedirs(os.path.join(wb.ws_dir(BOOK), "discussions"), exist_ok=True)
    bf = wb.branches_file(BOOK, 1)
    wb._write_json(bf, {"chapter": 1, "branches": BRANCHES})
    bible["chapters"]["1"] = {"status": "branching", "branches_path": wb.rel_path(BOOK, bf)}
    wb.save_bible(BOOK, bible)


def main():
    print(f"=== workbench smoke (M1 card flow) ROOT={ROOT} ===")

    # ---------- 0. 主流程建书：new（清空重建，交互式命令用管道喂输入） ----------
    if os.path.isdir(wb.ws_dir(BOOK)):
        shutil.rmtree(wb.ws_dir(BOOK))
    new_input = ("雾锁九门\n都市悬疑\nzh\nqidian\n"
                 "典当行学徒发现每件死当品里都住着一个未完成的执念，而最新的一件，是他失踪师父的怀表。\n"
                 "九十年代末，某南方城市的老九门典当行街\n悬疑假设弧\n12\n"
                 "真相埋在三十年前师父学徒的旧铺号\n每章都有一次计划被推翻的爽感\n")
    r = run(["new", BOOK], input=new_input)
    check("new 退出码 0", r.returncode == 0, r.stderr[-500:])
    bible = wb.load_bible(BOOK)
    check("bible schema_version == 2", bible.get("schema_version") == 2)
    check("bible revision >= 1", bible.get("revision", 0) >= 1)
    check("compass 默认字段齐全",
          set(bible.get("compass", {})) == {"ending_direction", "reader_promise", "active_long_line_ids"}
          and bible["compass"]["ending_direction"] != "")
    check("arc locked_through/planned_through",
          bible["arc"].get("locked_through") == 0 and bible["arc"].get("planned_through") == 12)
    check("shadows 默认空数组", bible.get("shadows") == [])

    # ---------- 1. char：手工 JSON seed（工单验收 #4 指定方式） ----------
    bible["characters"] = json.loads(json.dumps(CHARACTERS))
    # 暗账 seed（v1 smoke 同款 F1；lock 提示的 allowed/active_hook_ids 由此而来）
    bible["ledger"] = [{"id": "F1", "plant_chapter": 1, "reveal_chapter": 3,
                        "hook": "怀表背面刻着一个不属于师父籍贯的地名，只给特写不解释",
                        "reveal_plan": "地名是师父三十年前当学徒的旧铺号，贺三刀当年就在那里",
                        "canary": "泉 lock"}]
    wb.save_bible(BOOK, bible)
    r = run(["char", BOOK, "list"])
    check("char list 显示 2 个人物", r.returncode == 0 and "陆小满" in r.stdout and "贺三刀" in r.stdout)

    # ---------- 2. discuss：seed 分支文件 → 选分支 → 阶段二 REPL ----------
    bible = wb.load_bible(BOOK)
    seed_branches(bible)
    r = run(["discuss", BOOK, "1"], input="A\nlock\n")
    check("discuss 退出码 0", r.returncode == 0, (r.stderr or "")[-500:])
    bible = wb.load_bible(BOOK)
    meta1 = bible["chapters"].get("1") or {}
    log_path = os.path.join(wb.ws_dir(BOOK), "discussions", "ch01.jsonl")
    check("讨论已存档 ch01.jsonl", os.path.exists(log_path))
    check("status=discussed 且选中分支 A",
          meta1.get("status") == "discussed" and meta1.get("selected_branch") == "A")

    # ---------- 3. lock：章节卡生成 + 校验 + 作者确认 ----------
    r = run(["lock", BOOK, "1"], input="y\n")
    print("--- lock 输出尾部 ---")
    print(r.stdout[-1200:] if r.stdout else r.stderr[-800:])
    cf = wb.card_file(BOOK, 1)
    check("card.json 已落盘", os.path.exists(cf))
    if os.path.exists(cf):
        card = load_json(cf)
        bible = wb.load_bible(BOOK)
        check("card.json 通过 validate_card", validate_card(card, bible, expected_chapter=1) == [],
              str(validate_card(card, bible, expected_chapter=1)))
        meta1 = bible["chapters"]["1"]
        check("meta: status/card_path/card 齐全且无 cell",
              meta1.get("status") == "locked" and meta1.get("card_path") == "chapters/ch01/card.json"
              and isinstance(meta1.get("card"), dict) and "cell" not in meta1)
        check("engine 细胞字段族齐全",
              all(k in card.get("engine", {}) for k in
                  ("arc_label", "amplitude", "plan", "disruption", "crisis", "improvisation",
                   "pressure", "end_hook")))
        check("base_state_revision 为 int 且 = 锁定时的 bible revision",
              isinstance(card.get("base_state_revision"), int))
        check("arc.locked_through 推进到 1 且锚点回填",
              bible["arc"].get("locked_through") == 1 and bible["arc"].get("anchors"))
    else:
        RESULTS.append(False)

    # ---------- 4. write：硬门禁 + drafts/v001.md ----------
    r = run(["write", BOOK, "1"])
    print("--- write 输出尾部 ---")
    print(r.stdout[-600:] if r.stdout else r.stderr[-600:])
    draft1 = os.path.join(wb.drafts_dir(BOOK, 1), "v001.md")
    check("drafts/v001.md 已产出", os.path.exists(draft1) and os.path.getsize(draft1) > 300)
    bible = wb.load_bible(BOOK)
    check("status=written", (bible["chapters"].get("1") or {}).get("status") == "written")
    check("旧路径 chapters/ch01.md 不再产出", not os.path.exists(os.path.join(wb.chapters_dir(BOOK), "ch01.md")))
    check("build/spec.json 派生落盘且带 _generated",
          os.path.exists(os.path.join(wb.ws_dir(BOOK), "build", "spec.json"))
          and "_generated" in load_json(os.path.join(wb.ws_dir(BOOK), "build", "spec.json")))

    # 硬门禁负样本：坏卡拒绝（不再调 LLM、不新增 draft）
    good_card = load_json(cf)
    bad_card = dict(good_card)
    bad_card["engine"] = {**good_card["engine"], "amplitude": "XXL"}
    wb._write_json(cf, bad_card)
    n_drafts = len(os.listdir(wb.drafts_dir(BOOK, 1)))
    r = run(["write", BOOK, "1"])
    check("坏卡被硬门禁拒绝（退出码 1 + 明确违规）",
          r.returncode == 1 and "硬门禁" in r.stdout and "amplitude" in r.stdout)
    check("坏卡未产生新 draft", len(os.listdir(wb.drafts_dir(BOOK, 1))) == n_drafts)
    wb._write_json(cf, good_card)  # 还原
    # 文件权威回退：删 card.json 后 load_card 走 meta.card 镜像（决策 1）
    os.rename(cf, cf + ".bak")
    card_fb, src_fb = wb.load_card(BOOK, 1, wb.load_bible(BOOK)["chapters"]["1"])
    check("card.json 缺失时回退 meta.card 镜像",
          src_fb == "meta" and card_fb.get("chapter") == 1)
    os.rename(cf + ".bak", cf)
    # 硬门禁负样本：真·无卡（从未 lock 的第 2 章）
    r = run(["write", BOOK, "2"])
    check("无卡章节被硬门禁拒绝", r.returncode == 1 and "硬门禁" in r.stdout)

    # ---------- 5. status ----------
    r = run(["status", BOOK])
    check("status 显示 written 标记与锁定进度",
          r.returncode == 0 and "★" in r.stdout and "locked_through=1" in r.stdout)

    # ---------- 6. 迁移兼容：旧格式 bible（meta.cell）→ status/write 行为等价 ----------
    if os.path.isdir(wb.ws_dir(LEGACY)):
        shutil.rmtree(wb.ws_dir(LEGACY))
    legacy_cell = {
        "chapter": 1, "arc_label": "开局：扰动落地", "amplitude": "L",
        "plan": "陆小满按规矩收下死当怀表凑钱赎表，不惊动任何人",
        "disruption": "贺三刀夜访施压并行，怀表背面刻着不属于师父的地名",
        "crisis": "接下死当就得罪行会，不接就丢了查师父的唯一线索",
        "improvisation": "陆小满表面答应并行条款，私下记下地名准备暗查",
        "pressure": [
            {"char": "陆小满", "motive": "fear", "force": "怀表停在师父失踪那晚，师父可能自愿消失",
             "cost": "私查地名留下把柄"},
            {"char": "贺三刀", "motive": "contradiction", "force": "用规矩话术破坏规矩推行并局",
             "cost": "深夜登门留下把柄"}],
        "end_hook": "新信息型",
    }
    legacy_bible = {
        "book": {"title": "雾锁九门（旧格式）", "genre": "都市悬疑", "language": "zh",
                 "platform": "qidian", "logline": "同主书，用于旧格式迁移验证"},
        "opening_contract": {"want_visible_by": 1500, "disturbance_in_ch1": True,
                             "dialogue_ratio_min": 0.40, "no_info_dump": True, "notes": "0005"},
        "characters": json.loads(json.dumps(CHARACTERS)),
        "world": {"setting": "九十年代末，某南方城市的老九门典当行街", "glossary": ["死当", "九门", "行会"]},
        "arc": {"template": "悬疑假设弧", "anchors": [], "total_chapters": 12},
        "ledger": [{"id": "F1", "plant_chapter": 1, "reveal_chapter": 3,
                    "hook": "怀表背面刻着一个不属于师父籍贯的地名，只给特写不解释",
                    "reveal_plan": "地名是师父三十年前当学徒的旧铺号，贺三刀当年就在那里", "canary": "泉 lock"}],
        "chapters": {"1": {"status": "locked", "cell": legacy_cell}},
    }
    os.makedirs(wb.ws_dir(LEGACY), exist_ok=True)
    # 直接写原始 JSON（不经 save_bible，保持旧格式原貌）
    with open(wb.bible_path(LEGACY), "w", encoding="utf-8") as f:
        json.dump(legacy_bible, f, ensure_ascii=False, indent=2)

    # 迁移前基线：旧路径 bible_to_spec 的细胞指令
    spec0 = {"id": legacy_bible["book"]["title"], "language": "zh", "title": legacy_bible["book"]["title"],
             "premise": legacy_bible["book"]["logline"], "characters": legacy_bible["characters"],
             "beats": ["x"], "ledger": legacy_bible["ledger"],
             "engine": {"template": "悬疑假设弧", "arc": [], "envelope": [], "cells": [legacy_cell]}}
    directive0 = build_engine_directive(spec0, 1)

    r = run(["status", LEGACY])
    check("旧格式 status 不报错", r.returncode == 0 and "开局" in r.stdout, (r.stderr or "")[-500:])
    mb = load_json(wb.bible_path(LEGACY))
    check("status 后自动迁移落盘（schema v2 + 默认字段）",
          mb.get("schema_version") == 2 and mb.get("compass") is not None and mb.get("shadows") == []
          and mb["arc"].get("locked_through") == 0)
    wrapped = (mb["chapters"]["1"].get("card") or {})
    check("旧 cell 包装为 card.engine", wrapped.get("engine", {}).get("plan") == legacy_cell["plan"]
          and wrapped.get("chapter") == 1 and wrapped.get("legacy") is True
          and "chapter" not in wrapped["engine"])

    bible2 = wb.load_bible(LEGACY)
    spec1 = wb.bible_to_spec(LEGACY, bible2)
    check("迁移后 spec 细胞与旧 cell 逐字等价", spec1["engine"]["cells"] == [legacy_cell])
    check("细胞指令等价（build_engine_directive 逐字比对）",
          build_engine_directive(spec1, 1) == directive0)

    r = run(["write", LEGACY, "1"])
    print("--- legacy write 输出尾部 ---")
    print(r.stdout[-600:] if r.stdout else r.stderr[-600:])
    check("旧格式 write 直通不报错且出 drafts/v001.md",
          r.returncode == 0 and "旧格式 meta.cell 直通" in r.stdout
          and os.path.exists(os.path.join(wb.drafts_dir(LEGACY, 1), "v001.md")))

    # ---------- 7. schema 负样本：5 组非法 card（验收 #3） ----------
    base = json.loads(json.dumps(good_card))
    check("基准卡本身零违规", validate_card(base, bible) == [])

    cases = []
    c1 = json.loads(json.dumps(base)); del c1["objective"]
    cases.append(("缺字段（无 objective）", c1, "objective"))
    c2 = json.loads(json.dumps(base)); c2["engine"]["amplitude"] = "XXL"
    cases.append(("错枚举（amplitude=XXL）", c2, "amplitude"))
    c3 = json.loads(json.dumps(base)); c3["engine"]["end_hook"] = "突然大反转"
    cases.append(("错枚举（end_hook）", c3, "end_hook"))
    c4 = json.loads(json.dumps(base))
    c4["engine"] = {**c4["engine"], "pressure": [{"char": "路人甲", "motive": "anger",
                                                  "force": "怀表地名指向旧铺号", "cost": "暴露行踪"}]}
    cases.append(("未知人物（pressure.char=路人甲）+ 错 motive 枚举", c4, "bible.characters"))
    c5 = json.loads(json.dumps(base))
    c5["engine"] = {**c5["engine"], "pressure": [
        {**c5["engine"]["pressure"][0], "force": "火星探测车今日着陆"}]}
    cases.append(("force 与 plan/disruption 不同源", c5, "同源"))

    for name, card_bad, expect in cases:
        vs = validate_card(card_bad, bible, expected_chapter=1)
        hit = any(expect in x for x in vs)
        check(f"非法卡：{name}", bool(vs) and hit, f"期望含“{expect}”，实际：{vs}")

    # ---------- 汇总 ----------
    n_fail = RESULTS.count(False)
    print(f"\n=== smoke 完成：{len(RESULTS) - n_fail}/{len(RESULTS)} 项通过 ===")
    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
