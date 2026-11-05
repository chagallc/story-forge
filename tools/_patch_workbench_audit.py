#!/usr/bin/env python3
"""workbench.py：run_audit helper + write/revise 挂合理性审核。"""
import io

F = "workbench.py"
c = io.open(F, encoding="utf-8").read()

# 1. run_audit helper
helper = (
    '\ndef run_audit(book, bible, ch, text):\n'
    '    """合理性审核（reader 通道，异构）。失败返回 None（不阻塞）。"""\n'
    '    try:\n'
    '        aclient = client_for(bible, "reader", book)\n'
    '        prev_tail = ""\n'
    '        if ch > 1:\n'
    '            canon_prev = os.path.join(ws_dir(book), "chapters", f"ch{ch-1:02d}", "canon.md")\n'
    '            if os.path.exists(canon_prev):\n'
    '                prev_tail = open(canon_prev, encoding="utf-8").read()[-400:]\n'
    '        return audit_mod.audit_chapter(bible, ch, text, prev_tail, aclient,\n'
    '                                       bible.get("book", {}).get("language", "zh"))\n'
    '    except Exception as e:  # noqa: BLE001\n'
    '        print(f"[audit] 合理性审核失败（不阻塞）：{type(e).__name__}: {str(e)[:120]}")\n'
    '        return None\n\n\n'
)
anchor = "def revise_core(book, ch, intent, base_version=None, bible=None, log=None):"
assert anchor in c, "revise_core anchor missing"
c = c.replace(anchor, helper + anchor, 1)

# 2. revise_core 内联 audit 换 helper
old_inline_start = "    audit_result = None\n"
old_inline = (
    '    audit_result = None\n'
    '    try:\n'
    '        aclient = client_for(bible, "reader", book)\n'
    '        prev_tail = ""\n'
    '        if ch > 1:\n'
    '            canon_prev = os.path.join(ws_dir(book), "chapters", f"ch{ch-1:02d}", "canon.md")\n'
    '            if os.path.exists(canon_prev):\n'
    '                prev_tail = open(canon_prev, encoding="utf-8").read()[-400:]\n'
    '        audit_result = audit_mod.audit_chapter(bible, ch, text, prev_tail, aclient, lang)\n'
    '        log(f"  合理性审核：{audit_summary(audit_result)}")\n'
    '    except Exception as e:  # noqa: BLE001\n'
    '        audit_result = {"issues": [], "audit_error": str(e)[:200]}\n'
    '        log(f"  合理性审核失败（不阻塞）：{str(e)[:120]}")'
)
new_inline = (
    '    audit_result = run_audit(book, bible, ch, text)\n'
    '    if audit_result:\n'
    '        log(f"  合理性审核：{audit_summary(audit_result)}")'
)
assert old_inline in c, "inline audit not found"
c = c.replace(old_inline, new_inline, 1)

# 3. write_chapter_core return 加 audit
old_ret = (
    '    return {"version": fd["version"], "text": text, "draft_path": fd["draft_path"],\n'
    '            "lint_path": fd["lint_path"], "report": fd["report"], "flags": fd["flags"], **dx}'
)
new_ret = (
    '    audit_result = run_audit(book, bible, ch, text) if bible is not None else None\n'
    '    return {"version": fd["version"], "text": text, "draft_path": fd["draft_path"],\n'
    '            "lint_path": fd["lint_path"], "report": fd["report"], "flags": fd["flags"],\n'
    '            "audit": audit_result, **dx}'
)
assert old_ret in c, "wcc return not found"
c = c.replace(old_ret, new_ret, 1)

io.open(F, "w", encoding="utf-8").write(c)
print("workbench.py patched")
