#!/usr/bin/env python3
"""webgui.html：人物共创按钮 + codiscuss 路由 + viewCodiscuss。"""
import io
import re

F = "webgui.html"
c = io.open(F, encoding="utf-8").read()
ok = []

# 1. 顶栏按钮
old_btn = '      <button class="btn sm primary" id="btn-gonewchar">＋ 新人物</button>'
new_btn = old_btn + '\n      <button class="btn sm" id="btn-gocodiscuss">✎ 人物共创</button>'
assert old_btn in c, "btn row missing"
c = c.replace(old_btn, new_btn, 1)
ok.append("top button")

# 2. 按钮事件绑定（找 gonewchar 的绑定行）
mb = re.search(r'\w+[.(]typeof|null\)?[^;]*btn-gonewchar[^;]*;', c)
bind_pat = re.search(r'(byId\(|getElementById\()("btn-gonewchar"\)|' + "'btn-gonewchar'" + r')\)\.onclick', c)
if bind_pat:
    line_end = c.find("\n", bind_pat.end())
    bind_line = c[bind_pat.start():line_end]
    cod_bind = bind_line.replace("btn-gonewchar", "btn-gocodiscuss").replace(
        "UIState.selChar = null; UIState.selChapter = null; drawBook(name, data);",
        'location.hash = "#/book/" + name + "/codiscuss";')
    # 简化：加独立绑定行
    c = c[:line_end + 1] + '  byId("btn-gocodiscuss").onclick = () => { location.hash = "#/book/" + name + "/codiscuss"; };\n' + c[line_end + 1:]
    ok.append("bind")
else:
    # fallback: 找 byId 函数名
    byid = "byId" if "byId(" in c else "document.getElementById"
    c = c.replace(
        "byId" + '("btn-gonewchar").onclick',
        'byId' + '("btn-gonewchar").onclick', 1)
    # 在其行后追加
    idx = c.find('"btn-gonewchar").onclick')
    line_end = c.find("\n", idx)
    c = c[:line_end + 1] + '  byId("btn-gocodiscuss").onclick = () => { location.hash = "#/book/" + name + "/codiscuss"; };\n' + c[line_end + 1:]
    ok.append("bind (fallback)")

# 3. matchRoute 加 codiscuss
old_mr = '  if ((m = h.match(/^#\\/book\\/([^/]+)\\/canon$/))) return {view:"canon", name:m[1]};'
new_mr = old_mr + '\n  if ((m = h.match(/^#\\/book\\/([^/]+)\\/codiscuss$/))) return {view:"codiscuss", name:m[1]};'
assert old_mr in c, "matchRoute anchor missing"
c = c.replace(old_mr, new_mr, 1)
ok.append("matchRoute")

# 4. renderRoute 分发
old_rr = '    else if (r.view==="canon") await viewCanon(r.name);'
new_rr = old_rr + '\n    else if (r.view==="codiscuss") await viewCodiscuss(r.name);'
assert old_rr in c, "renderRoute anchor missing"
c = c.replace(old_rr, new_rr, 1)
ok.append("renderRoute")

io.open(F, "w", encoding="utf-8").write(c)
print("webgui.html wired:", ok)
