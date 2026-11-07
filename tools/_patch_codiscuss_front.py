#!/usr/bin/env python3
"""webgui.html：人物共创讨论板（codiscuss 屏）。

- hash 路由 #/book/<name>/codiscuss
- chat 流（作者/编剧气泡）+ 输入框
- 「提炼人物卡」按钮 → 预览表单（可改）→ 保存进 bible.characters
- 书工作台左栏加「＋人物共创」入口
"""
import io

F = "webgui.html"
c = io.open(F, encoding="utf-8").read()

# ---- 1. 书工作台左栏「＋人物共创」按钮（找「＋新人物」按钮旁边插入）----
anchor_newchar = '"＋ 新人物"'
assert anchor_newchar in c, "new char button not found"
# 找包含它的按钮元素并追加共创按钮：在该按钮的 onclick 赋值行后插入共创按钮创建
# 稳妥做法：搜 "+ 新人物" 的 addBtn 创建模式
import re
m = re.search(r'(\w+)\.textContent = "＋ 新人物";', c)
assert m, "new char button creation not found"
btn_var = m.group(1)
# 找该变量 appendChild 的行
m2 = re.search(re.escape(btn_var) + r'\.onclick = [^\n]+\n', c)
insert_after = c.find(m2.group(0)) + len(m2.group(0))
codiscuss_btn = (
    f'\n    const cd = document.createElement("button");\n'
    f'    cd.className = "btn"; cd.textContent = "✎ 人物共创（讨论板）";\n'
    f'    cd.onclick = () => {{ location.hash = "#/book/{name}/codiscuss"; }};\n'
    f'    ops2.appendChild(cd);'
)
# 找 ops2/append 的容器——简化：直接在 New Scan 按钮同容器 append
# 更稳妥：在该按钮创建后，找它被 append 的容器行
# 最简：在该按钮 onclick 行后插入创建+append（用一个已知存在的容器变量）
# 先看容器名：搜 btn_var 附近的 appendChild
seg = c[insert_after:insert_after + 400]
container_m = re.search(r'(\w+)\.appendChild\(' + re.escape(btn_var) + r'\)', seg)
if container_m:
    cont = container_m.group(1)
    codiscuss_btn += f'\n    {cont}.appendChild(cd);'
    c = c[:insert_after] + "\n    " + codiscuss_btn.strip() + c[insert_after:]
    print(f"codiscuss button wired into {cont}")

# ---- 2. codiscuss 屏（hash 路由 + chat UI + 落卡预览）----
# 找现有 hash 路由分发函数（route()）
rm = re.search(r'function route\(\)\s*\{', c)
assert rm, "route function not found"
# 在 route 里加 codiscuss 分发：匹配 #/book/<name>/codiscuss
route_hook = '''
  const cdMatch = location.hash.match(/^#\\/book\\/([\\w-]+)\\/codiscuss$/);
  if (cdMatch) { renderCodiscuss(cdMatch[1]); return; }
'''
# 插入到 route 函数体内第一个语句前（找 route() { 后第一个换行）
insert_at = rm.end()
# 找 route 函数内的第一个已有分支（找 "if (location.hash" 或 "const m"）——简化：直接在最前面插入
c = c[:insert_at] + route_hook + c[insert_at:]

