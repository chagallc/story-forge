#!/usr/bin/env python3
"""api_write：finalize 后挂合理性审核，report.audit 接线。"""
import io

F = "workbench-web.py"
c = io.open(F, encoding="utf-8").read()

# 1. finalize 行后加 audit 调用
anchor = "            fd = wb.write_finalize_draft(job, text, log=log)"
new_anchor = anchor + "\n            audit_r = wb.run_audit(book, bible, ch, text)"
if "audit_r = wb.run_audit" not in c:
    assert anchor in c, "finalize anchor missing"
    c = c.replace(anchor, new_anchor, 1)

# 2. report dict 的 audit 字段接线
old = (
    '                  "kept_ops": dx["kept_ops"],\n'
    '                  "audit": job.get("audit") if isinstance(job, dict) else None}'
)
new = '                  "kept_ops": dx["kept_ops"],\n                  "audit": audit_r}'
if old in c:
    c = c.replace(old, new, 1)
else:
    old2 = '                  "kept_ops": dx["kept_ops"]}'
    assert old2 in c, "report dict anchor missing"
    c = c.replace(old2, '                  "kept_ops": dx["kept_ops"],\n                  "audit": audit_r}', 1)

# 3. 响应体加 audit
old3 = '"lint_report": fd["report"], "report": report}'
if old3 in c and '"audit": audit_r' not in c.split("def api_write")[1].split("def ")[0].split("report")[0]:
    pass  # report 已含 audit，响应引用 report 即可

io.open(F, "w", encoding="utf-8").write(c)
print("api_write audit wired")
