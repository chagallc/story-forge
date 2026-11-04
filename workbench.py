#!/usr/bin/env python3
"""story-forge 写作工作台 v2：人机协作章节工作流（M1：章节卡与多线推演）。

用法：
  python workbench.py new <书名>             # 建 workspace（交互式，bible schema v2）
  python workbench.py char <书名> add        # 加人物卡（动机栈+声口）
  python workbench.py char <书名> list       # 人物列表
  python workbench.py discuss <书名> <章号>   # 两阶段讨论：3 条轻量分支选择 → 围绕选中分支 REPL
  python workbench.py lock <书名> <章号>     # 讨论结论固化为章节卡 card.json（校验+作者确认）
  python workbench.py write <书名> <章号>    # 落笔（硬门禁：无校验通过的 card.json 拒绝；出 drafts/vNNN.md）
  python workbench.py status <书名>          # 全书状态板

设计：docs/plans/M1-workorder.md / docs/plans/v2-整合方案.md（裁决一：章节卡分层嵌 cell）
/ docs/decisions/0003（动机压力层）/ 0005（开场契约）。

数据权威（M1 落地部分）：story-bible.json 唯一人工写入口（schema v2）；
chapters/chNN/card.json 作者确认后的章节卡文件（card_path 存在时以文件为准）；
build/spec.json 为 bible_to_spec 派生物（标注 _generated，可随时删除重建，禁止手改）。
旧格式兼容：加载无 schema_version 的 bible 自动迁移（meta.cell 包装为 card.engine，
旧 cell 行为等价直通，不经章节卡校验）。
"""
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from src.harness.agents import build_writer_messages  # noqa: E402
from src.harness.config import load_config  # noqa: E402
from src.harness.ledger import Ledger  # noqa: E402
from src.harness.llm import make_client  # noqa: E402
from src.harness.schema import validate_card  # noqa: E402
from src.harness.style_lint import lint_chapter  # noqa: E402

WS_ROOT = os.path.join(ROOT, "workspaces")
SCHEMA_VERSION = 2


def ws_dir(book):
    return os.path.join(WS_ROOT, book)


def bible_path(book):
    return os.path.join(ws_dir(book), "story-bible.json")


def chapters_dir(book):
    return os.path.join(ws_dir(book), "chapters")


def chapter_dir(book, ch):
    return os.path.join(chapters_dir(book), f"ch{ch:02d}")


def card_file(book, ch):
    return os.path.join(chapter_dir(book, ch), "card.json")


def drafts_dir(book, ch):
    return os.path.join(chapter_dir(book, ch), "drafts")


def branches_file(book, ch):
    return os.path.join(ws_dir(book), "discussions", f"ch{ch:02d}.branches.json")


def rel_path(book, path):
    """workspace 内相对路径（正斜杠，入 bible 元数据用）。"""
    return os.path.relpath(path, ws_dir(book)).replace(os.sep, "/")


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- P0：bible schema v2 与旧格式迁移 ----------------

def _ensure_defaults(bible):
    """补 v2 默认字段（幂等，保存前防御性调用）。"""
    bible.setdefault("revision", 0)
    bible.setdefault("compass", {"ending_direction": "", "reader_promise": "",
                                 "active_long_line_ids": []})
    arc = bible.setdefault("arc", {})
    arc.setdefault("locked_through", 0)
    arc.setdefault("planned_through", arc.get("total_chapters", 12))
    bible.setdefault("shadows", [])


def migrate_bible(bible):
    """旧版（无 schema_version）→ v2：补默认字段，meta.cell 包装为 card。

    旧 cell 原样放进 card.engine（cell 自身的 chapter 键移到 card.chapter 层），
    meta.cell 保留——带 cell 的章节在 write/spec 路径走「旧格式直通」，行为与 v1 等价。
    """
    if bible.get("schema_version") == SCHEMA_VERSION:
        return bible
    _ensure_defaults(bible)
    for ch, meta in (bible.get("chapters") or {}).items():
        if not isinstance(meta, dict) or not meta.get("cell") or meta.get("card"):
            continue
        cell = meta["cell"]
        meta["card"] = {
            "chapter": int(ch),
            "engine": {k: v for k, v in cell.items() if k != "chapter"},
            "legacy": True,
        }
    bible["schema_version"] = SCHEMA_VERSION
    return bible


