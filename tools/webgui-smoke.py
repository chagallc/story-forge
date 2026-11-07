#!/usr/bin/env python3
"""WebGUI 冒烟测试（WebGUI-workorder 验收 #2/#4/#5）：urllib 直打 API 全链路。

启动真实服务进程（--port 17891，默认端口 17890 留给人工浏览器冒烟）：
  0. 服务启动 + 仅回环绑定断言（stdout 声明 127.0.0.1）+ 首页可达
  1. 路径穿越攻击样本（http.client 原始请求行，不经客户端归一化）→ 一律 400/404 且 body 含 error
     （覆盖 workorder 指定样本 name=../main；另含 %2e%2e、反斜杠、char/章号段穿越、坏名 body 注入、
      Windows 保留名 con）
  2. 全链路（真实 LLM）：建书 → 建人物（含坏样本被拒）→ 章节列表 → 讨论三阶段
     （分支生成 → 选分支 → chat 一轮）→ 锁卡（坏卡被拒返回违规清单 → 确认落盘）→
     write 同章并发二连发（第二个被写锁拒绝 423）→ commit（ops 预览 → 确认；never_learn
     冲突自动修 delta 重跑，同 CLI smoke 的 flaky 防护）→ 重复 commit 被拒 → canon 读取
  3. 幂等/负样本：建书重名 409、exempt 无 finding 被拒、非白名单 discuss 动作 400

依赖：experiments/exp003 + config/models.local.json；真实 LLM 约 5 次调用（分支1+开场1+对话1+卡1+写作2，其中
写作2次在 write 内部）。
"""
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ → 仓库根
sys.path.insert(0, ROOT)

import workbench as wb  # noqa: E402
from src.harness.state import StoryState  # noqa: E402

PORT = 17891
BOOK = "webgui-smoke"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
RESULTS = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    RESULTS.append(cond)
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail and not cond else ""))
    return cond


# ---------------- HTTP 工具 ----------------

def req(method, path, body=None, timeout=900):
    """urllib 直打：返回 (status, json_or_None)。非 2xx 不抛异常由调用方断言。"""
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = {"_raw": raw.decode("utf-8", errors="replace")}
    return status, parsed


