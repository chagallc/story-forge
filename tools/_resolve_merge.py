#!/usr/bin/env python3
"""解决 workbench.py 的 M3A/WebGUI 合并冲突（2 处）+ locked_through 推进归位 commit_execute。"""
import io
import re

F = "workbench.py"
c = io.open(F, encoding="utf-8").read()

# ---- 冲突 1：cmd_new 的 arc 初始化（webgui 防零 + M3A 滚动纪律合并）----
c1_old = re.search(
    r'<<<<<<< HEAD\n(\s+"anchors": \[\], "total_chapters": int\(total_chapters\) or 12,\n'
    r'\s+"locked_through": 0, "planned_through": int\(total_chapters\) or 12},)\n'
    r'=======\n'
    r'(\s+"anchors": \[\], "total_chapters": total,\n'
    r'\s+"locked_through": 0,\n'
    r'\s+"planned_through": min\(total, ROLLING_WINDOW\)\},.*?\n)'
    r'>>>>>>> main\n', c, re.DOTALL)
assert c1_old, "conflict 1 not found"
c1_new = (
    '                "anchors": [], "total_chapters": int(total_chapters) or 12,\n'
    '                "locked_through": 0,\n'
    '                "planned_through": min(int(total_chapters) or 12, ROLLING_WINDOW)},  # v4：细纲前沿受滚动纪律约束\n'
)
c = c[:c1_old.start()] + c1_new + c[c1_old.end():]

# ---- 冲突 2：cmd_commit 尾部（保留 webgui result 打印；M3A 的 locked_through 推进移入 commit_execute）----
c2 = re.search(
    r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> main\n', c, re.DOTALL)
assert c2, "conflict 2 not found"
ours = c2.group(1)  # webgui result 打印（保留）
c = c[:c2.start()] + ours + "\n" + c[c2.end():]

# ---- locked_through 推进归位：加进 commit_execute（重读 bible 后、save_bible 前）----
anchor = '    meta["status"] = "committed"\n    save_bible(book, bible)'
assert anchor in c, "commit_execute anchor not found"
c = c.replace(
    anchor,
    '    # M3A：commit = 锁定事件（含旧格式直通章），推进 locked_through 供滚动规划判界\n'
    '    arc = bible.setdefault("arc", {})\n'
    '    arc["locked_through"] = max(int(arc.get("locked_through", 0) or 0), ch)\n'
    '    meta["status"] = "committed"\n'
    '    save_bible(book, bible)',
    1,
)

io.open(F, "w", encoding="utf-8").write(c)
print("conflicts resolved:", len(re.findall(r"<<<<<<<", c)) == 0)