def load_bible(book):
    with open(bible_path(book), encoding="utf-8") as f:
        bible = json.load(f)
    if bible.get("schema_version") != SCHEMA_VERSION:
        migrate_bible(bible)
        _write_json(bible_path(book), bible)  # 迁移结果立即落盘（一次性升级）
        print(f"migrated bible to schema v{SCHEMA_VERSION}: {bible_path(book)}")
    return bible


def save_bible(book, bible):
    _ensure_defaults(bible)
    bible["schema_version"] = SCHEMA_VERSION
    bible["revision"] = int(bible.get("revision", 0)) + 1
    _write_json(bible_path(book), bible)
    print(f"saved: {bible_path(book)} (revision {bible['revision']})")


# ---------------- 章节卡解析：文件 > meta.card > 旧 meta.cell ----------------

def cell_of(card):
    """card → 引擎细胞：engine 字段族原样透传，chapter 从卡顶层补齐（engine.py 契约）。"""
    cell = dict(card.get("engine") or {})
    cell.setdefault("chapter", card.get("chapter"))
    return cell


def load_card(book, ch, meta):
    """解析章节卡。返回 (card, source)；source: file|meta|legacy|None。

    - file：card_path 指向的 card.json 存在（作者确认后的文件权威）
    - meta：bible 内嵌 meta.card（无旧 cell 共存时）
    - legacy：旧 meta.cell 直通（行为等价 v1，跳过章节卡校验）
    """
    if not isinstance(meta, dict):
        return None, None
    cp = meta.get("card_path")
    if cp:
        p = cp if os.path.isabs(cp) else os.path.join(ws_dir(book), cp)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f), "file"
    if meta.get("cell"):
        cell = meta["cell"]
        return {"chapter": cell.get("chapter", ch), "engine": cell, "legacy": True}, "legacy"
    if meta.get("card"):
        return meta["card"], "meta"
    return None, None


def client_for(bible, role="writer", book=""):
    cfg = load_config(os.path.join(ROOT, "experiments", "exp003"))
    role_cfg = dict(cfg[role])
    if bible.get("book", {}).get("language") == "en":
        role_cfg["model"] = "gpt-5.6-terra"
        role_cfg["api_style"] = "codex"
        role_cfg.pop("extra_body", None)
    return make_client(role_cfg, os.path.join(ws_dir(book), "usage-workbench.jsonl"))


# ---------------- new ----------------

def cmd_new(args):
    book = args[0] if len(args) > 0 else input("书名（目录名，英文）: ").strip()
    d = ws_dir(book)
    os.makedirs(os.path.join(d, "chapters"), exist_ok=True)
    os.makedirs(os.path.join(d, "discussions"), exist_ok=True)
    print("== 建书（回车跳过）==")
    title = input("书名/标题: ").strip() or book
    genre = input("类型（如 修仙系统流/悬疑/progression fantasy）: ").strip()
    language = (input("语言 zh/en（默认 zh）: ").strip() or "zh")
    platform = input("目标平台（webnovel/qidian/...）: ").strip()
    logline = input("一句话故事: ").strip()
    setting = input("世界观一句话: ").strip()
    template = input("弧线模板（英雄之旅/悬疑假设弧/爽文蓄放弧）: ").strip()
    total = int(input("规划章数（默认12）: ").strip() or 12)
    ending_direction = input("终局方向（可空）: ").strip()
    reader_promise = input("读者核心承诺（可空）: ").strip()
    bible = {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "book": {
            "title": title,
            "genre": genre,
            "language": language,
            "platform": platform,
            "logline": logline,
        },
        "opening_contract": {
            "want_visible_by": 1500,
            "disturbance_in_ch1": True,
            "dialogue_ratio_min": 0.40,
            "no_info_dump": True,
            "notes": "见 docs/decisions/0005",
        },
        "characters": [],
        "world": {"setting": setting, "glossary": []},
        "compass": {
            "ending_direction": ending_direction,
            "reader_promise": reader_promise,
            "active_long_line_ids": [],
        },
        "arc": {"template": template,
                "anchors": [], "total_chapters": total,
                "locked_through": 0, "planned_through": total},
        "ledger": [],
        "shadows": [],
        "chapters": {},
    }
    save_bible(book, bible)
    print(f"\nworkspace 就绪：{d}\n下一步：python workbench.py char {book} add")


# ---------------- char ----------------