def raw_req(method, path, body=None):
    """http.client 原样发送请求行（客户端不做点段归一化），专测路径穿越。"""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
    try:
        conn.request(method, path, body=(json.dumps(body).encode() if body else None),
                     headers={"Content-Type": "application/json"} if body else {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def wait_server(sec=30):
    dl = time.time() + sec
    while time.time() < dl:
        try:
            st, _ = req("GET", "/api/books", timeout=3)
            if st == 200:
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


# ---------------- 服务生命周期 ----------------

def start_server():
    proc = subprocess.Popen([sys.executable, "workbench-web.py", "--port", str(PORT)],
                            cwd=ROOT, env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    # 常驻排水线程：服务端每个请求/save_bible 都会写 stdout/stderr，若无人消费，
    # 管道缓冲填满后服务端 print 阻塞 → 后续请求全部挂死（实测卡在重复删除 409 前）。
    lines = []

    def _drain():
        for line in proc.stdout:
            lines.append(line.rstrip())
            if len(lines) > 500:
                del lines[:300]  # 只留尾部，防内存膨胀

    import threading as _th
    t = _th.Thread(target=_drain, daemon=True)
    t.start()
    dl = time.time() + 20
    while time.time() < dl:
        if any("127.0.0.1" in x for x in lines):
            break
        time.sleep(0.3)
    return proc, lines


# ---------------- 主流程 ----------------

def main():
    print(f"=== webgui smoke ROOT={ROOT} PORT={PORT} ===")
    proc, lines = start_server()
    try:
        ok = wait_server()
        check("服务启动且 /api/books 可达", ok, "; ".join(lines))
        check("启动声明仅回环绑定（stdout 含 127.0.0.1）",
              any("127.0.0.1" in x for x in lines), "; ".join(lines))
        if not ok:
            return finish()

        # ============ 1. 首页 ============
        st, body = req("GET", "/")
        html = (body or {}).get("_raw", "") if isinstance(body, dict) else ""
        raw2 = raw_req("GET", "/")[1]
        html2 = raw2.decode("utf-8", errors="replace")
        check("GET / 返回 HTML（五屏前端单文件）",
              st == 200 and "<html" in html and "story" in html2.lower())
        check("前端零外部依赖（无 http(s):// 外链 / 无 CDN / 无 src= 外部脚本）",
              not re.search(r"(src|href)\s*=\s*[\"']https?://", html2)
              and not re.search(r"//cdn\.|unpkg|jsdelivr", html2))

        # ============ 2. 路径穿越攻击样本 ============
        samples = [
            "/api/book/../main",                                   # workorder 指定样本
            "/api/book/%2e%2e/main",
            "/api/book/..%5Cmain",
            "/api/book/smoke-wb/char/..%2f..%2f..%2fstory-bible.json",
            "/api/book/smoke-wb/../../../workbench.py",
            f"/api/book/{BOOK}%2F..%2F..%2Fmain",
            "/api/book/..",
            "/api/book/C:\\Windows\\system32",
        ]
        for s in samples:
            st, raw = raw_req("GET", s)
            okk = st in (400, 404) and b"error" in raw
            check(f"穿越样本被拒 {s[:56]}", okk, f"status={st} body={raw[:90]!r}")
        for name in ["../evil", "..", "a/b", "with space", "con", "", "a" * 80, "a/b/c"]:
            st, body = req("POST", "/api/books", {"name": name})
            check(f"建书坏名被拒 name={name!r:.30}", st == 400 and body and "error" in body,
                  f"status={st} body={body}")

        # ============ 3. 建书 ============
        st, body = req("GET", "/api/books")
        check("GET /api/books 含既有书", st == 200 and any(
            b["name"].startswith("smoke-wb") for b in body.get("books", [])))
        if os.path.isdir(wb.ws_dir(BOOK)):
            shutil.rmtree(wb.ws_dir(BOOK))  # 清理上次运行（smoke 可重复跑）
        st, body = req("POST", "/api/books", {
            "name": BOOK, "title": "雾锁九门（WebGUI 冒烟）", "genre": "都市悬疑",
            "language": "zh", "platform": "qidian",
            "logline": "典当行学徒发现每件死当品里都住着一个未完成的执念，而最新的一件，是他失踪师父的怀表。",
            "setting": "九十年代末，某南方城市的老九门典当行街",
            "template": "悬疑假设弧", "total_chapters": 6,
            "ending_direction": "真相埋在三十年前师父学徒的旧铺号",
            "reader_promise": "每章都有一次计划被推翻的爽感"})
        check("POST /api/books 建书成功", st == 200 and body.get("ok") is True, str(body))
        st, body = req("POST", "/api/books", {"name": BOOK, "title": "重复"})
        check("重复建书 409", st == 409 and "已存在" in (body or {}).get("error", ""), str(body))

        # ============ 4. 建人物（含坏样本） ============
        CHAR = {
            "name": "陆小满", "card": "24岁，九门典当行学徒，眼力毒，嘴更快。",
            "anchors": ["守规矩", "重师徒"],
            "want": "赎回师父留下的怀表，弄清他失踪那晚去了哪",
            "need": "承认师父可能自己有秘密，而非只有受害者叙事",
            "wound": "孤儿，师父是唯一给过他姓氏的人",
            "value": "当铺规矩：死当不问来路——但他今天想破例",
            "fear": "师父是自愿消失的，根本没打算带上他",
            "contradiction": "守规矩的学徒要做一行里最破规矩的事",
            "voice": {"catchphrases": ["按规矩说", "这物件不干净"],
                      "speech_habits": ["短句"], "forbidden": ["不说完整性解释句"],
                      "sample_line": "按规矩说，死当不问来路。",
                      "mes_example": ["「按规矩说，死当不问来路。」陆小满把当票推回去。"]},
            "knowledge_rules": {"learn": [{"fact_id": "F1", "when": "亲自看见怀表背面刻痕"}],
                                "never_learn": ["F1_REVEAL"]},
            "lorebook": [{"fact_id": "F1", "keywords": ["怀表", "刻痕"], "content_ref": "ledger:F1"}],
        }
        st, body = req("POST", f"/api/book/{BOOK}/char", CHAR)
        cid = (body or {}).get("character", {}).get("id")
        check("POST /char 建人物成功（id 自动生成）",
              st == 200 and body.get("ok") is True and cid == "char_01", str(body))
        st, body = req("POST", f"/api/book/{BOOK}/char", {"name": "  "})
        check("空名人物被拒（400/409）", st in (400, 409) and "姓名" in (body or {}).get("error", ""),
              str(body))
        st, body = req("POST", f"/api/book/{BOOK}/char", {"id": "char_099", "name": "鬼影"})
        check("不存在 id 更新被拒 409", st == 409, str(body))
        st, body = req("GET", f"/api/book/{BOOK}/char/char_01")
        check("GET /char 全量回读一致", st == 200
              and body.get("want") == CHAR["want"]
              and body.get("knowledge_rules", {}).get("never_learn") == ["F1_REVEAL"])
        # 更新路径
        CHAR2 = dict(CHAR, id="char_01", want="改：查清师父失踪真相")
        st, body = req("POST", f"/api/book/{BOOK}/char", CHAR2)
        check("POST /char 更新（带 id）成功", st == 200 and (body or {}).get("ok") is True)
        st, body = req("GET", f"/api/book/{BOOK}/char/char_01")
        check("更新已生效", st == 200 and body.get("want") == "改：查清师父失踪真相")

        # ============ 5. 章节列表 ============
        st, body = req("GET", f"/api/book/{BOOK}")
        check("GET /book 摘要（6 章列表 + 尚无 state）", st == 200
              and len(body.get("chapters", [])) == 6
              and body.get("state") is None  # 未提交过 → 无 state 文件
              and body["book"]["language"] == "zh")
        st, body = req("GET", f"/api/book/{BOOK}/chapter/1")
        check("GET /chapter/1（空章）", st == 200 and body.get("status") == "empty"
              and body.get("drafts") == [])
        st, body = req("GET", f"/api/book/{BOOK}/chapter/99")
        check("越界章号仍为合法路由（空章状态）", st == 200 and body.get("status") == "empty")

        # 暗账 seed：与 CLI smoke 相同的 two-entry ledger（工作区文件写入，黑盒链路需要 fact id）
        bible = wb.load_bible(BOOK)
        bible["ledger"] = [
            {"id": "F1", "plant_chapter": 1, "reveal_chapter": 3,
             "hook": "怀表背面刻着一个不属于师父籍贯的地名，只给特写不解释",
             "reveal_plan": "地名是师父三十年前当学徒的旧铺号", "canary": "旧铺"},
            {"id": "F1_REVEAL", "plant_chapter": 3, "reveal_chapter": 6,
             "hook": "（底牌登记用）贺三刀与旧铺号的关系",
             "reveal_plan": "贺三刀当年就在旧铺号当学徒", "canary": "旧铺"}]
        wb.save_bible(BOOK, bible)

        # ============ 6. 讨论三阶段（真实 LLM） ============
        print("--- discuss start（LLM 生成分支）---")
        st, body = req("POST", f"/api/book/{BOOK}/discuss/1", {"action": "start"})
        branches = (body or {}).get("branches") or []
        check("discuss start：3 条分支", st == 200 and len(branches) == 3
              and all(b.get("id") and b.get("summary") for b in branches), str(body)[:200])
        st, body = req("POST", f"/api/book/{BOOK}/discuss/1", {"action": "select", "branch_id": "Z9"})
        check("select 非法分支被拒 409", st == 409, str(body))
        print("--- discuss select（LLM 开场）---")
        st, body = req("POST", f"/api/book/{BOOK}/discuss/1", {"action": "select", "branch_id": "A"})
        session = (body or {}).get("session") or {}
        check("select A：会话建立 + 开场回复",
              st == 200 and session.get("branch") == "A"
              and (session.get("turns") or [{}])[0].get("role") == "ai")
        st, body = req("GET", f"/api/book/{BOOK}/chapter/1")
        check("章节状态 branching→讨论中（selected_branch=A）",
              st == 200 and body.get("selected_branch") == "A" and body.get("session_active") is True)
        print("--- discuss message（真实 LLM 一轮）---")
        st, body = req("POST", f"/api/book/{BOOK}/discuss/1",
                       {"action": "message", "message": "开场放在夜里收表，贺三刀当夜就要上门，节奏压紧。你觉得开场信息密度会不会太高？"})
        check("message：编剧回复（非空中文一轮）", st == 200
              and len(((body or {}).get("reply") or "")) > 20, str((body or {}).get("reply"))[:120])
        st, body = req("POST", f"/api/book/{BOOK}/discuss/1", {"action": "message", "message": "  "})
        check("空消息被拒 400", st == 400)
        st, body = req("POST", f"/api/book/{BOOK}/discuss/1", {"action": "teleport"})
        check("非白名单 discuss 动作 400", st == 400)

        # ============ 7. 锁卡（坏卡被拒 + 确认落盘） ============
        print("--- lock 生成（LLM 提炼章节卡，最多重试 2 次）---")
        card = None
        for attempt in range(2):  # flaky 防护：最多两轮生成
            st, body = req("POST", f"/api/book/{BOOK}/lock/1", {})
            card = (body or {}).get("card")
            if st == 200 and card:
                break
            print(f"  [flaky 防护] 第 {attempt+1} 次生成未过校验：{(body or {}).get('detail')}")
        check("lock 生成：全字段章节卡（未落盘）", card is not None
              and all(k in card for k in ("pov", "choice", "reader_promise", "engine"))
              and not os.path.exists(wb.card_file(BOOK, 1)), str(body)[:300])
        if card is None:
            return finish()  # 生成两轮都失败：无素材可断言，带 FAIL 退出
        # 坏卡确认：删必填 + 非法枚举 → 违规清单，不落盘
        bad = json.loads(json.dumps(card))
        bad.pop("objective")
        bad["engine"]["amplitude"] = "XXL"
        bad["pov"]["character"] = "不存在的角色"
        st, body = req("POST", f"/api/book/{BOOK}/lock/1", {"confirm": True, "card": bad})
        check("坏卡确认被拒：返回违规清单且不落盘", st == 409
              and isinstance((body or {}).get("detail"), list) and len(body["detail"]) >= 2
              and not os.path.exists(wb.card_file(BOOK, 1)), str(body)[:300])
        check("讨论已归档（status=discussed + jsonl）",
              (wb.load_bible(BOOK)["chapters"].get("1") or {}).get("status") == "discussed"
              and os.path.exists(os.path.join(wb.ws_dir(BOOK), "discussions", "ch01.jsonl")))
        print("--- lock 确认落盘 ---")
        st, body = req("POST", f"/api/book/{BOOK}/lock/1", {"confirm": True, "card": card})
        check("确认落盘：card.json + status=locked", st == 200
              and os.path.exists(wb.card_file(BOOK, 1))
              and (wb.load_bible(BOOK)["chapters"].get("1") or {}).get("status") == "locked",
              str(body)[:200])
        check("落盘卡片 pov 已归一为 id", (body or {}).get("card", {})
              .get("pov", {}).get("character", "").startswith("char_"))

        # ============ 8. write + 同章并发二连发（写锁拒绝） ============
        print("--- write（真实 LLM ×2：正文+delta；并发二连发）---")
        wresult = {}

        def writer():
            try:
                wresult["r"] = req("POST", f"/api/book/{BOOK}/write/1", {})
            except Exception as e:  # noqa: BLE001
                wresult["r"] = (0, {"error": repr(e)})

        t = threading.Thread(target=writer)
        t.start()
        lock_file = wb._write_lock_path(BOOK, 1)
        dl = time.time() + 120
        appeared = False
        while time.time() < dl:  # 等第一个请求进入 LLM 阶段（写锁文件出现）
            if os.path.exists(lock_file):
                appeared = True
                break
            time.sleep(0.5)
        check("write 第一发已进入写锁区（锁文件出现）", appeared)
        st2nd, body2nd = req("POST", f"/api/book/{BOOK}/write/1", {})
        check("同章 write 二连发：第二发被写锁拒绝 423",
              st2nd == 423 and "写入进程" in (body2nd or {}).get("error", ""),
              f"status={st2nd} body={body2nd}")
        t.join(timeout=900)
        st, body = wresult.get("r", (0, {}))
        check("write 第一发成功：三件套 + 报告", st == 200 and (body or {}).get("ok") is True
              and os.path.exists(wb.card_file(BOOK, 1))
              and os.path.exists(os.path.join(wb.drafts_dir(BOOK, 1), "v001.md"))
              and os.path.exists(os.path.join(wb.drafts_dir(BOOK, 1), "v001.delta.json"))
              and os.path.exists(os.path.join(wb.drafts_dir(BOOK, 1), "v001.lint.json")),
              str(body)[:300])
        check("写锁已释放", not os.path.exists(lock_file))
        bible = wb.load_bible(BOOK)
        check("章节状态 drafted", (bible["chapters"].get("1") or {}).get("status") == "drafted")

        # ============ 9. commit（ops 预览 → 确认；never_learn flaky 防护） ============
        print("--- commit 预览 + 确认 ---")

        def _fix_never_learn_delta():
            dp = os.path.join(wb.drafts_dir(BOOK, 1), "v001.delta.json")
            dj = json.load(open(dp, encoding="utf-8"))
            dj["ops"] = [o for o in dj.get("ops", [])
                         if not (o.get("op") == "learn" and o.get("fact_id") == "F1_REVEAL")]
            json.dump(dj, open(dp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

        st, body = req("POST", f"/api/book/{BOOK}/commit/1", {"confirmed": False})
        if st != 200 and "never_learn" in json.dumps(body, ensure_ascii=False):
            print("  [flaky 防护] 预览阶段 delta 撞 never_learn 红名单，模拟作者修 delta 后重跑")
            _fix_never_learn_delta()
            st, body = req("POST", f"/api/book/{BOOK}/commit/1", {"confirmed": False})
        check("commit 预览：ops 清单 + 提炼句", st == 200 and body.get("preview") is True
              and isinstance(body.get("ops"), list) and "derived" in body, str(body)[:300])
        st, body = req("POST", f"/api/book/{BOOK}/commit/1", {"confirmed": True})
        if st != 200 and "never_learn" in json.dumps(body, ensure_ascii=False):
            print("  [flaky 防护] delta 撞 never_learn 红名单，模拟作者修 delta 后重跑")
            _fix_never_learn_delta()
            st, body = req("POST", f"/api/book/{BOOK}/commit/1", {"confirmed": True})
        check("commit 确认：canon 落盘 + state 推进", st == 200 and (body or {}).get("ok") is True
              and os.path.exists(wb.canon_file(BOOK, 1))
              and StoryState(wb.state_path(BOOK)).revision == 1
              and os.path.exists(wb.state_path(BOOK) + ".bak-0"), str(body)[:300])
        st, body = req("POST", f"/api/book/{BOOK}/commit/1", {"confirmed": True})
        check("重复 commit 被拒（revision 不匹配，违规清单）", st == 409
              and any("不匹配" in x for x in (body or {}).get("detail", [])), str(body)[:200])

        # ============ 10. canon 读取 + 屏 5 数据 ============
        st, body = req("GET", f"/api/book/{BOOK}/canon")
        check("GET /canon：第 1 章正史连续视图", st == 200
              and len(body.get("chapters", [])) == 1
              and body["chapters"][0]["chapter"] == 1
              and len(body["chapters"][0]["text"]) > 100
              and body["chapters"][0]["drafts"] == ["v001"])
        st, body = req("GET", f"/api/book/{BOOK}/chapter/1")
        check("GET /chapter/1 committed 终态（canon 正文可见）", st == 200
              and body.get("status") == "committed" and len(body.get("canon") or "") > 100)
        st, body = req("GET", f"/api/book/{BOOK}")
        check("书摘要：state.revision=1 + 人物动态状态可见", st == 200
              and body["state"]["revision"] == 1 and body["state"]["as_of_chapter"] == 1
              and (body["characters"][0].get("knowledge") or {}).get("knows") is not None)

        # ============ 11. 世界设定端点（M3B-G） ============
        st, body = req("POST", f"/api/book/{BOOK}/world/meta",
                       {"time_period": "九十年代末，南方小城", "setting": "老九门典当行街"})
        check("POST /world/meta 更新 time_period/setting", st == 200 and body.get("ok") is True
              and body["world"]["time_period"] == "九十年代末，南方小城")
        st, body = req("GET", f"/api/book/{BOOK}/world")
        check("GET /world 全量（world 六字段）", st == 200
              and "time_period" in body and "era_materials" in body and "locations" in body
              and "rules" in body and body.get("setting") == "老九门典当行街")
        st, body = req("POST", f"/api/book/{BOOK}/world/material", {"entry": {
            "category": "物品道具", "keywords": ["怀表", "刻痕"],
            "content": "M3B-WEB-ERA-表壳内侧旋开处刻着修表匠铺号小字。", "chapter_range": None}})
        web_mat_id = (body or {}).get("material", {}).get("id")
        check("POST /world/material 新增（id 自动生成）", st == 200 and body.get("ok") is True
              and (web_mat_id or "").startswith("mat_"))
        st, body = req("GET", f"/api/book/{BOOK}")
        mats = (body.get("world") or {}).get("era_materials") or []
        check("验收#3：era_materials 写入后 GET /book/<name> 可见",
              st == 200 and any(m.get("id") == web_mat_id for m in mats))
        st, body = req("POST", f"/api/book/{BOOK}/world/material", {"entry": {
            "id": web_mat_id, "category": "物品道具", "keywords": ["怀表"],
            "content": "M3B-WEB-ERA-更新后的素材内容。"}})
        check("POST /world/material 同 id 更新", st == 200
              and (body or {}).get("material", {}).get("content") == "M3B-WEB-ERA-更新后的素材内容。")
        st, body = req("POST", f"/api/book/{BOOK}/world/material/remove", {"id": web_mat_id})
        check("POST /world/material/remove 删除成功", st == 200
              and body.get("removed") == web_mat_id)
        st, body = req("POST", f"/api/book/{BOOK}/world/material/remove", {"id": web_mat_id})
        check("重复删除被拒 409", st == 409)
        st, body = req("POST", f"/api/book/{BOOK}/world/propose", {"topic": ""})
        check("propose 空 topic 被拒 409", st == 409)

        # ============ 12. AI 素材提议（验收 #2：《大水将至》真实质量测试） ============
        print("--- theflood-smoke：AI 提议（真实 reader 通道 LLM，约 1-2 分钟）---")
        FLOOD = "theflood-smoke"
        if os.path.isdir(wb.ws_dir(FLOOD)):
            shutil.rmtree(wb.ws_dir(FLOOD))
        st, body = req("POST", "/api/books", {
            "name": FLOOD, "title": "大水将至", "genre": "怀旧都市悬疑加克苏鲁神话",
            "language": "zh", "platform": "番茄/webnovel",
            "logline": "1998年武汉盛夏，初中生李小凡的调查团发现民间组织囤积物资准备古怪祭祀，"
                       "在抗洪防汛的大背景下追查，结尾发现仪式是为送戴厚眼镜的小男孩胡子回他的位面。",
            "setting": "1998年武汉， ordinary 街区生活，偶有超自然暗示",
            "template": "悬疑假设弧", "total_chapters": 12})
        check("建《大水将至》测试书（theflood-smoke）", st == 200 and body.get("ok") is True)
        st, body = req("POST", f"/api/book/{FLOOD}/world/meta", {"time_period": "1998年夏，武汉"})
        check("theflood-smoke 设 time_period", st == 200)
        st, body = req("POST", f"/api/book/{FLOOD}/world/propose",
                       {"topic": "1998年武汉夏天 中学生的日常生活", "count": 10})
        cands = (body or {}).get("candidates") or []
        print(f"--- propose 返回 {len(cands)} 条候选（样例见下）---")
        for c in cands[:5]:
            print(f"  [{c.get('category')}] {'/'.join(c.get('keywords') or [])}: {c.get('content')}")
        check("验收#2：propose 返回 ≥8 条候选", st == 200 and len(cands) >= 8,
              f"st={st} n={len(cands)} {str(body)[:200]}")
        check("候选质量：每条有具体 content（≥15字）/分类/关键词（非泛化说明的粗筛）",
              all(len(str(c.get("content") or "")) >= 15 for c in cands)
              and all((c.get("category") or "").strip() for c in cands)
              and all(c.get("keywords") for c in cands),
              json.dumps(cands[:3], ensure_ascii=False)[:300])
        st, body = req("POST", f"/api/book/{FLOOD}/world/confirm", {"materials": cands[:2]})
        check("confirm 批量写入（source=AI提议已确认）", st == 200
              and len((body or {}).get("saved") or []) == 2
              and all(x.get("source") == "AI提议已确认" for x in (body or {}).get("saved") or []))
        st, body = req("GET", f"/api/book/{FLOOD}/world")
        check("确认的素材入 bible.world.era_materials", st == 200
              and len(body.get("era_materials") or []) == 2)

        # ============ 13. exempt 负样本（离线确定性） ============
        st, body = req("POST", f"/api/book/{BOOK}/exempt/1",
                       {"rule": "绝不存在的规则X", "reason": "测试"})
        check("exempt 无 finding 被拒 409", st == 409 and "没有规则" in (body or {}).get("error", ""),
              str(body))
        st, body = req("POST", f"/api/book/{BOOK}/exempt/1", {"rule": ""})
        check("exempt 缺 rule 被拒 400", st == 400)

        return finish()
    finally:
        dump_server_log(proc, lines)


def dump_server_log(proc, lines):
    if proc.poll() is None:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
            out = ""
    else:
        try:
            out, _ = proc.communicate(timeout=2)
        except Exception:  # noqa: BLE001
            out = ""
    tail = ("".join(lines) + (out or ""))[-1500:]
    if tail.strip():
        print("--- 服务日志尾部 ---")
        print(tail)


def finish():
    n_fail = RESULTS.count(False)
    print(f"\n=== webgui smoke 完成：{len(RESULTS) - n_fail}/{len(RESULTS)} 项通过 ===")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
