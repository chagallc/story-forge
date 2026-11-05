#!/usr/bin/env python3
"""revise_core 落 report.json（含 audit）。"""
import io

F = "workbench.py"
c = io.open(F, encoding="utf-8").read()

old = (
    '    # 合理性审核（reader 通道，异构；失败不阻塞）\n'
    '    audit_result = run_audit(book, bible, ch, text)\n'
    '    if audit_result:\n'
    '        log(f"  合理性审核：{audit_summary(audit_result)}")'
)
new = (
    '    # 合理性审核（reader 通道，异构；失败不阻塞）\n'
    '    audit_result = run_audit(book, bible, ch, text)\n'
    '    if audit_result:\n'
    '        log(f"  合理性审核：{audit_summary(audit_result)}")\n'
    '\n'
    '    # report.json 落盘（Web 草稿历史回看：lint/audit/delta 概要）\n'
    '    _write_json(os.path.join(ddir, f"{version}.report.json"), {\n'
    '        "chapter": ch, "draft": version, "intent": intent,\n'
    '        "base_version": base_version or (versions[-1].replace(".md", "") if versions else None),\n'
    '        "lint_report": lint["flags"], "audit": audit_result,\n'
    '        "delta_kept_ops": len(dx.get("kept_ops", [])),\n'
    '        "dropped_ops": dx.get("dropped_ops", []),\n'
    '        "generated_at": datetime.now().isoformat(timespec="seconds")})'
)
assert old in c, "revise audit block not found"
c = c.replace(old, new, 1)

io.open(F, "w", encoding="utf-8").write(c)
print("revise report.json OK")