CHAR_FIELDS = [
    ("card", "一句话人物卡（身份/年龄/外貌要点）"),
    ("want", "want：表层欲望（他自己知道且承认）"),
    ("need", "need：深层需求（他自己没意识到）"),
    ("wound", "wound：旧伤（解释他为什么这样行事）"),
    ("value", "value：底线（可让他翻脸/越线的东西）"),
    ("fear", "fear：恐惧（压力测试点）"),
    ("contradiction", "contradiction：内在矛盾"),
]


def cmd_char(args):
    book = args[0]
    bible = load_bible(book)
    sub = args[1] if len(args) > 1 else "list"
    if sub == "add":
        name = input("姓名: ").strip()
        c = {"name": name}
        for key, prompt in CHAR_FIELDS:
            c[key] = input(f"{prompt}: ").strip() or None
        c = {k: v for k, v in c.items() if v}
        c["voice"] = {
            "catchphrases": [x.strip() for x in input("口头禅/标志行为（逗号分隔，可空）: ").split(",") if x.strip()],
            "speech_habits": [x.strip() for x in input("说话习惯（逗号分隔，可空）: ").split(",") if x.strip()],
            "sample_line": input("一句代表性台词（可空）: ").strip() or None,
        }
        c["voice"] = {k: v for k, v in c["voice"].items() if v}
        bible["characters"].append(c)
        save_bible(book, bible)
    elif sub == "list":
        for c in bible["characters"]:
            print(f"- {c['name']}：{c.get('card','')}")
            print(f"  want={c.get('want','-')} | fear={c.get('fear','-')}")
            if c.get("voice", {}).get("catchphrases"):
                print(f"  口头禅: {c['voice']['catchphrases']}")
    else:
        print("用法: char <书名> add|list")


# ---------------- 讨论：两阶段（P1/P5 多线推演） ----------------

def bible_summary(bible):
    chars = "\n".join(
        f"- {c['name']}：{c.get('card','')}｜want={c.get('want','-')}｜fear={c.get('fear','-')}"
        + (f"｜口头禅={c['voice']['catchphrases']}" if c.get('voice', {}).get('catchphrases') else "")
        for c in bible["characters"])
    ledger = "\n".join(f"- {e['id']}: {e.get('hook','')}" for e in bible.get("ledger", [])) or "（暂无）"
    lang = bible["book"].get("language", "zh")
    return (f"《{bible['book']['title']}》 类型:{bible['book'].get('genre')} 平台:{bible['book'].get('platform')}\n"
            f"一句话：{bible['book'].get('logline')}\n世界观：{bible['world'].get('setting','-')}\n"
            f"弧线：{bible['arc'].get('template')}，全书 {bible['arc'].get('total_chapters')} 章，锚点：{bible['arc'].get('anchors') or '待定'}\n"
            f"人物：\n{chars}\n暗账：\n{ledger}"), lang


