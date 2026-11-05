#!/usr/bin/env python3
"""story-forge 写作工作台 v2：人机协作章节工作流（M3A：滚动连载 + 最小故事图谱）。

用法：
  python workbench.py new <书名>             # 建 workspace（交互式，bible schema v4）
  python workbench.py char <书名> add        # 加人物卡（四分区：动机栈+声口+知识边界+lorebook）
  python workbench.py char <书名> list       # 人物列表
  python workbench.py discuss <书名> <章号>   # 两阶段讨论：3 条轻量分支选择 → 围绕选中分支 REPL
  python workbench.py lock <书名> <章号>     # 讨论结论固化为章节卡 card.json（校验+作者确认）
  python workbench.py write <书名> <章号>    # 落笔（硬门禁；出 drafts/vNNN.md + delta.json + lint.json；
                                             #  前文只读 canon，绝不读 drafts）
  python workbench.py commit <书名> <章号>   # 人工提交正史：canon.md + state 原子推进 + recorded_consequence 回填
                                             #  （--revised <文件> 用作者修订版作为 canon 内容）
                                             #  成功后自动抽取章级事实（失败不阻塞）
  python workbench.py plan <书名> [--extend N]  # 滚动规划：canon 摘要+compass+未闭合钩子 → AI 提议锚点，
                                             #  作者逐条确认；纪律 planned-locked ≤ 8；自动追加 skeleton 卷
  python workbench.py map <书名> [--as-of N]  # 最小地图：facts 重放 → graph.json + map.html
                                             #  （Cytoscape 双视图/章节滑块/点击看 evidence）
  python workbench.py exempt <书名> <章号> <规则> <理由>  # 对最近 lint 的 finding 建豁免（指纹绑定正文 hash）
  python workbench.py books                  # 多书总览
  python workbench.py status <书名>          # 全书状态板

设计：docs/plans/M3A-workorder.md（P7s 滚动规划 + P-G1 ChapterFact 管线 + P-G2 最小地图）
/ docs/plans/M2-workorder.md / docs/plans/M1-workorder.md / docs/decisions/0003 / 0005。

数据权威（三层）：story-bible.json 作者创意与静态设定，唯一人工写入口（schema v4）；
state/story-state.json 已提交正史状态，唯一动态状态权威，只允许 src/harness/state.py 修改；
build/spec.json 引擎投影，可随时删除重建，禁止手改。chapters/chNN/card.json 作者确认后的
章节卡文件（card_path 存在时以文件为准）。
正史边界：write 只产草稿与状态变更提案（delta.json），commit 才写 canon.md 并推进 state。
图谱边界（M3A）：graph/ 是纯派生层——facts 不可变 append-only，遗漏只产警告与待审补丁文件，
图谱绝不写 state；graph/ 损坏不影响 commit/write/status，重抽即可恢复。
"""
import json
import time
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from src.harness.agents import build_writer_messages, WRITER_SYSTEM  # noqa: E402
from src.harness.config import load_config  # noqa: E402
from src.harness.context import SafeLedger, build_context  # noqa: E402
from src.harness import graph as gh  # noqa: E402
from src.harness.llm import make_client  # noqa: E402
from src.harness.schema import validate_card  # noqa: E402
from src.harness.state import OP_SPECS, StoryState, text_sha1  # noqa: E402
from src.harness.style_lint import lint_chapter  # noqa: E402

WS_ROOT = os.path.join(ROOT, "workspaces")
SCHEMA_VERSION = 4
ROLLING_WINDOW = 8       # 滚动纪律：planned_through - locked_through ≤ 8（不为远处写细纲）
PLAN_BATCH_DEFAULT = 4   # plan 默认提议章数
VOLUME_SIZE = 12         # 卷固定 12 章（工单示例 V1[1,12] / V2[13,24]）


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


def state_dir(book):
    return os.path.join(ws_dir(book), "state")


def state_path(book):
    return os.path.join(state_dir(book), "story-state.json")


def canon_file(book, ch):
    return os.path.join(chapter_dir(book, ch), "canon.md")


def revisions_dir(book, ch):
    return os.path.join(chapter_dir(book, ch), "revisions")


def rel_path(book, path):
    """workspace 内相对路径（正斜杠，入 bible 元数据用）。"""
    return os.path.relpath(path, ws_dir(book)).replace(os.sep, "/")


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- 人物 id（P3 四分区） ----------------

def char_id_map(bible):
    """name → id 映射（显示名 → 稳定引用键）。"""
    return {c["name"]: c["id"] for c in bible.get("characters", [])
            if isinstance(c, dict) and c.get("name") and c.get("id")}


def next_char_id(bible):
    nums = [int(m.group(1)) for c in bible.get("characters", [])
            if isinstance(c, dict) and (m := re.fullmatch(r"char_(\d+)", str(c.get("id", ""))))]
    return f"char_{max(nums, default=0) + 1:02d}"


def rewrite_card_char_ids(card, id_map):
    """把卡里的 pov.character / pressure[].char 从 name 归一为 id（原地改，返回是否改动）。"""
    changed = False
    pov = card.get("pov") or {}
    ref = pov.get("character")
    if ref in id_map:
        pov["character"] = id_map[ref]
        changed = True
    for p in (card.get("engine") or {}).get("pressure") or []:
        ref = p.get("char")
        if ref in id_map:
            p["char"] = id_map[ref]
            changed = True
    return changed


# ---------------- P0/P3：bible schema 迁移（v1 → v2 → v3） ----------------

def _migrate_to_v2(bible):
    """旧版（无 schema_version）→ v2：补默认字段，meta.cell 包装为 card。

    旧 cell 原样放进 card.engine（cell 自身的 chapter 键移到 card.chapter 层），
    meta.cell 保留——带 cell 的章节在 write/spec 路径走「旧格式直通」，行为与 v1 等价。
    """
    _ensure_defaults(bible)
    for ch, meta in (bible.get("chapters") or {}).items():
        if not isinstance(meta, dict) or not meta.get("cell") or meta.get("card"):
            continue
        cell = meta["cell"]
        # 深拷贝：包装卡与 cell 必须互不影响（后续 id 迁移只改卡，cell 保持 v1 原样）
        meta["card"] = {
            "chapter": int(ch),
            "engine": json.loads(json.dumps(
                {k: v for k, v in cell.items() if k != "chapter"})),
            "legacy": True,
        }
    bible["schema_version"] = 2


