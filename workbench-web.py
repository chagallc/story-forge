#!/usr/bin/env python3
"""story-forge 写作工作台 Web 界面（v1）：http.server 后端 + 单文件 vanilla JS 前端。

用法：
  python workbench-web.py            # 监听 127.0.0.1:17890（仅回环，不做鉴权）
  python workbench-web.py --port N   # 端口覆盖（webgui-smoke 隔离用；默认恒为 17890）

设计：docs/plans/WebGUI-workorder.md（唯一验收合同）。零第三方依赖、零构建、完全离线。
- 逻辑层零复制：全部走 workbench.py 的 *_core 函数（CLI 与 Web 共用同一套门禁/校验/落盘）
- LLM 非流式：讨论/落笔期间前端 loading；同 workspace 的写操作经 workspace 级互斥串行，
  write 的两段 LLM 调用期间放互斥、由 .write-lock-chNN 文件兜底同章互斥（跨进程同样有效）
- 安全：仅回环监听；路径参数白名单校验（书名/人物 id/章号），任何越出 workspaces/ 的尝试
  一律 400；前端不接触任何 key（LLM 配置只在服务端 config/models.local.json）
- GET / 服务 webgui.html（同目录）；其余路径 404。API 错误约定：非 2xx 时 body 为
  {"error": "...", "detail": [违规清单（可选）]}，前端 toast 展示。
"""
import argparse
import json
import os
import re
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import workbench as wb
from src.harness import codiscuss as _cd  # noqa: E402  # noqa: E402
from src.harness.state import StoryState  # noqa: E402

HTML_PATH = os.path.join(ROOT, "webgui.html")
DEFAULT_PORT = 17890
MAX_BODY = 2 * 1024 * 1024  # 2MB：人物卡/章节卡表单绰绰有余，防滥用

# 书名白名单：workspace 目录名（与 CLI new 约定一致：英文目录名）
RE_BOOK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
RE_CHAR_ID = re.compile(r"^char_\d+$")
# Windows 保留设备名（即使能建目录，后续读写也可能异常，一律拒绝）
RE_WIN_RESERVED = re.compile(r"(?i)^(con|prn|aux|nul|com\d|lpt\d)$")

# workspace 级互斥：同一本书的写操作串行（不同书可并发）。锁表本身用全局锁保护。
WS_LOCKS = {}
WS_LOCKS_GUARD = threading.Lock()


def ws_lock(book):
    with WS_LOCKS_GUARD:
        return WS_LOCKS.setdefault(book, threading.Lock())


class ApiError(Exception):
    """API 层错误：status 是 HTTP 状态码，msg/detail 进 {"error","detail"}。"""

    def __init__(self, status, msg, detail=None):
        super().__init__(msg)
        self.status = status
        self.msg = msg
        self.detail = detail


def refuse_to_api(e: wb.Refused):
    """workbench.Refused → API 错误。写锁占用（同章并发写）→ 423 LOCKED；其余门禁/校验拒绝 → 409。"""
    status = 423 if "另一个写入进程" in e.msg else 409
    return ApiError(status, e.msg, e.violations or None)


# ---------------- 路径安全 ----------------

def safe_book(raw):
    r"""书名段校验：白名单字符 + 目录必须存在。任何穿越形态（../、%2e%2e、反斜杠、盘符）都被
    字符白名单拦下（白名单只允许 [A-Za-z0-9_-]，不含 . / \ : 空格）。"""
    name = raw if isinstance(raw, str) else ""
    if not RE_BOOK.fullmatch(name) or RE_WIN_RESERVED.match(name):
        raise ApiError(400, f"非法书名：{raw!r}（只允许字母/数字/连字符/下划线）")
    if not os.path.isdir(wb.ws_dir(name)):
        raise ApiError(404, f"书不存在：{name}")
    return name


def safe_segment(raw, what="路径段"):
    """通用段校验：拒绝空段、穿越段（..）、内嵌分隔符（unquote 后的 / 与 \\）。"""
    seg = raw if isinstance(raw, str) else ""
    if not seg or seg in (".", "..") or "/" in seg or "\\" in seg or "\x00" in seg:
        raise ApiError(400, f"非法{what}：{raw!r}")
    return seg