# ---- 3. renderCodiscuss 函数 + doCodiscussSend + 落卡提取/保存 ----
codiscuss_fn = '''

// ============ 人物共创讨论板 ============
let _cdTurns = [];
let _cdBook = "";

async function renderCodiscuss(book) {
  _cdBook = book;
  const app = document.getElementById("app") || document.body;
  app.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <h2>✎ 人物共创（讨论板）</h2>
      <div style="display:flex;gap:8px">
        <button class="btn" onclick="location.hash='#/book/${book}'">← 返回工作台</button>
        <button class="btn primary" id="cd-extract">📋 提炼人物卡</button>
      </div>
    </div>
    <div id="cd-chat" style="max-width:820px;margin:0 auto"></div>
    <div style="max-width:820px;margin:12px auto;display:flex;gap:8px">
      <input id="cd-input" style="flex:1;font:inherit;padding:8px 12px;border:1px solid #ccc;border-radius:6px"
        placeholder="反馈、修改、深化……（回车发送）" onkeydown="if(event.key==='Enter')cdSend()"/>
      <button class="btn primary" onclick="cdSend()">发送</button>
    </div>
    <div id="cd-save-preview" style="max-width:820px;margin:12px auto"></div>`;
  // 加载已有 session
  try {
    const r = await fetch(`/api/book/${book}/codiscuss`);
    const j = await r.json();
    _cdTurns = j.turns || [];
  } catch { _cdTurns = []; }
  cdRenderTurns();
  if (!_cdTurns.length) {
    cdSendStart();
  }
}

function cdRenderTurns() {
  const chat = document.getElementById("cd-chat");
  if (!chat) return;
  chat.innerHTML = _cdTurns.map(t => {
    const isUser = t.role === "user";
    return `<div style="display:flex;justify-content:${isUser ? "flex-end" : "flex-start"};margin:8px 0">
      <div style="max-width:85%;padding:10px 14px;border-radius:10px;white-space:pre-wrap;font-size:14px;line-height:1.7;
        background:${isUser ? "var(--accent,#2a6bd4)" : "#fff"};color:${isUser ? "#fff" : "inherit"};
        border:${isUser ? "none" : "1px solid #ddd"}">${esc(t.content)}</div>
    </div>`;
  }).join("");
  chat.scrollTop = chat.scrollHeight;
}

async function cdSendStart() {
  const chat = document.getElementById("cd-chat");
  const think = document.createElement("div");
  think.id = "cd-thinking";
  think.style.cssText = "padding:10px;color:#999;font-style:italic";
  think.textContent = "联合编剧阅读设定中……";
  chat.appendChild(think);
  try {
    const r = await fetch(`/api/book/${_cdBook}/codiscuss/start`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({})});
    const j = await r.json();
    _cdTurns = j.turns || [];
  } catch (e) { toast("启动失败：" + e); }
  const th = document.getElementById("cd-thinking");
  if (th) th.remove();
  cdRenderTurns();
}

async function cdSend() {
  const inp = document.getElementById("cd-input");
  const msg = inp ? inp.value.trim() : "";
  if (!msg) return;
  inp.value = "";
  _cdTurns.push({"role": "user", "content": msg});
  cdRenderTurns();
  const chat = document.getElementById("cd-chat");
  const think = document.createElement("div");
  think.id = "cd-thinking";
  think.style.cssText = "padding:10px;color:#999;font-style:italic";
  think.textContent = "编剧思考中……";
  chat.appendChild(think);
  try {
    const r = await fetch(`/api/book/${_cdBook}/codiscuss/message`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: msg})});
    const j = await r.json();
    _cdTurns = j.turns || [];
  } catch (e) { toast("发送失败：" + e); }
  const th = document.getElementById("cd-thinking");
  if (th) th.remove();
  cdRenderTurns();
}

async function cdExtract() {
  const btn = document.getElementById("cd-extract");
  if (btn) { btn.disabled = true; btn.textContent = "提炼中……"; }
  try {
    const r = await fetch(`/api/book/${_cdBook}/codiscuss/extract`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
    const j = await r.json();
    if (!r.ok) { toast(j.error || "提炼失败"); return; }
    cdRenderSavePreview(j.characters || []);
  } catch (e) { toast("提炼失败：" + e); }
  if (btn) { btn.disabled = false; btn.textContent = "📋 提炼人物卡"; }
}

function cdRenderSavePreview(chars) {
  const pv = document.getElementById("cd-save-preview");
  if (!pv) return;
  pv.innerHTML = `
    <div class="pane"><h3>提炼的人物卡预览（${chars.length} 人）——可修改后保存</h3>
    ${chars.map((c, i) => `
      <div style="border:1px solid #ddd;border-radius:8px;padding:10px;margin:8px 0">
        <input class="cd-char-name" data-i="${i}" value="${esc(c.name || "")}" style="font-weight:bold;width:40%;margin-bottom:4px"/>
        <textarea class="cd-char-card" data-i="${i}" rows="2" style="width:100%;box-sizing:border-box">${esc(c.card || "")}</textarea>
        <div class="small">want: <input class="cd-char-want" data-i="${i}" value="${esc(c.want || "")}" style="width:70%"/>
        | fear: <input class="cd-char-fear" data-i="${i}" value="${esc(c.fear || "")}" style="width:40%"/></div>
        <div class="small">contradiction: <input class="cd-char-contradiction" data-i="${i}" value="${esc(c.contradiction || "")}" style="width:80%"/></div>
        <div class="small">口头禅: <input class="cd-char-catch" data-i="${i}" value="${esc((c.voice||{}).catchphrases||[]).join("、")}" style="width:70%"/></div>
      </div>`).join("")}
    <button class="btn primary" id="cd-save-go">💾 保存 ${chars.length} 个人物到 story-bible</button>
    </div>`;
  pv.querySelector("#cd-save-go").onclick = async () => {
    // 从表单回收编辑
    const rows = pv.querySelectorAll(".cd-char-name");
    rows.forEach((inp, idx) => {
      const i = inp.dataset.i;
      const card = pv.querySelector(`.cd-char-card[data-i="${i}"]`);
      if (card) chars[i].card = card.value;
      inp.value && (chars[i].name = inp.value);
    });
    pv.querySelectorAll(".cd-char-want").forEach(inp => { const i = inp.dataset.i; chars[i].want = inp.value; });
    pv.querySelectorAll(".cd-char-fear").forEach(inp => { const i = inp.dataset.i; chars[i].fear = inp.value; });
    pv.querySelectorAll(".cd-char-contradiction").forEach(inp => { const i = inp.dataset.i; chars[i].contradiction = inp.value; });
    pv.querySelectorAll(".cd-char-catch").forEach(inp => {
      const i = inp.dataset.i;
      chars[i].voice = chars[i].voice || {};
      chars[i].voice.catchphrases = inp.value.split("、").map(s => s.trim()).filter(Boolean);
    });
    const r = await fetch(`/api/book/${_cdBook}/codiscuss/save`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({characters: chars})});
    const j = await r.json();
    if (j.ok) { toast(`已保存 ${j.added} 个人物到 story-bible`); pv.innerHTML = ""; }
    else { toast(j.error || "保存失败"); }
  };
}

// cd-extract 按钮绑定（面板渲染后）
const _origCd = renderCodiscuss;
renderCodiscuss = async function(book) {
  await _origCd(book);
  const btn = document.getElementById("cd-extract");
  if (btn) btn.onclick = cdExtract;
};
'''

# 插入 codiscuss_fn 到 </script> 前的第一个（主 script 结束）——找最后一个 </script> 前插
# 简化：插在 body 渲染函数（renderCodiscuss 的调用点在 route 里），函数定义放 route 之前即可
# route 函数定义前插入
route_def = "function route()"
rd = c.find(route_def)
assert rd >= 0, "route def not found"
c = c[:rd] + codiscuss_fn + "\n\n" + c[rd:]

# ---- 5. cdExtract 按钮绑定修正（renderCodiscuss 里绑）----
bind = '''
  const extBtn = document.getElementById("cd-extract");
  if (extBtn) extBtn.onclick = cdExtract;
'''
# 在 renderCodiscuss 的 cdRenderTurns() 后插
old_rc_end = "  cdRenderTurns();\n  if (!_cdTurns.length) {\n    cdSendStart();\n  }\n}"
assert old_rc_end in c, "renderCodiscuss end not found"
c = c.replace(old_rc_end, "  cdRenderTurns();\n" + bind + "  if (!_cdTurns.length) {\n    cdSendStart();\n  }\n}", 1)

io.open(F, "w", encoding="utf-8").write(c)
print("webgui.html codiscuss panel added")
