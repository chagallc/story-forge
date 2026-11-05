#!/usr/bin/env python3
"""从 M3A worktree 移植 run_fact_extraction + commit 触发到合并版 workbench.py。"""
import io
import re

src = io.open(r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge-m3a\workbench.py", encoding="utf-8").read()
dst_f = r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge-webgui\workbench.py"
dst = io.open(dst_f, encoding="utf-8").read()

# 1. 提取 run_fact_extraction 函数（M3A 版）
m = re.search(r"(def run_fact_extraction\(book, bible, ch, canon_text, delta, state_revision\):.*?)(?=\n\n# -{10,}|\n\ndef )", src, re.DOTALL)
assert m, "run_fact_extraction not found in M3A"
func = m.group(1)

# 2. 提取 commit 尾部触发调用（M3A 版）
t = re.search(r"(    # P-G1：commit 成功后自动抽取章级事实.*?print\(f\"\[graph\] 警告：事实抽取失败（不阻塞 commit，可重抽恢复）：\{type\(e\).__name__\}: \{e\}\"\)\n)", src, re.DOTALL)
assert t, "commit trigger not found in M3A"
trigger = t.group(1)

# 3. 插入 run_fact_extraction（放在 extraction_client_for 之后）
m2 = re.search(r"(def extraction_client_for\(bible, book\):.*?)(?=\n\ndef |\n\n# -{10,})", dst, re.DOTALL)
assert m2, "extraction_client_for not found in dst"
insert_at = m2.end(1)
dst = dst[:insert_at] + "\n\n\n" + func + dst[insert_at:]

# 4. 插入 commit 尾部触发（webgui 版 cmd_commit 的 result 打印之后）
anchor = 'print(f"recorded_consequence 已回填：{result[' + chr(39) + "recorded_consequence" + chr(39) + ']}")'
assert anchor in dst, "commit print anchor not found"
dst = dst.replace(anchor, anchor + "\n" + trigger, 1)

io.open(dst_f, "w", encoding="utf-8").write(dst)
print("transplanted: run_fact_extraction + commit trigger")