def _migrate_to_v3(bible, book=None):
    """M1 格式（v2）→ v3：人物四分区 + name→id 全线迁移。

    - characters[] 补 id（char_{NN} 按序生成）/anchors/voice.forbidden/voice.mes_example/
      knowledge_rules/lorebook 默认字段
    - meta.card 与 card.json 文件里的 pov.character / pressure[].char 从 name 改写为 id
    - M1 状态机 written → drafted（M2 起正史以 commit 为准）
    - book.context_projection 默认 false（= M1 行为）
    """
    (bible.get("book") or {}).setdefault("context_projection", False)
    id_map = {}
    used = {c.get("id") for c in bible.get("characters", [])
            if isinstance(c, dict) and c.get("id")}
    n = 1
    for c in bible.get("characters", []):
        if not isinstance(c, dict):
            continue
        if not c.get("id"):
            while f"char_{n:02d}" in used:
                n += 1
            c["id"] = f"char_{n:02d}"
            used.add(c["id"])
            n += 1
        if c.get("name"):
            id_map[c["name"]] = c["id"]
        c.setdefault("anchors", [])
        voice = c.setdefault("voice", {})
        voice.setdefault("forbidden", [])
        voice.setdefault("mes_example", [])
        c.setdefault("knowledge_rules", {"learn": [], "never_learn": []})
        c.setdefault("lorebook", [])
    for ch, meta in (bible.get("chapters") or {}).items():
        if not isinstance(meta, dict):
            continue
        if meta.get("status") == "written":
            meta["status"] = "drafted"
        card = meta.get("card")
        if card and id_map and rewrite_card_char_ids(card, id_map):
            cp = meta.get("card_path")
            if cp and not meta.get("cell"):  # 文件权威：card.json 同步改写（legacy 直通章不动文件）
                p = cp if os.path.isabs(cp) else os.path.join(ws_dir(book), cp)
                if os.path.exists(p):
                    _write_json(p, card)
    bible["schema_version"] = 3


def _ensure_volumes(arc):
    """卷初始化/补齐：V1 active 覆盖 1..min(total,12)，其余按 12 章 skeleton 顺延。

    已有 volumes 时增量扩展：覆盖不到 planned_through/total 的部分自动追加 skeleton 卷。
    """
    total = int(arc.get("total_chapters", 12) or 12)
    end = max(total, int(arc.get("planned_through", total) or total))
    if not arc.get("volumes"):
        arc["volumes"] = []
        start, vid = 1, 1
        while start <= end:
            arc["volumes"].append({"id": f"V{vid}", "status": "active" if vid == 1 else "skeleton",
                                   "chapters": [start, min(start + VOLUME_SIZE - 1, end)]})
            start += VOLUME_SIZE
            vid += 1
        return
    start = arc["volumes"][-1]["chapters"][1] + 1
    vid = len(arc["volumes"]) + 1
    while start <= end:
        arc["volumes"].append({"id": f"V{vid}", "status": "skeleton",
                               "chapters": [start, min(start + VOLUME_SIZE - 1, end)]})
        start += VOLUME_SIZE
        vid += 1


def _migrate_to_v4(bible, book=None):
    """M2 格式（v3）→ v4：arc 升级（volumes/compass 镜像/滚动纪律收敛）。

    - arc.compass：工单 v4 结构要求 compass 入 arc；顶层 bible.compass 保持权威
      （M1/M2 代码与既有数据都读它），v4 迁移时镜像一份进 arc.compass，两者由 save 同步
    - planned_through 收敛到滚动纪律：planned - locked ≤ 8（旧书 planned=total 的
      一次性收敛，plan 之后按纪律推进）
    - volumes[] 初始化（V1 active + 后续 skeleton）
    """
    arc = bible.setdefault("arc", {})
    locked = int(arc.get("locked_through", 0) or 0)
    planned = int(arc.get("planned_through", arc.get("total_chapters", 12)) or 12)
    if "compass" not in arc:
        arc["compass"] = json.loads(json.dumps(bible.get("compass") or {}))
    if planned - locked > ROLLING_WINDOW:
        arc["planned_through"] = locked + ROLLING_WINDOW
    _ensure_volumes(arc)
    bible["schema_version"] = 4


def _ensure_defaults(bible):
    """补 v2 起的默认字段（幂等，保存前防御性调用）。"""
    bible.setdefault("revision", 0)
    compass = bible.setdefault("compass", {"ending_direction": "", "reader_promise": "",
                                           "active_long_line_ids": []})
    arc = bible.setdefault("arc", {})
    arc.setdefault("locked_through", 0)
    total = int(arc.get("total_chapters", 12) or 12)
    # v4：planned 是「细纲前沿」，默认不超过滚动纪律窗口；compass 镜像进 arc（工单 v4 结构，
    # 顶层 bible.compass 为权威，每次保存刷新镜像）
    if "planned_through" not in arc:
        arc["planned_through"] = min(total, int(arc.get("locked_through", 0)) + ROLLING_WINDOW)
    arc["compass"] = dict(compass)
    _ensure_volumes(arc)
    bible.setdefault("shadows", [])


def migrate_bible(bible, book=None):
    """迁移到当前 schema：v1（无标记）→ v2 → v3 → v4，链式执行，幂等。"""
    ver = bible.get("schema_version")
    if ver == SCHEMA_VERSION:
        return bible
    if ver is None:
        _migrate_to_v2(bible)
    if bible.get("schema_version") == 2:
        _migrate_to_v3(bible, book)
    if bible.get("schema_version") == 3:
        _migrate_to_v4(bible, book)
    bible["schema_version"] = SCHEMA_VERSION
    return bible


