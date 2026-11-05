#!/usr/bin/env python3
"""插入 api_revise 方法（路由已由 edit 完成）。"""
import io

F = "workbench-web.py"
c = io.open(F, encoding="utf-8").read()

if "def api_revise" in c:
    print("api_revise already exists")
    raise SystemExit(0)

api_revise = '''    def api_revise(self, book, ch):
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
            result = wb.revise_core(book, ch, intent, base_version=base_version, log=log.append)
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

'''

anchor = "    def api_commit(self, book, ch):"
assert anchor in c, "api_commit anchor missing"
c = c.replace(anchor, api_revise + anchor, 1)

# time/os import（workbench-web.py 顶部应已有 os；time 可能没有）
io.open(F, "w", encoding="utf-8").write(c)
print("api_revise inserted")