def _extract_json(raw, container="auto"):
    """宽容截取 LLM 输出里的 JSON（array 或 object）。"""
    pairs = []
    if container in ("auto", "array"):
        pairs.append(("[", "]"))
    if container in ("auto", "object"):
        pairs.append(("{", "}"))
    for a, b in pairs:
        i, j = raw.find(a), raw.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(raw[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no valid JSON in output")


def _normalize_branches(data) -> list:
    """轻量分支规范化：补缺失字段，保证下游零崩溃。"""
    if isinstance(data, dict):
        data = data.get("branches") or []
    if not isinstance(data, list) or not data:
        raise ValueError("branches 不是非空数组")
    out = []
    for i, b in enumerate(data):
        b = b if isinstance(b, dict) else {}
        out.append({
            "id": str(b.get("id") or chr(65 + i)).strip().upper() or chr(65 + i),
            "summary": str(b.get("summary") or "").strip(),
            "beats": [str(x) for x in (b.get("beats") or [])][:6] or ["（未给出节拍）"],
            "choice": str(b.get("choice") or "").strip(),
            "motive_cost": str(b.get("motive_cost") or "").strip(),
            "reader_payoff": str(b.get("reader_payoff") or "").strip(),
            "risks": [str(x) for x in (b.get("risks") or [])],
        })
    return out


def print_branches(branches):
    for b in branches:
        print(f"\n【分支 {b['id']}】{b['summary']}")
        print("  节拍: " + " → ".join(b["beats"]))
        if b["choice"]:
            print(f"  选择: {b['choice']}")
        if b["motive_cost"]:
            print(f"  动机代价: {b['motive_cost']}")
        if b["reader_payoff"]:
            print(f"  读者获得: {b['reader_payoff']}")
        if b["risks"]:
            print(f"  风险: {'；'.join(b['risks'])}")


def gen_branches(client, bible, ch, lang, summary):
    """阶段一：LLM 产出 3 条轻量剧情分支（P5 多线推演）。"""
    if lang == "en":
        prompt = (f"Book state:\n{summary}\n\nWe are working on Chapter {ch}. Step 1: propose exactly 3 "
                  f"lightweight plot branches for the author to choose from. Reply with a strict JSON "
                  f"array (nothing else), each item: {{\"id\": \"A\", \"summary\": \"one-line direction\", "
                  f"\"beats\": [\"3-5 beats\"], \"choice\": \"the key choice to confirm this chapter\", "
                  f"\"motive_cost\": \"whose motive is pressured and the visible cost\", "
                  f"\"reader_payoff\": \"what the reader gets (info|emotion|event|visual)\", "
                  f"\"risks\": [\"risks of this line\"]}}")
    else:
        prompt = (f"书况：\n{summary}\n\n我们来讨论第 {ch} 章。第一步：请提出 3 条轻量剧情分支供作者选择。"
                  f"严格输出 JSON 数组（不要任何其他文字），每条格式："
                  f'{{"id": "A", "summary": "一句话方向", "beats": ["3-5 条节拍"], '
                  f'"choice": "本章要确认的关键选择", "motive_cost": "动机代价：压谁的哪个动机、付出什么可见代价", '
                  f'"reader_payoff": "读者获得（信息/情绪/事件/画面之一）", "risks": ["这条线的风险"]}}')
    raw = client.chat([{"role": "user", "content": prompt}], tag=f"branches-ch{ch:02d}")
    return _normalize_branches(_extract_json(raw, "array"))


def cmd_discuss(args):
    book, ch = args[0], int(args[1])
    bible = load_bible(book)
    summary, lang = bible_summary(bible)
    client = client_for(bible, "writer", book)

    os.makedirs(os.path.join(ws_dir(book), "discussions"), exist_ok=True)
    bf = branches_file(book, ch)
    meta = bible["chapters"].setdefault(str(ch), {})

    # 阶段一：轻量分支（已有分支文件则直接复用，regen 可重新生成）
    branches = None
    if os.path.exists(bf):
        try:
            with open(bf, encoding="utf-8") as f:
                branches = _normalize_branches(json.load(f).get("branches"))
            print(f"已有分支文件，直接选择：{bf}（输入 regen 可重新生成）")
        except (json.JSONDecodeError, ValueError):
            branches = None
    if branches is None:
        print("阶段一：生成 3 条轻量剧情分支 ...")
        branches = gen_branches(client, bible, ch, lang, summary)
        _write_json(bf, {"chapter": ch, "branches": branches})
        meta["branches_path"] = rel_path(book, bf)
        meta.setdefault("status", "branching")
        save_bible(book, bible)
    print_branches(branches)

    ids = [b["id"] for b in branches]
    while True:
        sel = input(f"\n选择分支（{'/'.join(ids)}，regen=重新生成，quit=放弃）> ").strip()
        if sel == "quit":
            print("讨论放弃（分支文件已存档，可稍后重跑 discuss 再选）。")
            return
        if sel == "regen":
            print("重新生成分支 ...")
            branches = gen_branches(client, bible, ch, lang, summary)
            _write_json(bf, {"chapter": ch, "branches": branches})
            print_branches(branches)
            ids = [b["id"] for b in branches]
            continue
        if sel.upper() in ids:
            sel = sel.upper()
            break
        print(f"无效分支 id：{sel}")

    branch = next(b for b in branches if b["id"] == sel)
    meta["branches_path"] = rel_path(book, bf)
    meta["selected_branch"] = sel

    # 阶段二：围绕选中分支深入讨论（原有 REPL 保留）
    beats = "；".join(branch["beats"])
    if lang == "en":
        system = ("You are the co-writer of this serialized novel. Your job in this session: discuss the "
                  "direction of one chapter with the author BEFORE any prose is written, building on the "
                  "branch the author selected. Push back when the author's idea breaks continuity or "
                  "weakens motive chains. Never write prose.")
        opener = (f"Book state:\n{summary}\n\nThe author selected branch {sel} for Chapter {ch}:\n"
                  f"Summary: {branch['summary']}\nBeats: {beats}\nKey choice: {branch['choice']}\n"
                  f"Motive cost: {branch['motive_cost']}\n"
                  f"Now nail down the chapter details with the author: opening state, time & place, "
                  f"objective and obstacle, choice and its cost, reader promise, ending hook. "
                  f"Flag continuity or motive-chain problems plainly. Never write prose.")
    else:
        system = ("你是这部连载小说的联合编剧。本次会话任务：在动笔之前与作者讨论一章的剧情方向，"
                  "以作者选定的分支为基础深入。作者的想法如果破坏连续性或削弱动机链，你要直说并给出修正。"
                  "全程不写正文。")
        opener = (f"书况：\n{summary}\n\n作者为第 {ch} 章选定了分支 {sel}：\n"
                  f"方向：{branch['summary']}\n节拍：{beats}\n关键选择：{branch['choice']}\n"
                  f"动机代价：{branch['motive_cost']}\n"
                  f"请围绕该分支与作者敲定本章细节：开场状态、时间地点、目标与阻力、选择与代价、"
                  f"读者承诺、断章钩子。连续性或动机链有问题要直说。全程不写正文。")

    msgs = [{"role": "system", "content": system}, {"role": "user", "content": opener}]
    turns = [{"role": "user", "content": opener}]
    print(f"\n=== 第 {ch} 章剧情讨论·分支 {sel}（输入内容回车发送；'lock' 结束讨论去生成章节卡；'quit' 放弃）===")
    while True:
        reply = client.chat(msgs, tag=f"discuss-ch{ch:02d}")
        msgs.append({"role": "assistant", "content": reply})
        turns.append({"role": "ai", "content": reply})
        print(f"\n【编剧】\n{reply}\n")
        user = input("【你】> ").strip()
        if not user:
            continue
        if user == "quit":
            print("讨论放弃。")
            return
        if user == "lock":
            break
        msgs.append({"role": "user", "content": user})
        turns.append({"role": "user", "content": user})

    log_path = os.path.join(ws_dir(book), "discussions", f"ch{ch:02d}.jsonl")
    with open(log_path, "w", encoding="utf-8") as f:
        for t in turns:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    meta["discussion"] = rel_path(book, log_path)
    meta["status"] = "discussed"
    save_bible(book, bible)
    print(f"\n讨论已存档：{log_path}\n下一步：python workbench.py lock {book} {ch}")


# ---------------- lock：讨论 → 章节卡 card.json ----------------

CARD_JSON_SPEC_ZH = (
    '{\n'
    '  "chapter": 章号(int),\n'
    '  "chapter_type": "单字母章型标记（自定，如 A=推进章）",\n'
    '  "base_state_revision": 0（系统会覆写，填 0 即可）,\n'
    '  "pov": {"character": "必须是人物名单之一", "tense": "past 或 present"},\n'
    '  "time_place": "本章时间地点，一句话",\n'
    '  "opening_state": "本章开场的状态（承接上章结尾）",\n'
    '  "objective": "主角本章要什么",\n'
    '  "obstacle": "什么阻力在场",\n'
    '  "choice": {"selected": "作者确认的关键选择", "irreversible": true或false, "cost": "可见代价"},\n'
    '  "intended_consequence": "选择的预期后果",\n'
    '  "recorded_consequence": null（写完正文后回填，现在恒为 null）,\n'
    '  "reader_promise": {"type": "{promise_types}", "content": "本章给读者什么"},\n'
    '  "ending_state": "本章结尾的状态",\n'
    '  "allowed_fact_ids": ["本章允许使用的事实/暗账 id，无则 []"],\n'
    '  "prohibited_developments": ["禁止在本章发生的事"],\n'
    '  "active_hook_ids": ["本章需保持活跃的钩子 id，无则 []"],\n'
    '  "dialogue_budget": {"min_ratio": 0.4 到 0.7 之间的小数},\n'
    '  "engine": {\n'
    '    "arc_label": "弧线位置标签", "amplitude": "XL|L|M|S|B",\n'
    '    "plan": "主角计划", "disruption": "颠覆（新信息推翻计划）",\n'
    '    "crisis": "危机（失败代价具象化）", "improvisation": "临场应变（用新信息重构计划）",\n'
    '    "pressure": [{"char": "人物名单之一", "motive": "want|need|wound|value|fear|contradiction",\n'
    '                  "force": "受压内容（必须与 plan/disruption 共享关键名词，同源）", "cost": "行动的可见代价"}],\n'
    '    "end_hook": "{end_hooks}"\n'
    '  }\n'
    '}\n'
    '规则：pressure 至少 1 条且 force 必须与 plan/disruption 同源（共用关键名词）；'
    '所有叙述文字用{lang_name}；只输出 JSON，不要任何其他文字。')

CARD_SPEC_ZH = {"end_hooks": "新信息型|两难型|即将行动型|轻收束",
                "promise_types": "信息|情绪|事件|画面", "lang_name": "中文"}
CARD_SPEC_EN = {"end_hooks": "new-information|dilemma|about-to-act|quiet-close",
                "promise_types": "info|emotion|event|visual", "lang_name": "English"}


def _card_prompt(bible, ch, dialogue, branch, lang):
    names = [c["name"] for c in bible["characters"]]
    ledger_ids = [e["id"] for e in bible.get("ledger", [])]
    contract = bible.get("opening_contract", {})
    min_ratio = contract.get("dialogue_ratio_min", 0.4)
    branch_txt = json.dumps(branch, ensure_ascii=False) if branch else "（无，仅凭讨论记录）"
    subs = CARD_SPEC_EN if lang == "en" else CARD_SPEC_ZH
    spec = CARD_JSON_SPEC_ZH
    for k, val in subs.items():
        spec = spec.replace("{" + k + "}", val)
    if lang == "en":
        head = (f"Below is the co-writing discussion for chapter {ch} (and the author-selected branch, "
                f"if any). Distill it into ONE chapter card as strict JSON (no other text). "
                f"Field spec:\n{spec}\n"
                f"Additional rules: chapter={ch}; pov.character and pressure[].char must be one of {names}; "
                f"engine.end_hook must be one of: new-information|dilemma|about-to-act|quiet-close; "
                f"reader_promise.type must be one of: info|emotion|event|visual; "
                f"dialogue_budget.min_ratio >= {min_ratio}; "
                f"allowed_fact_ids / active_hook_ids may only use these ledger ids: {ledger_ids or '[]'}.\n\n"
                f"Selected branch:\n{branch_txt}\n\nDiscussion:\n{dialogue}")
    else:
        head = (f"以下是第 {ch} 章的联合编剧讨论记录（可能附作者选定的分支）。把已达成的方向提炼为"
                f"一张完整章节卡，输出严格 JSON（不要任何其他文字）。字段规格：\n{spec}\n"
                f"附加规则：chapter={ch}；pov.character 与 pressure[].char 限 {names}；"
                f"reader_promise.type 限 信息|情绪|事件|画面；dialogue_budget.min_ratio >= {min_ratio}"
                f"（开场契约）；allowed_fact_ids / active_hook_ids 只能从这些暗账 id 里选：{ledger_ids or '[]'}"
                f"（无合适的就给 []）。\n\n选定的分支：\n{branch_txt}\n\n讨论记录：\n{dialogue}")
    return head


def cmd_lock(args):
    book, ch = args[0], int(args[1])
    bible = load_bible(book)
    meta = bible["chapters"].get(str(ch)) or {}
    if meta.get("status") == "locked":
        if input("该章已有章节卡，重新生成将覆盖 card.json，继续？(y=继续 / 其他=放弃): ").strip().lower() != "y":
            print("放弃。")
            return

    # 素材：讨论记录（相对/绝对路径兼容）+ 选定分支
    dialogue = ""
    log_path = meta.get("discussion")
    if log_path:
        p = log_path if os.path.isabs(log_path) else os.path.join(ws_dir(book), log_path)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                turns = [json.loads(l) for l in f if l.strip()]
            dialogue = "\n\n".join(f"【{'编剧' if t['role'] == 'ai' else '作者'}】{t['content']}" for t in turns)
    branch = None
    bp = meta.get("branches_path")
    if bp:
        p = bp if os.path.isabs(bp) else os.path.join(ws_dir(book), bp)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                sel = meta.get("selected_branch")
                branch = next((b for b in json.load(f).get("branches", []) if b.get("id") == sel), None)
    if not dialogue and not branch:
        print("该章没有已存档的讨论/分支。先 discuss。")
        return

    client = client_for(bible, "writer", book)
    lang = bible["book"].get("language", "zh")
    prompt = _card_prompt(bible, ch, dialogue, branch, lang)

    msgs, violations, card = [{"role": "user", "content": prompt}], None, None
    for attempt in range(3):  # 首次 + 最多重试 2 次
        raw = client.chat(msgs, tag=f"lock-ch{ch:02d}")
        try:
            card = _extract_json(raw, "object")
        except ValueError:
            violations = ["输出不是合法 JSON 对象"]
            card = None
        if card is not None:
            card["chapter"] = ch
            card["base_state_revision"] = int(bible.get("revision", 0))  # 代码权威，覆写 LLM 值
            card.setdefault("recorded_consequence", None)
            violations = validate_card(card, bible, expected_chapter=ch)
            if not violations:
                break
        print(f"[lock] 第 {attempt + 1} 次生成未过校验：{'；'.join(violations)}")
        if attempt < 2:
            msgs.append({"role": "assistant", "content": raw})
            msgs.append({"role": "user", "content":
                         "章节卡校验未通过，违规清单：\n- " + "\n- ".join(violations)
                         + "\n请逐条修正后重新输出完整章节卡（严格 JSON，不要任何其他文字）。"})
    if violations:
        print("章节卡校验未通过（已重试 2 次），放弃。违规清单：")
        for x in violations:
            print(f"  - {x}")
        return

    print(json.dumps(card, ensure_ascii=False, indent=1))
    ok = input("确认固化此章节卡？(y=确认 / 其他=放弃): ").strip().lower()
    if ok != "y":
        print("放弃。")
        return

    ch_dir = chapter_dir(book, ch)
    os.makedirs(os.path.join(ch_dir, "drafts"), exist_ok=True)
    cf = card_file(book, ch)
    _write_json(cf, card)
    meta.update({"status": "locked", "card_path": rel_path(book, cf), "card": card})
    meta.pop("cell", None)  # 新格式正式锁定，移除旧 cell（彻底告别直通路径）
    bible["chapters"][str(ch)] = meta
    arc = bible["arc"]
    arc["locked_through"] = max(int(arc.get("locked_through", 0)), ch)
    anchors = arc.setdefault("anchors", [])
    tag = f"{card.get('engine', {}).get('arc_label', '')}@第{ch}章"
    if tag not in anchors:
        anchors.append(tag)
    save_bible(book, bible)
    print(f"\n第 {ch} 章章节卡已锁定：{cf}\n下一步：python workbench.py write {book} {ch}")


# ---------------- write：落笔（硬门禁 + drafts/vNNN.md） ----------------

class _LedgerSafe(Ledger):
    """workbench 写作路径的空暗账兜底。

    Ledger.directive_for 对空 entries 会 max() 空序列崩溃（v1 起就存在，
    new 建的书默认 ledger: []）。Ledger 类本身不许动，这里仅在 workbench
    侧兜底：entries 为空时返回无指令行；非空时行为与 Ledger 完全一致，
    防火墙语义不变（空账本无底牌可泄）。
    """

    def directive_for(self, chapter: int) -> str:
        if not self.entries:
            return "- 本章无特殊指令，按大纲推进。"
        return super().directive_for(chapter)


def bible_to_spec(book, bible):
    """把 story-bible 转成引擎 spec（复用 E 臂管线）。

    章节卡优先级：card.json（card_path 存在时）> meta.card.engine > 旧 meta.cell。
    产物落盘 build/spec.json（标注 _generated，可随时删除重建，禁止手改）。
    """
    cells = []
    for k, meta in sorted(bible["chapters"].items(), key=lambda kv: int(kv[0])):
        card, _ = load_card(book, int(k), meta)
        if card:
            cells.append(cell_of(card))
    spec = {
        "id": bible["book"]["title"],
        "language": bible["book"].get("language", "zh"),
        "title": bible["book"]["title"],
        "premise": bible["book"].get("logline", ""),
        "characters": bible["characters"],
        "beats": ["（工作台模式：见 engine.cells）"],
        "ledger": bible.get("ledger", []),
        "engine": {"template": bible["arc"].get("template", ""), "arc": [], "envelope": [], "cells": cells},
    }
    build_dir = os.path.join(ws_dir(book), "build")
    os.makedirs(build_dir, exist_ok=True)
    spec_out = dict(spec)
    spec_out["_generated"] = {"from": "story-bible.json", "bible_revision": bible.get("revision", 0),
                              "generated_at": datetime.now().isoformat(timespec="seconds")}
    _write_json(os.path.join(build_dir, "spec.json"), spec_out)
    return spec


def latest_text(book, ch):
    """前文读取：优先该章最新 draft，回退旧格式 chNN.md（旧 workspace 兼容）。"""
    d = drafts_dir(book, ch)
    if os.path.isdir(d):
        versions = sorted(f for f in os.listdir(d) if re.fullmatch(r"v\d+\.md", f))
        if versions:
            with open(os.path.join(d, versions[-1]), encoding="utf-8") as f:
                return f.read()
    legacy = os.path.join(chapters_dir(book), f"ch{ch:02d}.md")
    if os.path.exists(legacy):
        with open(legacy, encoding="utf-8") as f:
            return f.read()
    return ""


def next_draft_no(drafts):
    nos = [int(m.group(1)) for f in os.listdir(drafts)
           if (m := re.fullmatch(r"v(\d+)\.md", f))]
    return max(nos, default=0) + 1


def cmd_write(args):
    book, ch = args[0], int(args[1])
    bible = load_bible(book)
    meta = bible["chapters"].get(str(ch)) or {}
    card, source = load_card(book, ch, meta)

    # 硬门禁：无校验通过的章节卡拒绝落笔（旧格式 meta.cell 直通除外，行为等价 v1）
    if card is None:
        print("硬门禁：该章没有校验通过的章节卡（card.json）。先 discuss + lock。")
        sys.exit(1)
    if source == "legacy":
        print("（旧格式 meta.cell 直通：跳过章节卡校验，行为与 v1 等价）")
    else:
        violations = validate_card(card, bible, expected_chapter=ch)
        if violations:
            print("硬门禁拒绝：章节卡校验未通过，不落笔。违规清单：")
            for x in violations:
                print(f"  - {x}")
            sys.exit(1)

    spec = bible_to_spec(book, bible)
    client = client_for(bible, "writer", book)
    ledger = _LedgerSafe(spec)

    prev = [t for t in (latest_text(book, p) for p in range(1, ch)) if t]
    msgs = build_writer_messages("E", spec, ledger, prev, ch)
    print(f"writing chapter {ch} ...")
    text = client.chat(msgs, tag=f"wb-ch{ch:02d}")

    # lint + 可选润色
    lint = lint_chapter(text, spec.get("language", "zh"))
    print("lint flags:", lint["flags"] or ["clean"])

    drafts = drafts_dir(book, ch)
    os.makedirs(drafts, exist_ok=True)
    draft_path = os.path.join(drafts, f"v{next_draft_no(drafts):03d}.md")
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(text)
    bible["chapters"][str(ch)]["status"] = "written"
    save_bible(book, bible)
    print(f"\n落笔完成：{draft_path}（{len(text)} chars）")
    if spec.get("language", "zh") == "zh":
        print(f"金丝雀检查：{[e['canary'] for e in ledger.entries if e['canary'] in text and ch < e['reveal_chapter'] and ch != e['plant_chapter']] or '无泄漏'}")


# ---------------- status ----------------

def cmd_status(args):
    book = args[0]
    bible = load_bible(book)  # 旧格式自动迁移
    total = bible["arc"].get("total_chapters", 12)
    print(f"《{bible['book']['title']}》 {bible['book'].get('genre')} | {bible['book'].get('platform')} | {bible['book'].get('language')}")
    print(f"人物 {len(bible['characters'])} | 暗账 {len(bible.get('ledger', []))} 条 | 弧线 {bible['arc'].get('template')}")
    compass = bible.get("compass") or {}
    if compass.get("ending_direction") or compass.get("reader_promise"):
        print(f"终局方向：{compass.get('ending_direction') or '-'} | 读者承诺：{compass.get('reader_promise') or '-'}")
    print(f"进度：locked_through={bible['arc'].get('locked_through', 0)}"
          f" / planned_through={bible['arc'].get('planned_through', '-')} / revision={bible.get('revision', 0)}")
    marks = {"empty": "·", "branching": "◦", "discussed": "◇", "locked": "◆", "written": "★"}
    for ch in range(1, total + 1):
        meta = bible["chapters"].get(str(ch)) or {}
        status = meta.get("status", "empty")
        mark = marks.get(status, "?")
        card, source = load_card(book, ch, meta)
        eng = (card or {}).get("engine") or {}
        extra = " (旧cell)" if source == "legacy" else ""
        print(f"  {mark} 第{ch:>2}章 [{status:<9}] {eng.get('arc_label', '')} {eng.get('amplitude', '')}"
              f" {(eng.get('plan', '') or '')[:30]}{extra}")


def main():
    cmds = {"new": cmd_new, "char": cmd_char, "discuss": cmd_discuss,
            "lock": cmd_lock, "write": cmd_write, "status": cmd_status}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        return
    if sys.argv[1] != "new" and len(sys.argv) < 3:
        print("缺书名参数。示例：python workbench.py status <书名>")
        return
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