def load_bible(book):
    with open(bible_path(book), encoding="utf-8") as f:
        bible = json.load(f)
    if bible.get("schema_version") != SCHEMA_VERSION:
        from_ver = bible.get("schema_version", "v1(无标记)")
        migrate_bible(bible, book)
        _write_json(bible_path(book), bible)  # 迁移结果立即落盘（一次性升级）
        print(f"migrated bible (from {from_ver}) to schema v{SCHEMA_VERSION}: {bible_path(book)}")
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
    # 每书模型覆盖：bible.book.writer_model / reader_model 优先（多书并行时各自指定）
    override_key = f"{role}_model"
    if bible.get("book", {}).get(override_key):
        role_cfg["model"] = bible["book"][override_key]
    if bible.get("book", {}).get("language") == "en":
        role_cfg["model"] = bible["book"].get(override_key, "gpt-5.6-terra")
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
            "context_projection": False,  # P4 投影开关：默认 false = M1 全文历史行为
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
                "locked_through": 0,
                "planned_through": min(total, ROLLING_WINDOW)},  # v4：细纲前沿受滚动纪律约束
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
        c = {"id": next_char_id(bible), "name": name}
        for key, prompt in CHAR_FIELDS:
            c[key] = input(f"{prompt}: ").strip() or None
        c = {k: v for k, v in c.items() if v}
        c["anchors"] = [x.strip() for x in
                        input("人格锚点（不可变，1-3 条，逗号分隔，可空）: ").split(",") if x.strip()]
        c["voice"] = {
            "catchphrases": [x.strip() for x in input("口头禅/标志行为（逗号分隔，可空）: ").split(",") if x.strip()],
            "speech_habits": [x.strip() for x in input("说话习惯（逗号分隔，可空）: ").split(",") if x.strip()],
            "forbidden": [x.strip() for x in input("禁说/禁止行为（逗号分隔，可空）: ").split(",") if x.strip()],
            "sample_line": input("一句代表性台词（可空）: ").strip() or None,
            "mes_example": _input_lines("完整对话样本（逐条输入，空行结束，建议 3-5 条）"),
        }
        c["voice"] = {k: v for k, v in c["voice"].items() if v}
        learn_raw = input("知识边界 learn（格式 fact_id:when，多条逗号分隔，可空）: ").strip()
        never_raw = input("知识边界 never_learn（fact_id，逗号分隔，可空）: ").strip()
        c["knowledge_rules"] = {
            "learn": [{"fact_id": p.split(":", 1)[0].strip(), "when": (p.split(":", 1) + [""])[1].strip()}
                      for p in learn_raw.split(",") if p.strip()],
            "never_learn": [x.strip() for x in never_raw.split(",") if x.strip()],
        }
        c["knowledge_rules"] = {k: v for k, v in c["knowledge_rules"].items() if v}
        lore_raw = input("lorebook（格式 fact_id:关键词1|关键词2:content_ref，多条逗号分隔，可空）: ").strip()
        c["lorebook"] = []
        for p in lore_raw.split(","):
            parts = [x.strip() for x in p.strip().split(":")]
            if p.strip() and len(parts) == 3:
                c["lorebook"].append({"fact_id": parts[0],
                                      "keywords": [k for k in parts[1].split("|") if k],
                                      "content_ref": parts[2]})
        if not c["lorebook"]:
            c.pop("lorebook")
        bible["characters"].append(c)
        save_bible(book, bible)
        print(f"人物已添加：{c.get('id')} = {name}")
    elif sub == "list":
        for c in bible["characters"]:
            print(f"- {c.get('id', '-')}（{c['name']}）：{c.get('card','')}")
            print(f"  want={c.get('want','-')} | fear={c.get('fear','-')}")
            kr = c.get("knowledge_rules") or {}
            if kr.get("never_learn"):
                print(f"  never_learn: {kr['never_learn']}")
            if c.get("voice", {}).get("catchphrases"):
                print(f"  口头禅: {c['voice']['catchphrases']}")
    else:
        print("用法: char <书名> add|list")


