#!/usr/bin/env python3
"""workbench-web.py：api_write 的 report dict 加 audit 字段（前端徽标数据源）。"""
import io

F = "workbench-web.py"
c = io.open(F, encoding="utf-8").read()

old = (
    '        report = {"chapter": ch, "draft": fd["version"], "lint_report": fd["report"],\n'
    '                  "dropped_ops": dx["dropped_ops"], "warnings": dx["warnings"],\n'
    '                  "kept_ops": dx["kept_ops"]}'
)
new = (
    '        report = {"chapter": ch, "draft": fd["version"], "lint_report": fd["report"],\n'
    '                  "dropped_ops": dx["dropped_ops"], "warnings": dx["warnings"],\n'
    '                  "kept_ops": dx["kept_ops"],\n'
    '                  "audit": job.get("audit") if isinstance(job, dict) else None}'
)
assert old in c, "api_write report anchor missing"
c = c.replace(old, new, 1)

io.open(F, "w", encoding="utf-8").write(c)
print("api_write report + audit OK")