def safe_chapter(raw):
    seg = safe_segment(raw, "章号")
    if not re.fullmatch(r"\d{1,3}", seg) or int(seg) < 1:
        raise ApiError(400, f"非法章号：{raw!r}")
    return int(seg)


def safe_char_id(raw):
    cid = safe_segment(raw, "人物 id")
    if not RE_CHAR_ID.fullmatch(cid):
        raise ApiError(400, f"非法人物 id：{raw!r}（应为 char_NN）")
    return cid


# ---------------- 数据组装（只读 GET 用） ----------------

def chapter_status_view(book, bible, ch):
    meta = bible["chapters"].get(str(ch)) or {}
    card, source = wb.load_card(book, ch, meta)
    eng = (card or {}).get("engine") or {}
    branches = None
    if meta.get("branches_path"):
        p = meta["branches_path"]
        p = p if os.path.isabs(p) else os.path.join(wb.ws_dir(book), p)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    branches = json.load(f).get("branches")
            except (json.JSONDecodeError, OSError):
                branches = None
    drafts = []
    d = wb.drafts_dir(book, ch)
    if os.path.isdir(d):
        for f in sorted(f for f in os.listdir(d) if re.fullmatch(r"v\d+\.md", f)):
            v = f[:-3]
            item = {"version": v}
            lp = os.path.join(d, f"{v}.lint.json")
            if os.path.exists(lp):
                try:
                    lj = json.load(open(lp, encoding="utf-8"))
                    item["lint_flags"] = lj.get("flags") or []
                except (json.JSONDecodeError, OSError):
                    item["lint_flags"] = None
            dp = os.path.join(d, f"{v}.delta.json")
            if os.path.exists(dp):
                try:
                    dj = json.load(open(dp, encoding="utf-8"))
                    item["delta_ops"] = len(dj.get("ops") or [])
                except (json.JSONDecodeError, OSError):
                    item["delta_ops"] = None
            rp = os.path.join(d, f"{v}.report.json")
            if os.path.exists(rp):
                try:
                    item["report"] = json.load(open(rp, encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            drafts.append(item)
    session = wb.load_discussion_session(book, ch)
    turns = session.get("turns") if session else None
    if turns is None and meta.get("discussion"):
        p = meta["discussion"]
        p = p if os.path.isabs(p) else os.path.join(wb.ws_dir(book), p)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    turns = [json.loads(l) for l in f if l.strip()]
            except (json.JSONDecodeError, OSError):
                turns = None
    canon = ""
    if os.path.exists(wb.canon_file(book, ch)):
        with open(wb.canon_file(book, ch), encoding="utf-8") as f:
            canon = f.read()
    latest = wb.latest_draft(book, ch)
    return {
        "chapter": ch,
        "status": meta.get("status", "empty"),
        "selected_branch": meta.get("selected_branch"),
        "card": card,
        "card_source": source,
        "branches": branches,
        "turns": turns,
        "session_active": bool(session),
        "drafts": drafts,
        "latest_draft": {"version": latest[0], "text": latest[2]} if latest else None,
        "canon": canon,
        "canon_committed": os.path.exists(wb.canon_file(book, ch)),
        "arc_label": eng.get("arc_label", ""),
        "amplitude": eng.get("amplitude", ""),
    }


def book_view(book):
    """GET /api/book/<name>：bible 摘要 + 章节列表 + 人物列表 + 动态状态。"""
    bible = wb.load_bible(book)
    state = StoryState(wb.state_path(book)) if os.path.exists(wb.state_path(book)) else None
    total = int(bible["arc"].get("total_chapters", 12))
    chapters = [chapter_status_view(book, bible, ch) for ch in range(1, total + 1)]
    chars = []
    st_chars = (state.data.get("characters") or {}) if state else {}
    for c in bible.get("characters", []):
        if not isinstance(c, dict):
            continue
        dyn = st_chars.get(c.get("id")) or {}
        # 完整人物卡（动机栈/声口/知识规则/lorebook）+ 动态状态合并输出
        chars.append({**c, "knowledge": dyn.get("knowledge") or {},
                      "location": dyn.get("location", ""),
                      "inventory": dyn.get("inventory") or [],
                      "relationships": dyn.get("relationships") or {}})
    return {
        "name": book,
        "book": bible.get("book") or {},
        "compass": bible.get("compass") or {},
        "arc": bible.get("arc") or {},
        "world": bible.get("world") or {},
        "ledger": bible.get("ledger") or [],
        "revision": bible.get("revision", 0),
        "state": None if state is None else {
            "revision": state.revision,
            "as_of_chapter": state.data.get("as_of_chapter", 0),
            "exemptions": len(state.data.get("exemptions", [])),
        },
        "chapters": chapters,
        "characters": chars,
    }


def char_view(bible, cid):
    c = next((x for x in bible.get("characters", [])
              if isinstance(x, dict) and x.get("id") == cid), None)
    if c is None:
        raise ApiError(404, f"人物不存在：{cid}")
    return c


def canon_view(book):
    """GET /api/book/<name>/canon：已提交章节连续阅读视图。"""
    bible = wb.load_bible(book)
    out = []
    for k in sorted(bible["chapters"].keys(), key=int):
        meta = bible["chapters"][k] or {}
        cf = wb.canon_file(book, int(k))
        if not os.path.exists(cf):
            continue
        with open(cf, encoding="utf-8") as f:
            text = f.read()
        eng = ((meta.get("card") or {}).get("engine") or {})
        d = wb.drafts_dir(book, int(k))
        drafts = sorted(f[:-3] for f in os.listdir(d)
                        if re.fullmatch(r"v\d+\.md", f)) if os.path.isdir(d) else []
        out.append({"chapter": int(k), "status": meta.get("status", ""),
                    "arc_label": eng.get("arc_label", ""),
                    "drafts": drafts, "text": text})
    return {"name": book, "title": (bible.get("book") or {}).get("title", book),
            "chapters": out}


# ---------------- HTTP Handler ----------------

class Handler(BaseHTTPRequestHandler):
    server_version = "story-forge-webgui/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 基础设施 ----

    def log_message(self, fmt, *args):  # 简化访问日志（一行一条，中文时间戳省略）
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, msg, detail=None):
        payload = {"error": msg}
        if detail:
            payload["detail"] = detail
        self._send_json(status, payload)

    def _read_json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, f"请求体过大（>{MAX_BODY // 1024}KB）")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "请求体必须是 JSON 对象")
        return data

    def _dispatch(self, method):
        try:
            parts = [urllib.parse.unquote(s) for s in urllib.parse.urlparse(self.path).path.split("/")]
            parts = [p for p in parts if p != ""]
            self._route(method, parts)
        except ApiError as e:
            self._error(e.status, e.msg, e.detail)
        except wb.Refused as e:
            self._error(409, e.msg, e.violations or None)
        except (RuntimeError,) as e:  # LLM 客户端失败（make_client/chat 重试耗尽）
            self._error(502, f"LLM 调用失败：{e}")
        except Exception as e:  # noqa: BLE001 防御：任何未预期异常都不带栈出去
            sys.stderr.write(f"[webgui] 500: {type(e).__name__}: {e}\n")
            self._error(500, f"服务器内部错误：{type(e).__name__}: {e}")

    # ---- 路由 ----

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _route(self, method, parts):
        if method == "GET" and parts == []:
            return self._serve_index()
        if parts[:1] != ["api"]:
            raise ApiError(404, "not found")
        p = parts[1:]

        # /api/books
        if p == ["books"]:
            if method == "GET":
                return self.api_books_list()
            if method == "POST":
                return self.api_books_create()
            raise ApiError(405, "method not allowed")

        # /api/book/<name>/...
        if p[:1] == ["book"] and len(p) >= 2:
            book = safe_book(p[1])
            rest = p[2:]
            if rest == []:
                if method == "GET":
                    return self._send_json(200, book_view(book))
                raise ApiError(405, "method not allowed")
            if rest == ["codiscuss"]:
                if method == "GET":
                    return self._send_json(200, _cd.load_codiscuss(book) or {"turns": []})
                raise ApiError(405, "method not allowed")
            if rest[:1] == ["codiscuss"] and len(rest) == 2:
                if method != "POST":
                    raise ApiError(405, "method not allowed")
                return self._route_codiscuss(rest[1], book)
            if rest == ["canon"] and method == "GET":
                return self._send_json(200, canon_view(book))
            if rest[:1] == ["char"]:
                return self._route_char(method, book, rest[1:])
            if rest[:1] == ["chapter"] and len(rest) >= 2:
                ch = safe_chapter(rest[1])
                return self._route_chapter(method, book, ch, rest[2:])
            # 章级动作：/api/book/<name>/{discuss|lock|write|commit|exempt}/<n>
            if rest[:1] in (["discuss"], ["lock"], ["write"], ["commit"], ["revise"], ["exempt"]) \
                    and len(rest) >= 2:
                ch = safe_chapter(rest[1])
                action = rest[0]
                if method != "POST":
                    raise ApiError(405, "method not allowed")
                if action == "discuss":
                    return self.api_discuss(book, ch)
                if action == "lock":
                    return self.api_lock(book, ch)
                if action == "write":
                    return self.api_write(book, ch)
                if action == "commit":
                    return self.api_commit(book, ch)
                if action == "revise":
                    return self.api_revise(book, ch)
                return self.api_exempt(book, ch)
            raise ApiError(404, "not found")
        raise ApiError(404, "not found")

    def _route_char(self, method, book, rest):
        if rest == []:
            if method == "POST":
                return self.api_char_save(book)
            raise ApiError(405, "method not allowed")
        if len(rest) == 1:
            cid = safe_char_id(rest[0])
            if method == "GET":
                bible = wb.load_bible(book)
                return self._send_json(200, char_view(bible, cid))
            raise ApiError(405, "method not allowed")
        raise ApiError(404, "not found")

    def _route_chapter(self, method, book, ch, rest):
        if rest == []:
            if method == "GET":
                bible = wb.load_bible(book)
                return self._send_json(200, chapter_status_view(book, bible, ch))
            raise ApiError(405, "method not allowed")
        action = safe_segment(rest[0], "动作")
        if method != "POST":
            raise ApiError(405, "method not allowed")
        if action == "discuss":
            return self.api_discuss(book, ch)
        if action == "lock":
            return self.api_lock(book, ch)
        if action == "write":
            return self.api_write(book, ch)
        if action == "commit":
            return self.api_commit(book, ch)
        if action == "exempt":
            return self.api_exempt(book, ch)
        raise ApiError(404, f"未知动作：{action}")



    def _route_codiscuss(self, action, book):
        body = self._read_json_body()
        bible = wb.load_bible(book)
        session = _cd.load_codiscuss(book)
        turns = (session or {}).get("turns", [])
        client = wb.client_for(bible, "writer", book)

        if action == "start":
            brief = str(body.get("brief") or "")
            msgs = _cd.codiscuss_messages(bible, [], brief_extra=brief)
            reply = client.chat(msgs, tag="codiscuss-start")
            turns = [{"role": "user", "content": brief},
                     {"role": "ai", "content": reply}]
            _cd.save_codiscuss_session(book, {"brief": brief, "turns": turns})
            return self._send_json(200, {"ok": True, "turns": turns})

        if action == "message":
            message = str(body.get("message") or "").strip()
            if not message:
                raise ApiError(400, "空消息")
            turns = turns + [{"role": "user", "content": message}]
            msgs = _cd.codiscuss_messages(bible, turns)
            reply = client.chat(msgs, tag="codiscuss-msg")
            turns = turns + [{"role": "ai", "content": reply}]
            _cd.save_codiscuss_session(book, {"brief": session.get("brief", "") if session else "",
                                              "turns": turns})
            return self._send_json(200, {"ok": True, "turns": turns})

        if action == "extract":
            # 落卡提炼：从讨论提炼人物 JSON（返回预览，前端确认后调 save）
            chars = _cd.extract_characters_from_discussion(
                turns, client, book, bible.get("book", {}).get("language", "zh"))
            return self._send_json(200, {"ok": True, "characters": chars})

        if action == "save":
            chars = body.get("characters") or []
            if not chars:
                raise ApiError(400, "characters 为空")
            existing = bible.get("characters", [])
            have_names = {c.get("name") for c in existing}
            seq = len(existing)
            for c in chars:
                if not isinstance(c, dict) or not c.get("name"):
                    continue
                if c.get("name") in have_names:
                    continue  # 重名跳过（避免覆盖已有人物）
                seq += 1
                c.setdefault("id", f"char_{seq:02d}")
                c.setdefault("card", "")
                c.setdefault("anchors", [])
                c.setdefault("knowledge_rules", {"learn": [], "never_learn": []})
                c.setdefault("lorebook", [])
                existing.append(c)
                have_names.add(c.get("name"))
            bible["characters"] = existing
            wb.save_bible(book, bible)
            return self._send_json(200, {"ok": True, "added": len(chars)})

        raise ApiError(404, f"unknown codiscuss action: {action}")

    # ---- 静态页 ----

    def _serve_index(self):
        try:
            with open(HTML_PATH, "rb") as f:
                body = f.read()
        except OSError:
            raise ApiError(500, f"前端文件缺失：webgui.html（应与 workbench-web.py 同目录）")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---- API 实现 ----

    def api_books_list(self):
        rows, locks = wb.books_overview()
        by_name = {}
        for lk in locks:
            m = re.search(r"[\\/]\.write-lock-ch(\d+)$", lk["path"])
            b = os.path.normpath(os.path.dirname(lk["path"])).split(os.sep)[-1]
            by_name.setdefault(b, []).append({"chapter": int(m.group(1)) if m else None,
                                              "age": lk["age"]})
        for r in rows:
            r["active_locks"] = by_name.get(r["name"]) or []
        self._send_json(200, {"books": rows})

    def api_books_create(self):
        body = self._read_json_body()
        name = body.get("name")
        if not RE_BOOK.fullmatch(name or "") or RE_WIN_RESERVED.match(name or ""):
            raise ApiError(400, "书名（目录名）只允许字母/数字/连字符/下划线，且不以连字符开头")
        if os.path.exists(wb.ws_dir(name)):
            raise ApiError(409, f"书已存在：{name}")
        language = body.get("language") or "zh"
        if language not in ("zh", "en"):
            raise ApiError(400, "language 只允许 zh 或 en")
        try:
            total = int(body.get("total_chapters") or 12)
        except (TypeError, ValueError):
            raise ApiError(400, "规划章数必须是整数")
        if not 1 <= total <= 200:
            raise ApiError(400, "规划章数须在 1~200 之间")
        wb.create_book_core(name, title=str(body.get("title") or "").strip() or name,
                            genre=str(body.get("genre") or "").strip(),
                            language=language,
                            platform=str(body.get("platform") or "").strip(),
                            logline=str(body.get("logline") or "").strip(),
                            setting=str(body.get("setting") or "").strip(),
                            template=str(body.get("template") or "").strip(),
                            total_chapters=total,
                            ending_direction=str(body.get("ending_direction") or "").strip(),
                            reader_promise=str(body.get("reader_promise") or "").strip())
        self._send_json(200, {"ok": True, "name": name})

    def api_char_save(self, book):
        with ws_lock(book):
            bible = wb.load_bible(book)
            body = self._read_json_body()
            try:
                c = wb.save_character_core(book, bible, body)
            except wb.Refused as e:
                raise refuse_to_api(e)
            self._send_json(200, {"ok": True, "character": c})

    def api_discuss(self, book, ch):
        body = self._read_json_body()
        action = str(body.get("action") or "")
        with ws_lock(book):
            bible = wb.load_bible(book)
            if action == "start":
                branches, generated = wb.ensure_branches(book, bible, ch, log=[])
                self._send_json(200, {"ok": True, "branches": branches, "generated": generated})
                return
            if action == "regen":
                branches, _ = wb.ensure_branches(book, bible, ch, regen=True, log=[])
                self._send_json(200, {"ok": True, "branches": branches, "generated": True})
                return
            if action == "select":
                sel = str(body.get("branch_id") or "").strip()
                if not sel:
                    raise ApiError(400, "缺少 branch_id")
                session = wb.start_discussion_session(book, bible, ch, sel)
                self._send_json(200, {"ok": True, "session": session})
                return
            if action == "message":
                message = str(body.get("message") or "").strip()
                if not message:
                    raise ApiError(400, "消息不能为空")
                session, reply = wb.discussion_reply_core(book, bible, ch, message)
                self._send_json(200, {"ok": True, "reply": reply, "turns": session["turns"]})
                return
            if action == "archive":
                session = wb.load_discussion_session(book, ch)
                if not session:
                    raise ApiError(409, "该章没有进行中的讨论会话")
                log_path = wb.archive_discussion(book, bible, ch, session["turns"])
                self._send_json(200, {"ok": True, "log_path": os.path.relpath(log_path, wb.ws_dir(book))})
                return
            raise ApiError(400, f"未知 discuss 动作：{action!r}")

    def api_lock(self, book, ch):
        body = self._read_json_body()
        with ws_lock(book):
            bible = wb.load_bible(book)
            if body.get("confirm"):
                # 作者确认（可逐项修改后）→ 校验 + 落盘
                try:
                    card = wb.confirm_chapter_card_core(book, bible, ch, body.get("card"))
                except wb.Refused as e:
                    raise refuse_to_api(e)
                self._send_json(200, {"ok": True, "card": card})
                return
            # 生成阶段：讨论收尾归档 + LLM 出卡（不落盘）
            session = wb.load_discussion_session(book, ch)
            meta = bible["chapters"].get(str(ch)) or {}
            if session and meta.get("status") not in ("locked", "drafted", "committed"):
                wb.archive_discussion(book, bible, ch, session["turns"])
            log = []
            card, violations = wb.generate_chapter_card_core(book, bible, ch, log=log)
            if card is None:
                raise ApiError(422, "章节卡生成后仍未过校验（已重试 2 次）", violations)
            self._send_json(200, {"ok": True, "card": card})

    def api_write(self, book, ch):
        # 三段式：prepare（互斥）→ prose LLM（互斥外，写锁文件兜底）→ finalize/delta
        bible = wb.load_bible(book)
        with ws_lock(book):
            try:
                job = wb.write_prepare(book, ch, bible=bible)
            except wb.Refused as e:
                raise refuse_to_api(e)
        # —— 互斥外：正文 LLM（同章再入请求会被 prepare 的写锁拒绝 → 423）——
        log = []
        finalized = False
        try:
            text = wb.write_prose(job, log=log)
            with ws_lock(book):
                fd = wb.write_finalize_draft(job, text, log=log)
            audit_r = wb.run_audit(book, bible, ch, text)
            finalized = True
            # —— 互斥外：delta LLM ——
            dx = wb.write_delta_core(book, job["bible"], ch, fd["version"], text, log=log)
        except wb.Refused as e:
            raise refuse_to_api(e)
        except Exception:
            # CLI 语义（异常时锁残留 1h 自然过期）在 Web 层收紧：草稿未落盘就释放锁，
            # 避免 LLM 一次失败把该章锁死一小时（finalized 后绝不触碰锁文件，防误删并发者的锁）
            if not finalized and os.path.exists(job["lock_path"]):
                try:
                    os.remove(job["lock_path"])
                except OSError:
                    pass
            raise
        # 写报告落盘（drafts/vNNN.report.json）：drafts 历史里可回看丢弃 op/警告
        report = {"chapter": ch, "draft": fd["version"], "lint_report": fd["report"],
                  "dropped_ops": dx["dropped_ops"], "warnings": dx["warnings"],
                  "kept_ops": dx["kept_ops"],
                  "audit": audit_r}
        wb._write_json(os.path.join(wb.drafts_dir(book, ch), f"{fd['version']}.report.json"), report)
        self._send_json(200, {"ok": True, "version": fd["version"],
                              "draft_path": os.path.relpath(fd["draft_path"], wb.ws_dir(book)),
                              "lint_report": fd["report"], "report": report})

    def api_revise(self, book, ch):
        """微调剧情：{intent, base_version?} → 定向修订出新 draft 版本 + 合理性审核。"""
        import time as _t
        body = self._read_json_body()
        intent = str(body.get("intent") or "").strip()
        if not intent:
            raise ApiError(400, "缺 intent（微调意图）")
        base_version = body.get("base_version")
        lock_path = wb.os.path.join(wb.ws_dir(book), f".write-lock-ch{ch:02d}")
        if wb.os.path.exists(lock_path) and (_t.time() - wb.os.path.getmtime(lock_path)) < 3600:
            raise ApiError(423, "另一个写入进程占用该章（写锁未过期）")
        open(lock_path, "w").close()
        log = []
        try:
            result = wb.revise_core(book, ch, intent, base_version=base_version, log=log)
        except wb.Refused as e:
            if wb.os.path.exists(lock_path):
                try:
                    wb.os.remove(lock_path)
                except OSError:
                    pass
            raise refuse_to_api(e)
        except Exception:
            if wb.os.path.exists(lock_path):
                try:
                    wb.os.remove(lock_path)
                except OSError:
                    pass
            raise
        self._send_json(200, {
            "ok": True, "version": result["version"],
            "base_version": result["base_version"], "intent": result["intent"],
            "draft_path": wb.os.path.relpath(result["draft_path"], wb.ws_dir(book)),
            "lint_report": result["lint_report"],
            "audit": result.get("audit"),
            "delta": {"kept_ops": result.get("kept_ops"),
                      "dropped_ops": result.get("dropped_ops"),
                      "warnings": result.get("warnings")},
            "log": log})

    def api_commit(self, book, ch):
        body = self._read_json_body()
        revised = body.get("revised_path")
        with ws_lock(book):
            try:
                preview = wb.commit_preview(book, ch, revised=revised)
            except wb.Refused as e:
                raise refuse_to_api(e)
            if not body.get("confirmed"):
                self._send_json(200, {
                    "ok": True, "preview": True,
                    "version": preview["version"],
                    "state_revision": preview["state"].revision,
                    "next_revision": preview["state"].revision + 1,
                    "ops": [{k: v for k, v in op.items() if k != "evidence"}
                            for op in preview["ops"]],
                    "derived": preview["derived"],
                    "canon_exists": preview["canon_exists"]})
                return
            result = wb.commit_execute(preview,
                                       recorded_consequence=str(body.get("recorded_consequence") or ""))
            self._send_json(200, {"ok": True,
                                  "canon_path": os.path.relpath(result["canon_path"], wb.ws_dir(book)),
                                  "revision": result["revision"],
                                  "as_of_chapter": result["as_of_chapter"],
                                  "recorded_consequence": result["recorded_consequence"]})

    def api_exempt(self, book, ch):
        body = self._read_json_body()
        rule = str(body.get("rule") or "").strip()
        reason = str(body.get("reason") or "").strip()
        if not rule:
            raise ApiError(400, "缺少规则名（rule）")
        with ws_lock(book):
            try:
                ex = wb.exempt_core(book, ch, rule, reason)
            except wb.Refused as e:
                raise refuse_to_api(e)
        self._send_json(200, {"ok": True, "exemption": ex})


def main():
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="story-forge 本地 Web 工作台")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"监听端口（默认 {DEFAULT_PORT}；仅回环地址）")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"story-forge WebGUI 已启动：http://127.0.0.1:{args.port}（仅本机可访问，Ctrl+C 退出）",
          flush=True)  # 冒烟测试从管道读启动行，必须即刷
    print(f"前端文件：{HTML_PATH}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()
