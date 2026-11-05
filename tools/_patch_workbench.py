#!/usr/bin/env python3
"""给 workbench.py 的 cmd_write 加同章并发锁 + books 总览命令。"""
import io
import re

F = r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge\workbench.py"
c = io.open(F, encoding="utf-8").read()

# 1. cmd_write 加并发锁
old = (
    '    spec = bible_to_spec(book, bible)\n'
    '    state = load_state(book, bible)\n'
    '    client = client_for(bible, "writer", book)'
)
new = (
    '    # 同章并发写保护：锁文件 1 小时内视为有效（多书并行安全，同书同章互斥）\n'
    '    lock_path = os.path.join(ws_dir(book), f".write-lock-ch{ch:02d}")\n'
    '    if os.path.exists(lock_path) and (time.time() - os.path.getmtime(lock_path)) < 3600:\n'
    '        print(f"警告：第 {ch} 章可能有另一个写入进程在跑（锁 {int(time.time() - os.path.getmtime(lock_path))} 秒前更新）。确认无并发后删除该锁文件重试。")\n'
    '        sys.exit(1)\n'
    '    open(lock_path, "w").close()\n'
    '\n'
    '    spec = bible_to_spec(book, bible)\n'
    '    state = load_state(book, bible)\n'
    '    client = client_for(bible, "writer", book)'
)
assert old in c, "cmd_write anchor not found"
c = c.replace(old, new, 1)

# 2. draft 写完后释放锁
mark = (
    '    with open(draft_path, "w", encoding="utf-8") as f:\n'
    '        f.write(text)'
)
assert mark in c, "draft write anchor not found"
c = c.replace(mark, mark + '\n    if os.path.exists(lock_path):\n        os.remove(lock_path)', 1)

# 3. books 总览命令
books_cmd = '''

def cmd_books(args):
    """多书总览：列出所有 workspace 的进度。"""
    import time as _t
    if not os.path.isdir(WS_ROOT):
        print("尚无 workspace。先用 new 建书。")
        return
    rows = []
    for name in sorted(os.listdir(WS_ROOT)):
        bp = bible_path(name)
        if not os.path.isfile(bp):
            continue
        try:
            b = json.load(open(bp, encoding="utf-8"))
        except json.JSONDecodeError:
            rows.append((name, "?", "?", "bible 损坏", 0, 0, 0))
            continue
        chs = b.get("chapters", {})
        written = sum(1 for m in chs.values() if m.get("status") in ("written", "drafted", "committed"))
        locked = sum(1 for m in chs.values() if m.get("status") == "locked")
        total = b.get("arc", {}).get("total_chapters", 0)
        lang = b.get("book", {}).get("language", "zh")
        model = b.get("book", {}).get("writer_model") or ("gpt-5.6-terra" if lang == "en" else "glm-5.3-flash")
        rows.append((name, b.get("book", {}).get("title", ""), lang, model, written, locked, total))
    print(f"{'书名':<18} {'标题':<14} {'语':<3} {'writer模型':<16} {'已写':>4} {'已锁':>4} /{'规划':>4}")
    for name, title, lang, model, w, l, t in rows:
        print(f"{name:<18} {title:<14} {lang:<3} {model:<16} {w:>4} {l:>4} /{t:>4}")
    # 活跃写锁提示
    import glob as _g
    locks = _g.glob(os.path.join(WS_ROOT, "*", ".write-lock-*"))
    for lk in locks:
        age = int(_t.time() - os.path.getmtime(lk))
        if age < 3600:
            print(f"  [活跃写锁] {lk}  ({age}s)")

'''
anchor = "\n\ndef main():"
assert anchor in c, "main anchor not found"
c = c.replace(anchor, books_cmd + anchor, 1)
c = c.replace(
    'cmds = {"new": cmd_new, "char": cmd_char, "discuss": cmd_discuss,\n            "lock": cmd_lock, "write": cmd_write, "status": cmd_status}',
    'cmds = {"new": cmd_new, "char": cmd_char, "discuss": cmd_discuss,\n            "lock": cmd_lock, "write": cmd_write, "status": cmd_status, "books": cmd_books}',
    1)

io.open(F, "w", encoding="utf-8").write(c)
print("workbench.py updated: 并发锁 + books 总览")
