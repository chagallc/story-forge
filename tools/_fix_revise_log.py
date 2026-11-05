#!/usr/bin/env python3
"""revise_core 的 log 约定统一为 _log_collector（emit）。"""
import io

F = r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge-webgui\workbench.py"
c = io.open(F, encoding="utf-8").read()

# revise_core 开头：log = log or lambda → emit = _log_collector(log)
old_head = (
    '    log = log or (lambda m: None)\n'
    '    bible = bible or load_bible(book)'
)
new_head = (
    '    emit = _log_collector(log)\n'
    '    bible = bible or load_bible(book)'
)
assert old_head in c, "head not found"
c = c.replace(old_head, new_head, 1)

# 3 处调用改 emit
n = c.count('log(f"  合理性审核')
c = c.replace('log(f"  合理性审核', 'emit(f"  合理性审核')
n2 = c.count('log(f"  合理性审核失败')
c = c.replace('log(f"  合理性审核失败', 'emit(f"  合理性审核失败')
print(f"replaced: 审核 {n}, 失败 {n2}")

io.open(F, "w", encoding="utf-8").write(c)
print("done")
