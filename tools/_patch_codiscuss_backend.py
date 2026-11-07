#!/usr/bin/env python3
"""workbench-web.py：codiscuss 路由 + _route_codiscuss 方法。"""
import io

F = "workbench-web.py"
c = io.open(F, encoding="utf-8").read()

# import codiscuss（顶部）
if "codiscuss" not in c.split("def ")[0]:
    c = c.replace(
        "import workbench as wb",
        "import workbench as wb\nfrom src.harness import codiscuss as _cd  # noqa: E402",
        1)

# 路由：codiscuss 端点（插在 canon 端点前）
Q = chr(34)
anchor = (
    "            if rest == [" + Q + "canon" + Q + "] and method == " + Q + "GET" + Q + ":"
)
assert anchor in c, "canon route anchor missing"
routes = (
    "            if rest == [" + Q + "codiscuss" + Q + "]:\n"
    "                if method == " + Q + "GET" + Q + ":\n"
    "                    return self._send_json(200, _cd.load_codiscuss(book) or {"
    + Q + "turns" + Q + ": []})\n"
    "                raise ApiError(405, " + Q + "method not allowed" + Q + ")\n"
    "            if rest[:1] == [" + Q + "codiscuss" + Q + "] and len(rest) == 2:\n"
    "                if method != " + Q + "POST" + Q + ":\n"
    "                    raise ApiError(405, " + Q + "method not allowed" + Q + ")\n"
    "                return self._route_codiscuss(rest[1], book)\n"
) + anchor
c = c.replace(anchor, routes, 1)

# _route_codiscuss 方法（POST start/message/save/extract）
method = '''

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
            chars = wb.extract_characters_from_discussion(
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
'''

anchor2 = "    # ---- 静态页 ----"
assert anchor2 in c, "static page anchor missing"
c = c.replace(anchor2, method + "\n" + anchor2, 1)

io.open(F, "w", encoding="utf-8").write(c)
print("codiscuss routes + method added")