def _input_lines(prompt):
    """多行输入：逐条读取，空行结束。"""
    print(prompt + "（空行结束）")
    out = []
    while True:
        line = input("  > ").strip()
        if not line:
            return out
        out.append(line)


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
    '  "pov": {"character": "必须是人物 id", "tense": "past 或 present"},\n'
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
    '    "pressure": [{"char": "人物 id", "motive": "want|need|wound|value|fear|contradiction",\n'
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
    ref_desc = "、".join(f"{c.get('id', '?')}（{c['name']}）"
                         for c in bible["characters"] if isinstance(c, dict))
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
                f"Additional rules: chapter={ch}; pov.character and pressure[].char must be the "
                f"character ID (not the name), from: {ref_desc}; "
                f"engine.end_hook must be one of: new-information|dilemma|about-to-act|quiet-close; "
                f"reader_promise.type must be one of: info|emotion|event|visual; "
                f"dialogue_budget.min_ratio >= {min_ratio}; "
                f"allowed_fact_ids / active_hook_ids may only use these ledger ids: {ledger_ids or '[]'}.\n\n"
                f"Selected branch:\n{branch_txt}\n\nDiscussion:\n{dialogue}")
    else:
        head = (f"以下是第 {ch} 章的联合编剧讨论记录（可能附作者选定的分支）。把已达成的方向提炼为"
                f"一张完整章节卡，输出严格 JSON（不要任何其他文字）。字段规格：\n{spec}\n"
                f"附加规则：chapter={ch}；pov.character 与 pressure[].char 必须填人物 id（不要填名字），"
                f"可选：{ref_desc}；"
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
            rewrite_card_char_ids(card, char_id_map(bible))  # LLM 若填了名字，归一为 id
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


# ---------------- write：落笔（硬门禁 + draft/delta/lint 三件套） ----------------

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


def load_state(book, bible=None):
    st = StoryState(state_path(book))
    if bible:
        st.ensure_characters([c.get("id") for c in bible.get("characters", [])
                              if isinstance(c, dict) and c.get("id")])
    return st


def latest_draft(book, ch):
    """最新草稿：返回 (版本号如 'v001', 路径, 正文) 或 None（含旧格式 chNN.md 回退，版本号标 'legacy'）。"""
    d = drafts_dir(book, ch)
    if os.path.isdir(d):
        versions = sorted(f for f in os.listdir(d) if re.fullmatch(r"v\d+\.md", f))
        if versions:
            p = os.path.join(d, versions[-1])
            with open(p, encoding="utf-8") as f:
                return versions[-1][:-3], p, f.read()
    legacy = os.path.join(chapters_dir(book), f"ch{ch:02d}.md")
    if os.path.exists(legacy):
        with open(legacy, encoding="utf-8") as f:
            return "legacy", legacy, f.read()
    return None


def next_draft_no(drafts):
    nos = [int(m.group(1)) for f in os.listdir(drafts)
           if (m := re.fullmatch(r"v(\d+)\.md", f))]
    return max(nos, default=0) + 1


def prev_canon_texts(book, ch):
    """前文来源（正史截断核心）：只读第 1~N-1 章 canon.md，绝不读 drafts。

    迁移期回退：该章没有 canon 时回退最新 draft/旧 chNN.md 并标注来源
    （M1 格式工作区续写兼容，见 M2-CHANGES 决策 1）；投影模式下同样回退但显式标注。
    返回 (canon_texts: {ch: text}, prev_source: {ch: tag})。
    """
    canon_texts, prev_source = {}, {}
    for p in range(1, ch):
        cf = canon_file(book, p)
        if os.path.exists(cf):
            with open(cf, encoding="utf-8") as f:
                canon_texts[p] = f.read()
            prev_source[p] = "canon"
            continue
        ld = latest_draft(book, p)
        if ld:
            canon_texts[p] = ld[2]
            prev_source[p] = "draft(迁移回退)" if ld[0] != "legacy" else "chNN.md(旧格式回退)"
    return canon_texts, prev_source


DELTA_OPS_SPEC_ZH = (
    'op 白名单与格式（每条必带 evidence，且 evidence 必须是正文原文的连续子串，逐字复制）：\n'
    '- {"op": "learn", "character_id": "人物id", "fact_id": "事实/暗账id", "evidence": "…"}\n'
    '- {"op": "set_location", "character_id": "人物id", "value": "地点", "evidence": "…"}\n'
    '- {"op": "set_inventory", "character_id": "人物id", "value": "物品", "evidence": "…"}\n'
    '- {"op": "advance_hook", "hook_id": "暗账id", "action": "plant|develop|payoff", "evidence": "…"}\n'
    '- {"op": "add_relationship", "a": "人物id", "b": "人物id", "type": "关系", "evidence": "…"}\n'
    '- {"op": "set_false_belief", "character_id": "人物id", "value": "错误信念一句", "evidence": "…"}')


def _delta_prompt(bible, ch, version, draft_text, state_revision):
    ref_desc = "、".join(f"{c.get('id', '?')}（{c['name']}）"
                         for c in bible["characters"] if isinstance(c, dict))
    ledger_ids = [e["id"] for e in bible.get("ledger", [])]
    return (f"以下是刚写完的第 {ch} 章草稿（版本 {version}）。请提炼本章实际发生的状态变更提案，"
            f"输出严格 JSON（不要任何其他文字）：\n"
            f'{{"chapter": {ch}, "draft": "{version}", "base_state_revision": {state_revision}, '
            f'"ops": [...]}}\n\n{DELTA_OPS_SPEC_ZH}\n'
            f"规则：character_id 必须用人物 id（不要用名字），可选：{ref_desc}；"
            f"fact_id/hook_id 只能从这些暗账 id 里选：{ledger_ids or '[]'}；"
            f"只登记正文里确实发生的变更；没有就给空数组。\n\n正文：\n{draft_text}")


def _normalize_delta_ops(raw_ops, bible, draft_text):
    """write 侧 op 预清洗：name→id 改写、白名单/必填/evidence 校验，非法 op 丢弃并警告。"""
    id_by_name = char_id_map(bible)
    kept, dropped = [], []
    for i, op in enumerate(raw_ops if isinstance(raw_ops, list) else []):
        if not isinstance(op, dict):
            dropped.append(f"ops[{i}] 非对象")
            continue
        op = dict(op)
        name = op.get("op")
        if name not in OP_SPECS:
            dropped.append(f"ops[{i}] 非白名单 op：{name!r}")
            continue
        for key in ("character_id", "a", "b"):
            if op.get(key) in id_by_name:
                op[key] = id_by_name[op[key]]
        required, _ = OP_SPECS[name]
        missing = [f for f in required if not str(op.get(f) or "").strip()]
        if missing:
            dropped.append(f"ops[{i}] {name} 缺少必填字段 {missing}")
            continue
        if op.get("evidence") not in (draft_text or ""):
            dropped.append(f"ops[{i}] {name} 的 evidence 不是正文子串：『{str(op.get('evidence'))[:30]}…』")
            continue
        kept.append(op)
    return kept, dropped


def _derive_consequence(delta):
    """从 delta 的 ops 提炼一句正文实际结局（recorded_consequence 回填用）。"""
    parts = []
    for op in delta.get("ops", []):
        n = op.get("op")
        if n == "advance_hook":
            parts.append(f"钩子 {op['hook_id']} {op['action']}")
        elif n == "learn":
            parts.append(f"{op['character_id']} 获知 {op['fact_id']}")
        elif n == "set_location":
            parts.append(f"{op['character_id']} 行至 {op['value']}")
        elif n == "set_false_belief":
            parts.append(f"{op['character_id']} 误信：{op['value']}")
        elif n == "add_relationship":
            parts.append(f"{op['a']} → {op['b']}：{op['type']}")
        elif n == "set_inventory":
            parts.append(f"{op['character_id']} 物品变动：{op['value']}")
    return "；".join(parts) if parts else "（本章无状态变更）"


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

    # 同章并发写保护：锁文件 1 小时内视为有效（多书并行安全，同书同章互斥）
    lock_path = os.path.join(ws_dir(book), f".write-lock-ch{ch:02d}")
    if os.path.exists(lock_path) and (time.time() - os.path.getmtime(lock_path)) < 3600:
        print(f"警告：第 {ch} 章可能有另一个写入进程在跑（锁 {int(time.time() - os.path.getmtime(lock_path))} 秒前更新）。确认无并发后删除该锁文件重试。")
        sys.exit(1)
    open(lock_path, "w").close()

    spec = bible_to_spec(book, bible)
    state = load_state(book, bible)
    client = client_for(bible, "writer", book)
    lang = spec.get("language", "zh")
    projection = bool((bible.get("book") or {}).get("context_projection"))
    id_name_map = {c["id"]: c["name"] for c in bible.get("characters", [])
                   if isinstance(c, dict) and c.get("id") and c.get("name")}

    # 前文：只读 canon（P2 正史截断核心），迁移期无 canon 才回退 draft 并标注
    canon_texts, prev_source = prev_canon_texts(book, ch)
    if projection:
        # P4：HOT/WARM/COLD 投影（shadows/COLD 绝不注入）
        config = {"id_name_map": id_name_map, "canon_texts": canon_texts,
                  "prev_source": prev_source, "card": None if source == "legacy" else card}
        ctx = build_context(bible, state, spec, ch, config)
        msgs = [{"role": "system", "content": WRITER_SYSTEM[lang]},
                {"role": "user", "content": "\n\n".join(ctx["hot"] + ctx["warm"])}]
    else:
        # 投影关：M1 全文历史行为（前文来源已切到 canon 优先，见决策 1）
        prev = [canon_texts[p] for p in sorted(canon_texts)]
        msgs = build_writer_messages("E", spec, SafeLedger(spec), prev, ch)
        if id_name_map:
            msgs[1]["content"] += ("\n\n人物 id 对照（状态提案/章节卡里的 char 引用用 id）："
                                   + "，".join(f"{cid}={name}" for cid, name in id_name_map.items()))

    print(f"writing chapter {ch} ...")
    text = client.chat(msgs, tag=f"wb-ch{ch:02d}")

    # lint 存档（P6 豁免的正文 hash 绑定此文件）
    lint = lint_chapter(text, lang)
    kept_flags, exempted_flags = state.filter_flags(lint["flags"], ch, text_sha1(text))
    report = kept_flags or ["clean"]
    if exempted_flags:
        report.append(f"（{len(exempted_flags)} 项已豁免：{'、'.join(exempted_flags)}）")
    print("lint flags:", report)

    drafts = drafts_dir(book, ch)
    os.makedirs(drafts, exist_ok=True)
    version = f"v{next_draft_no(drafts):03d}"
    draft_path = os.path.join(drafts, f"{version}.md")
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(text)
    if os.path.exists(lock_path):
        os.remove(lock_path)
    lint_path = os.path.join(drafts, f"{version}.lint.json")
    _write_json(lint_path, {
        "chapter": ch, "draft": version, "flags": lint["flags"],
        "checks": lint.get("checks", {}), "evidence": lint.get("evidence", {}),
        "source_text_sha1": text_sha1(text),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    })

    # 状态变更提案（STATE_DELTA）：单独一次 LLM 调用，op 预清洗后落盘
    print("提炼状态变更提案（delta）...")
    delta_raw = client.chat([{"role": "user", "content": _delta_prompt(
        bible, ch, version, text, state.revision)}], tag=f"delta-ch{ch:02d}")
    try:
        delta = _extract_json(delta_raw, "object")
    except ValueError:
        delta = {}
        print("[delta] 提案解析失败，落盘空 delta（可手工补 ops 后 commit）")
    kept_ops, dropped_ops = _normalize_delta_ops(delta.get("ops"), bible, text)
    for d in dropped_ops:
        print(f"[delta] 丢弃 op：{d}")
    delta = {"chapter": ch, "draft": version, "base_state_revision": state.revision, "ops": kept_ops}
    delta_path = os.path.join(drafts, f"{version}.delta.json")
    _write_json(delta_path, delta)
    # never_learn 冲突在 commit 时硬拒绝；写阶段只提前提示
    kr = {c.get("id"): (c.get("knowledge_rules") or {}) for c in bible.get("characters", [])
          if isinstance(c, dict) and c.get("id")}
    for op in kept_ops:
        c = op.get("op") == "learn" and kr.get(op.get("character_id")) or None
        if c and op.get("fact_id") in (c.get("never_learn") or []):
            print(f"[delta] 警告：learn {op['fact_id']} 与 {op['character_id']} 的 never_learn 冲突，commit 将硬拒绝")

    bible["chapters"][str(ch)]["status"] = "drafted"
    save_bible(book, bible)
    print(f"\n落笔完成：{draft_path}（{len(text)} chars）")
    print(f"状态提案：{delta_path}（base_state_revision={state.revision}，{len(kept_ops)} ops）")
    print(f"lint 存档：{lint_path}")
    ledger_entries = SafeLedger(spec).entries
    if lang == "zh":
        print(f"金丝雀检查：{[e['canary'] for e in ledger_entries if e['canary'] in text and ch < e['reveal_chapter'] and ch != e['plant_chapter']] or '无泄漏'}")
    print(f"下一步：python workbench.py commit {book} {ch}")


# ---------------- commit：人工提交正史（P2） ----------------

def cmd_commit(args):
    book, ch = args[0], int(args[1])
    revised = None
    if "--revised" in args:
        i = args.index("--revised")
        if i + 1 >= len(args):
            print("--revised 需要文件参数。")
            sys.exit(1)
        revised = args[i + 1]

    bible = load_bible(book)
    meta = bible["chapters"].get(str(ch)) or {}
    card, source = load_card(book, ch, meta)
    ld = latest_draft(book, ch)
    if not ld:
        print("该章没有草稿。先 write。")
        sys.exit(1)
    version, draft_path, draft_text = ld
    delta_path = os.path.join(drafts_dir(book, ch), f"{version}.delta.json")
    if not os.path.exists(delta_path):
        print(f"缺少状态提案：{delta_path}（write 生成，或手工补该文件后重跑）")
        sys.exit(1)
    with open(delta_path, encoding="utf-8") as f:
        delta = json.load(f)
    if revised:
        with open(revised, encoding="utf-8") as f:
            draft_text = f.read()  # evidence 校验同时针对修订版
        print(f"使用修订版作为 canon 内容：{revised}")

    state = load_state(book, bible)
    knowledge_rules = {c["id"]: (c.get("knowledge_rules") or {})
                       for c in bible.get("characters", [])
                       if isinstance(c, dict) and c.get("id")}
    violations = state.validate_delta(delta, draft_text, knowledge_rules)
    if violations:
        print("commit 拒绝：delta 校验未通过（可手工修 delta.json 后重跑）。违规清单：")
        for x in violations:
            print(f"  - {x}")
        sys.exit(1)

    ops = delta.get("ops", [])
    print(f"将推进的状态变更（{len(ops)} ops，state.revision {state.revision} → {state.revision + 1}）：")
    for op in ops:
        print(f"  - {op.get('op')}: {json.dumps({k: v for k, v in op.items() if k != 'evidence'}, ensure_ascii=False)}")
    derived = _derive_consequence(delta)
    print(f"recorded_consequence 提炼：{derived}")
    ok = input("确认提交正史？(y=确认 / 其他=放弃): ").strip().lower()
    if ok != "y":
        print("放弃（草稿与 delta 保留，state 未推进）。")
        return
    rc = input("recorded_consequence 回填（回车=采用上面提炼句）: ").strip() or derived

    os.makedirs(revisions_dir(book, ch), exist_ok=True)  # M3 修订历史目录约定
    canon_path = canon_file(book, ch)
    if os.path.exists(canon_path):
        print(f"警告：canon.md 已存在，将被覆盖：{canon_path}")
    with open(canon_path, "w", encoding="utf-8") as f:
        f.write(draft_text)

    prev_revision = state.revision
    violations = state.commit_delta(delta, draft_text, knowledge_rules)
    if violations:  # 理论不可达（上面已校验）；防御
        print("commit 失败（state 未推进）：")
        for x in violations:
            print(f"  - {x}")
        sys.exit(1)
    # M3A：commit = 锁定事件（含旧格式直通章），推进 locked_through 供滚动规划判界
    arc = bible.setdefault("arc", {})
    arc["locked_through"] = max(int(arc.get("locked_through", 0) or 0), ch)

    if card is not None and source != "legacy":
        card["recorded_consequence"] = rc
        cp = meta.get("card_path")
        if cp:
            p = cp if os.path.isabs(cp) else os.path.join(ws_dir(book), cp)
            if os.path.exists(p):
                _write_json(p, card)
        meta["card"] = card
    else:
        print("（旧格式直通章：无章节卡，跳过 recorded_consequence 回填）")
    meta["status"] = "committed"
    save_bible(book, bible)
    print(f"\n正史已提交：{canon_path}")
    print(f"state 已推进：revision={state.revision}，as_of_chapter={state.data['as_of_chapter']}，"
          f"备份=state/story-state.json.bak-{prev_revision}")
    print(f"recorded_consequence 已回填：{rc}")
    print(f"arc.locked_through 推进至 {arc['locked_through']}")

    # P-G1：commit 成功后自动抽取章级事实（图谱是派生层，任何失败只警告不阻塞）
    try:
        run_fact_extraction(book, bible, ch, draft_text, delta, state.revision)
    except Exception as e:  # noqa: BLE001
        print(f"[graph] 警告：事实抽取失败（不阻塞 commit，可重抽恢复）：{type(e).__name__}: {e}")


# ---------------- exempt：豁免即状态（P6） ----------------

def cmd_exempt(args):
    if len(args) < 3:
        print("用法: exempt <书名> <章号> <规则> <理由>")
        sys.exit(1)
    book, ch, rule = args[0], int(args[1]), args[2]
    reason = args[3] if len(args) > 3 else ""
    ld = latest_draft(book, ch)
    if not ld:
        print("该章没有草稿。先 write。")
        sys.exit(1)
    version = ld[0]
    lint_path = os.path.join(drafts_dir(book, ch), f"{version}.lint.json")
    if not os.path.exists(lint_path):
        print(f"该章最近没有 lint 存档：{lint_path}（先 write）")
        sys.exit(1)
    with open(lint_path, encoding="utf-8") as f:
        lint = json.load(f)
    flags = lint.get("flags") or []
    state = StoryState(state_path(book))
    matched = [f for f in flags if state._rule_short(f) == state._rule_short(rule)]
    if not matched:
        print(f"最近 lint 没有规则「{rule}」的 finding。现有 flags：{flags or ['clean']}")
        sys.exit(1)
    ex = state.add_exemption(rule, ch, lint.get("source_text_sha1", ""), reason)
    state.save()
    print(f"豁免已登记：{ex['id']} rule={rule} scope=ch{ch}")
    print(f"fingerprint={ex['fingerprint']}（绑定正文 hash，正文变化后自动失效）")


# ---------------- plan：滚动规划（P7s） ----------------

def _canon_summaries_for_plan(book, bible, max_full=6):
    """committed 章节的 canon 摘要：最近 max_full 章给尾部摘要，更早的只给弧线标签。"""
    labels, recent = [], []
    for k, meta in sorted(bible["chapters"].items(), key=lambda kv: int(kv[0])):
        if meta.get("status") != "committed":
            continue
        ch = int(k)
        card, _ = load_card(book, ch, meta)
        label = (card or {}).get("engine", {}).get("arc_label", "")
        labels.append(f"第{ch}章：{label}" if label else f"第{ch}章")
        recent.append(ch)
    summaries = []
    for ch in recent[-max_full:]:
        cf = canon_file(book, ch)
        text = ""
        if os.path.exists(cf):
            with open(cf, encoding="utf-8") as f:
                text = f.read().strip()
        summaries.append(f"【第{ch}章 结尾】…{text[-200:]}" if len(text) > 200
                         else f"【第{ch}章】{text}")
    return "\n".join(labels), "\n\n".join(summaries)


def _open_hooks_for_plan(bible, book):
    lines = []
    for e in bible.get("ledger", []):
        lines.append(f"- [{e['id']}] 第{e['plant_chapter']}章埋设、第{e['reveal_chapter']}章回收：{e.get('hook', '')}")
    sp = state_path(book)
    if os.path.exists(sp):
        st = StoryState(sp)
        for hid, h in (st.data.get("hooks") or {}).items():
            if h.get("status") != "payoff":
                lines.append(f"- [{hid}] state 状态 {h.get('status')}（第{h.get('chapter')}章）")
    return "\n".join(lines) or "（无未闭合钩子）"


def _plan_prompt(bible, arc, start, n, labels_line, summaries, hooks_line):
    compass = bible.get("compass") or {}
    existing = "\n".join(map(str, arc.get("anchors", [])[-8:])) or "（无）"
    return (
        f"你是这部连载的联合编剧。全书 {arc.get('total_chapters', 12)} 章，弧线模板：{arc.get('template')}。\n"
        f"终局方向：{compass.get('ending_direction', '')}｜读者核心承诺：{compass.get('reader_promise', '')}\n"
        f"已有弧线锚点（最近）：\n{existing}\n"
        f"已提交正文章节：\n{labels_line or '（暂无）'}\n"
        f"最近正文章节结尾：\n{summaries or '（暂无）'}\n"
        f"未闭合钩子：\n{hooks_line}\n\n"
        f"请为第 {start}~{start + n - 1} 章提议锚点（滚动规划：只看这一批，不为更远处写细纲）。"
        f"严格输出 JSON 数组（不要任何其他文字），每章一条：\n"
        f'[{{"chapter": {start}, "arc_label": "弧线位置标签", '
        f'"amplitude": "XL|L|M|S|B", "direction": "本章一句话方向"}}]\n'
        f"规则：锚点要与已有锚点/正文章节连续推进，服务终局方向与读者承诺；"
        f"amplitude 按张力节奏分配（呼吸拍 B 不可少）；钩子该回收的章要安排回收。")


def cmd_plan(args):
    book = args[0]
    extend_n = None
    if "--extend" in args:
        i = args.index("--extend")
        if i + 1 >= len(args):
            print("--extend 需要章数参数，如 --extend 4")
            sys.exit(1)
        extend_n = int(args[i + 1])

    bible = load_bible(book)
    arc = bible["arc"]
    total = int(arc.get("total_chapters", 12) or 12)
    locked = int(arc.get("locked_through", 0) or 0)
    planned = int(arc.get("planned_through", 0) or 0)

    # 条件：规划耗尽（planned == locked）或显式 --extend N
    if planned > locked and extend_n is None:
        print(f"规划未耗尽：planned_through={planned} > locked_through={locked}。"
              f"滚动纪律下不为远处写细纲；确需提前展开用 --extend N。")
        sys.exit(1)

    # 写超前于规划（locked > planned，作者直写未 plan）时，从正史前沿之后展开
    start = max(planned, locked) + 1
    n = extend_n if extend_n is not None else PLAN_BATCH_DEFAULT
    # 滚动纪律：planned - locked ≤ 8，超出部分截断（打印警告，不打断作者）
    cap = locked + ROLLING_WINDOW
    if start + n - 1 > cap:
        n_eff = max(0, cap - start + 1)
        print(f"[plan] 滚动纪律：planned_through 不得超过 locked_through+{ROLLING_WINDOW}"
              f"（={cap}）。本批从 {start} 截断为 {n_eff} 章。")
        n = n_eff
    if n <= 0:
        print(f"已到滚动纪律上限（planned={planned}，locked={locked}）。先推进 locked 再 plan。")
        sys.exit(1)
    if start + n - 1 > total:
        n = max(0, total - start + 1)
        if n <= 0:
            print(f"已达全书规划章数（total={total}）。如需延长全书请调整 arc.total_chapters。")
            sys.exit(1)

    # 素材：canon 摘要 + compass + 未闭合 hook + 弧位置
    labels_line, summaries = _canon_summaries_for_plan(book, bible)
    hooks_line = _open_hooks_for_plan(bible, book)
    prompt = _plan_prompt(bible, arc, start, n, labels_line, summaries, hooks_line)

    client = client_for(bible, "writer", book)  # 锚点提议用主力 writer 模型
    raw = client.chat([{"role": "user", "content": prompt}], tag=f"plan-{start:02d}-{n:02d}")
    try:
        anchors = _extract_json(raw, "array")
    except ValueError:
        print("锚点提议解析失败（非 JSON 数组）：", raw[:200])
        sys.exit(1)
    if not isinstance(anchors, list) or not anchors:
        print("锚点提议为空。")
        sys.exit(1)

    # 作者逐条确认或修改
    print(f"\n=== 滚动规划：第 {start}~{start + len(anchors) - 1} 章锚点提议 ===")
    confirmed = []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        ch_no = int(a.get("chapter") or (start + len(confirmed)))
        label = str(a.get("arc_label") or "").strip() or "未命名锚点"
        amp = str(a.get("amplitude") or "M").strip().upper()
        if amp not in ("XL", "L", "M", "S", "B"):
            print(f"  [plan] 第{ch_no}章 amplitude {amp!r} 不在枚举，按 M 处理")
            amp = "M"
        direction = str(a.get("direction") or "").strip()
        print(f"\n第{ch_no}章 [{amp}] {label}\n  方向：{direction}")
        ans = input("确认？(y=确认 / 直接输入修改后的一句方向 / s=跳过): ").strip()
        if ans.lower() == "s":
            print("  跳过。")
            continue
        if ans and ans.lower() != "y":
            direction = ans  # 作者口述修改
        confirmed.append({"chapter": ch_no, "arc_label": label, "amplitude": amp,
                          "direction": direction})
    if not confirmed:
        print("没有确认任何锚点，planned_through 不推进。")
        return
    # 防线：即使 LLM/作者多给了锚点，planned 也绝不越过纪律窗口
    dropped = [a for a in confirmed if a["chapter"] > cap]
    if dropped:
        print(f"[plan] 滚动纪律：丢弃超出 locked+{ROLLING_WINDOW} 的锚点："
              + "、".join(f"第{a['chapter']}章" for a in dropped))
        confirmed = [a for a in confirmed if a["chapter"] <= cap]
        if not confirmed:
            print("没有窗口内的锚点，planned_through 不推进。")
            return

    # 写入 arc.anchors + 推进 planned_through + 卷边界处理
    new_planned = planned
    for a in confirmed:
        tag = f"{a['arc_label']}@第{a['chapter']}章（{a['amplitude']}）｜{a['direction']}"
        if tag not in arc["anchors"]:
            arc["anchors"].append(tag)
        new_planned = max(new_planned, a["chapter"])
    arc["planned_through"] = max(planned, new_planned)
    _ensure_volumes(arc)
    for v in arc.get("volumes", []):  # 新规划落入的 skeleton 卷转 active
        vs, ve = v.get("chapters", [0, 0])
        if v.get("status") == "skeleton" and vs <= arc["planned_through"] and ve >= start:
            v["status"] = "active"
    save_bible(book, bible)
    print(f"\n规划完成：planned_through {planned} → {arc['planned_through']}"
          f"（locked={locked}，窗口 {arc['planned_through'] - locked}/{ROLLING_WINDOW}）")
    print(f"新增锚点 {len(confirmed)} 条；卷状态："
          + "，".join(f"{v['id']}[{v['chapters'][0]}-{v['chapters'][1]}]{v['status']}"
                      for v in arc.get("volumes", [])))
    print(f"下一步：python workbench.py discuss {book} <新章号>")


# ---------------- map：最小地图（P-G2） ----------------

def cmd_map(args):
    book = args[0]
    as_of = None
    if "--as-of" in args:
        i = args.index("--as-of")
        if i + 1 >= len(args):
            print("--as-of 需要章号参数")
            sys.exit(1)
        as_of = int(args[i + 1])
    bible = load_bible(book)  # 旧格式自动迁移（图谱只读 bible，不改 state）
    facts = gh.load_all_latest_facts(ws_dir(book), as_of=as_of)
    g = gh.replay_graph(bible, facts, as_of=as_of)

    out_dir = gh.graph_dir(ws_dir(book))
    os.makedirs(out_dir, exist_ok=True)
    graph_path = os.path.join(out_dir, "graph.json")
    meta = dict(g["meta"])
    meta.update({"book": book, "title": bible["book"].get("title", book),
                 "source": "graph/facts/* 重放（派生投影，非第二正史）"})
    g_out = {"meta": meta, "nodes": g["nodes"], "edges": g["edges"]}
    _write_json(graph_path, g_out)

    vendor = gh.vendor_js_text(ROOT)
    mode = "cytoscape(vendor)" if vendor else "mermaid(降级)"
    html = gh.render_map_html(g_out, meta["title"], vendor_js=vendor)
    html_path = os.path.join(out_dir, "map.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"地图已生成（{mode}）：")
    print(f"  {graph_path}（nodes={len(g['nodes'])}, edges={len(g['edges'])}"
          f", chapters={g['meta']['chapters'] or '[]'}）")
    print(f"  {html_path}")
    if as_of is not None:
        print(f"  as-of 第{as_of}章时刻")


# ---------------- 事实抽取：commit 后自动触发（P-G1，失败不阻塞） ----------------

def extraction_client_for(bible, book):
    """抽取客户端：qwen3.8-flash（reader 通道，与 writer 异构）；bible.book.extraction_model 可覆盖。"""
    client = client_for(bible, "reader", book)
    override = (bible.get("book") or {}).get("extraction_model")
    if override and hasattr(client, "model"):
        client.model = override
    return client


def run_fact_extraction(book, bible, ch, canon_text, delta, state_revision):
    """抽取 + 保存 + 遗漏检测。抛异常由调用方捕获（不阻塞 commit）。"""
    client = extraction_client_for(bible, book)
    model = getattr(client, "model", "?")
    raw = client.chat([{"role": "user", "content": gh.build_extraction_prompt(
        bible, ch, canon_text, state_revision, delta.get("draft", "?"))}],
        tag=f"fact-ch{ch:02d}")
    fact_raw = _extract_json(raw, "object")
    fact, warnings = gh.normalize_fact(fact_raw, bible, canon_text, ch, state_revision, model)
    for w in warnings:
        print(f"[graph] 警告：{w}")
    path, entry = gh.save_fact(ws_dir(book), fact)
    print(f"[graph] 事实已抽取：{path}（版本 {len(entry['versions'])}，"
          f"events={len(fact['events'])}, state_changes={len(fact['state_changes_observed'])}）")
    # 遗漏检测：正文观察到、delta 未登记 → 警告 + 待审补丁文件（绝不改 state）
    omissions = gh.detect_omissions(fact, delta)
    if omissions:
        opath = gh.save_omissions(ws_dir(book), ch, omissions, delta.get("draft", "?"))
        print(f"[graph] 遗漏警告：{len(omissions)} 项状态变化在 delta 中无对应 op → {opath}")
        for o in omissions:
            print(f"  - {o['character_id']}.{o['kind']}：{o.get('value', '')}"
                  f"（建议 op：{json.dumps(o['suggested_op'], ensure_ascii=False)[:120]}）")
    return fact


# ---------------- status ----------------

def cmd_status(args):
    book = args[0]
    bible = load_bible(book)  # 旧格式自动迁移
    total = bible["arc"].get("total_chapters", 12)
    print(f"《{bible['book']['title']}》 {bible['book'].get('genre')} | {bible['book'].get('platform')} | {bible['book'].get('language')}")
    print(f"人物 {len(bible['characters'])} | 暗账 {len(bible.get('ledger', []))} 条 | 弧线 {bible['arc'].get('template')}"
          f" | 投影={'开' if (bible.get('book') or {}).get('context_projection') else '关'}")
    compass = bible.get("compass") or {}
    if compass.get("ending_direction") or compass.get("reader_promise"):
        print(f"终局方向：{compass.get('ending_direction') or '-'} | 读者承诺：{compass.get('reader_promise') or '-'}")
    print(f"进度：locked_through={bible['arc'].get('locked_through', 0)}"
          f" / planned_through={bible['arc'].get('planned_through', '-')} / revision={bible.get('revision', 0)}")
    if os.path.exists(state_path(book)):
        st = StoryState(state_path(book))
        print(f"正史：state.revision={st.revision} / as_of_chapter={st.data.get('as_of_chapter', 0)}"
              f" / 豁免 {len(st.data.get('exemptions', []))} 条")
    marks = {"empty": "·", "branching": "◦", "discussed": "◇", "locked": "◆",
             "drafted": "▧", "committed": "★"}
    for ch in range(1, total + 1):
        meta = bible["chapters"].get(str(ch)) or {}
        status = meta.get("status", "empty")
        mark = marks.get(status, "?")
        card, source = load_card(book, ch, meta)
        eng = (card or {}).get("engine") or {}
        extra = " (旧cell)" if source == "legacy" else ""
        print(f"  {mark} 第{ch:>2}章 [{status:<9}] {eng.get('arc_label', '')} {eng.get('amplitude', '')}"
              f" {(eng.get('plan', '') or '')[:30]}{extra}")


def cmd_books(args):
    """多书总览：列出所有 workspace 的进度。"""
    import time as _t
    if not os.path.isdir(WS_ROOT):
        print("尚无 workspace。先用 new 建书。")
        return
    rows = []
    for name in sorted(os.listdir(WS_ROOT)):
        bp = bible_path(name)
        if not os.path.isfile(bp):
            continue
        try:
            b = json.load(open(bp, encoding="utf-8"))
        except json.JSONDecodeError:
            rows.append((name, "?", "?", "bible 损坏", 0, 0, 0))
            continue
        chs = b.get("chapters", {})
        written = sum(1 for m in chs.values() if m.get("status") in ("written", "drafted", "committed"))
        locked = sum(1 for m in chs.values() if m.get("status") == "locked")
        total = b.get("arc", {}).get("total_chapters", 0)
        lang = b.get("book", {}).get("language", "zh")
        model = b.get("book", {}).get("writer_model") or ("gpt-5.6-terra" if lang == "en" else "glm-5.3-flash")
        rows.append((name, b.get("book", {}).get("title", ""), lang, model, written, locked, total))
    print(f"{'书名':<18} {'标题':<14} {'语':<3} {'writer模型':<16} {'已写':>4} {'已锁':>4} /{'规划':>4}")
    for name, title, lang, model, w, l, t in rows:
        print(f"{name:<18} {title:<14} {lang:<3} {model:<16} {w:>4} {l:>4} /{t:>4}")
    # 活跃写锁提示
    import glob as _g
    locks = _g.glob(os.path.join(WS_ROOT, "*", ".write-lock-*"))
    for lk in locks:
        age = int(_t.time() - os.path.getmtime(lk))
        if age < 3600:
            print(f"  [活跃写锁] {lk}  ({age}s)")



def main():
    cmds = {"new": cmd_new, "char": cmd_char, "discuss": cmd_discuss,
            "lock": cmd_lock, "write": cmd_write, "commit": cmd_commit,
            "plan": cmd_plan, "map": cmd_map,
            "exempt": cmd_exempt, "books": cmd_books, "status": cmd_status}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        return
    if sys.argv[1] not in ("new", "books") and len(sys.argv) < 3:
        print("缺书名参数。示例：python workbench.py status <书名>")
        return
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
