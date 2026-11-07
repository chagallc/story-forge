#!/usr/bin/env python3
"""webgui.html：viewCodiscuss 函数（人物共创 chat 面板 + 落卡预览）。"""
import io

F = "webgui.html"
c = io.open(F, encoding="utf-8").read()

if "async function viewCodiscuss" in c:
    print("already exists")
    raise SystemExit(0)

FN = '''

// ============ 人物共创讨论板 ============
let _cdBook = "";

async function viewCodiscuss(name) {
  _cdBook = name;
  const m = main();
  m.innerHTML = `
    <div class="pane">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <h2 style="margin:0">✎ 人物共创（讨论板）</h2>
      <div style="display:flex;gap:8px">
        <button class="btn sm" id="cd-back">← 返回工作台</button>
        <button class="btn sm primary" id="cd-extract">📋 提炼人物卡</button>
      </div>
    </div>
    <div id="cd-chat" style="max-width:860px;margin:0 auto"></div>
    <div style="max-width:860px;margin:12px auto;display:flex;gap:8px">
      <input id="cd-input" style="flex:1;font:inherit;padding:8px 12px;border:1px solid #ccc;border-radius:6px"
        placeholder="反馈、修改、深化……（回车发送）" onkeydown="if(event.key==='Enter')cdSend()"/>
      <button class="btn primary" onclick="cdSend()">发送</button>
    </div>
    <div id="cd-save-preview" style="max-width:860px;margin:12px auto"></div>
    </div>`;
  m.querySelector("#cd-back").onclick = () => { location.hash = "#/book/" + name; };
  m.querySelector("#cd-extract").onclick = () => cdExtract(name);
  // 加载已有 session
  try {
    const r = await fetch(`/api/book/${name}/codiscuss`);
    const j = await r.json();
    _cdTurns = j.turns || [];
  } catch { _cdTurns = []; }
  cdRenderTurns();
  if (!_cdTurns.length) {
    // 首轮：AI 基于书况自动开场
    const think = document.createElement("div");
    think.id = "cd-thinking";
    think.style.cssText = "padding:10px;color:#999;font-style:italic";
    think.textContent = "联合编剧阅读设定中……";
    document.getElementById("cd-chat").appendChild(think);
    try {
      const r = await fetch(`/api/book/${name}/codiscuss/start`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({})});
      const j = await r.json();
      _cdTurns = j.turns || [];
    } catch (e) { toast("启动失败：" + e); }
    const th = document.getElementById("cd-thinking");
    if (th) th.remove();
    cdRenderTurns();
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

async function cdExtract(book) {
  const btn = document.getElementById("cd-extract");
  if (btn) { btn.disabled = true; btn.textContent = "提炼中……"; }
  try {
    const r = await fetch(`/api/book/${_cdBook}/codiscuss/extract`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
    const j = await r.json();
    if (!r.ok) { toast(j.error || "提炼失败"); return; }
    cdRenderSavePreview(_cdBook, j.characters || []);
  } catch (e) { toast("提炼失败：" + e); }
  if (btn) { btn.disabled = false; btn.textContent = "📋 提炼人物卡"; }
}

function cdRenderSavePreview(book, chars) {
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
        <div class="small">口头禅: <input class="cd-char-catch" data-i="${i}" value="${esc(((c.voice||{}).catchphrases||[]).join("、"))}" style="width:70%"/></div>
      </div>`).join("")}
    <button class="btn primary" id="cd-save-go">💾 保存 ${chars.length} 个人物到 story-bible</button>
    </div>`;
  pv.querySelector("#cd-save-go").onclick = async () => {
    pv.querySelectorAll(".cd-char-name").forEach((inp, idx) => { chars[idx].name = inp.value; });
    pv.querySelectorAll(".cd-char-card").forEach((ta, idx) => { chars[idx].card = ta.value; });
    pv.querySelectorAll(".cd-char-want").forEach(inp => { const i = +inp.dataset.i; chars[i].want = inp.value; });
    pv.querySelectorAll(".cd-char-fear").forEach(inp => { const i = +inp.dataset.i; chars[i].fear = inp.value; });
    pv.querySelectorAll(".cd-char-contradiction").forEach(inp => { const i = +inp.dataset.i; chars[i].contradiction = inp.value; });
    pv.querySelectorAll(".cd-char-catch").forEach(inp => {
      const i = +inp.dataset.i;
      chars[i].voice = chars[i].voice || {};
      chars[i].voice.catchphrases = inp.value.split("、").map(s => s.trim()).filter(Boolean);
    });
    try {
      const r = await fetch(`/api/book/${book}/codiscuss/save`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({characters: chars})});
      const j = await r.json();
      if (j.ok) { toast(`已保存 ${j.added} 个人物到 story-bible`); pv.innerHTML = ""; }
      else { toast(j.error || "保存失败"); }
    } catch (e) { toast("保存失败：" + e); }
  };
}
'''

# 插在 viewCanon 函数定义之后
anchor = "async function viewCanon"
idx = c.find(anchor)
assert idx >= 0, "viewCanon not found"
# 找 viewCanon 函数结束（下一个 async function 或 // ==== 分隔）
end_pat = c.find("\nasync function ", idx + 10)
if end_pat < 0:
    end_pat = c.find("\nfunction ", idx + 10)
c = c[:end_pat] + FN + c[end_pat:]

io.open(F, "w", encoding="utf-8").write(c)
print("viewCodiscuss + helpers added")
