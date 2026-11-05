#!/usr/bin/env python3
"""workbench-web.py 加 /revise 路由 + api_revise 方法。"""
import io

F = "workbench-web.py"
c = io.open(F, encoding="utf-8").read()

Q = chr(34)
old_route = (
    '                if action == ' + Q + 'commit' + Q + ':\n'
    '                    return self.api_commit(book, ch)\n'
    '                return self.api_exempt(book, ch)'
)
new_route = (
    '                if action == ' + Q + 'commit' + Q + ':\n'
    '                    return self.api_commit(book, ch)\n'
    '                if action == ' + Q + 'revise' + Q + ':\n'
    '                    return self.api_revise(book, ch)\n'
    '                return self.api_exempt(book, ch)'
)
n = c.count(old_route)
assert n == 1, f"expect 1 occurrence, got {n}"
c = c.replace(old_route, new_route)

api_revise = '''
    def api_revise(self, book, ch):
        """微调剧情：{intent, base_version?} → 定向修订出新 draft 版本 + 合理性审核。"""
        body = self._read_json_body()
        intent = str(body.get("intent") or "").strip()
        if not intent:
            raise ApiError(400, "缺 intent（微调意图）")
        base_version = body.get("base_version")
        lock_path = os.path.join(wb.ws_dir(book), f".write-lock-ch{ch:02d}")
        if os.path.exists(lock_path) and (time.time() - os.path.getmtime(lock_path)) < 3600:
            raise ApiError(423, "另一个写入进程占用该章（写锁未过期）")
        open(lock_path, "w").close()
        log = []
        try:
            result = wb.revise_core(book, ch, intent, base_version=base_version, log=log.append)
        except wb.Refused as e:
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
            raise refuse_to_api(e)
        except Exception:
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
            raise
        self._send_json(200, {
            "ok": True, "version": result["version"],
            "base_version": result["base_version"], "intent": result["intent"],
            "draft_path": os.path.relpath(result["draft_path"], wb.ws_dir(book)),
            "lint_report": result["lint_report"],
            "audit": result.get("audit"),
            "delta": {"kept_ops": result.get("kept_ops"),
                      "dropped_ops": result.get("dropped_ops"),
                      "warnings": result.get("warnings")},
            "log": log})
'''

# api_revise 方法插在 api_commit 之前
anchor = "    def api_commit(self, book, ch):"
assert anchor in c, "api_commit anchor missing"
c = c.replace(anchor, api_revise + "\n" + anchor, 1)

# time import 检查
if "\nimport time\n" not in c and not c.startswith("import time"):
    pass  # workbench-web.py 可能已有
if "import time" not in c.split("\n\n")[0] and "\nimport time\n" not in c:
    c = c.replace("import json", "import json\nimport time", 1)

io.open(F, "w", encoding="utf-8").write(c)
print("routes + api_revise added")
