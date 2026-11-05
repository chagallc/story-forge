#!/usr/bin/env python3
"""webgui.html 前端：drafts 微调按钮 + 审核徽标 + 微调模态 + doRevise 函数。"""
import io

F = "webgui.html"
c = io.open(F, encoding="utf-8").read()

# ---- 1. 草稿条目：audit 徽标 ----
old1 = (
    '          lint：${flags.length?esc(flags.join("、")):"clean"}\n'
    '          ${d.delta_ops!=null?` · 提案 ${d.delta_ops} ops`:""}'
)
new1 = (
    '          lint：${flags.length?esc(flags.join("、")):"clean"}\n'
    '          ${d.delta_ops!=null?` · 提案 ${d.delta_ops} ops`:""}\n'
    '          ${d.report&&d.report.audit?` · <span class="tag">${esc(String(d.report.audit.issues&&d.report.audit.issues.length?"⚠ 合理性 "+d.report.audit.issues.length+" 项":"✅ 审核"))}</span>`:""}'
)
assert old1 in c, "draft badge anchor missing"
c = c.replace(old1, new1, 1)

# ---- 2. 微调按钮（drafted 状态操作区）----
old2 = (
    '''    if (c.status==="drafted"){
      const cm = document.createElement("button");
      cm.className = "btn danger"; cm.id = "mc-commit";
      cm.textContent = "⬆ 提交正史";
      cm.onclick = ()=>doCommit(name, c.chapter);
      ops.appendChild(cm);
    }'''
)
new2 = (
    '''    if (c.status==="drafted"){
      const rv = document.createElement("button");
      rv.className = "btn"; rv.id = "mc-revise";
      rv.textContent = "✎ 微调剧情";
      rv.onclick = ()=>openReviseModal(name, c.chapter, c.drafts);
      ops.appendChild(rv);
      const cm = document.createElement("button");
      cm.className = "btn danger"; cm.id = "mc-commit";
      cm.textContent = "⬆ 提交正史";
      cm.onclick = ()=>doCommit(name, c.chapter);
      ops.appendChild(cm);
    }'''
)
assert old2 in c, "drafted ops anchor missing"
c = c.replace(old2, new2, 1)

# ---- 3. doRevise + 微调模态（挂在 doWrite 附近；找 doWrite 定义插入之后）----
m = io.search = None
import re
dm = re.search(r'(async )?function doWrite\([^)]*\)\s*\{', c)
assert dm, "doWrite not found"
insert_pos = dm.end()
revise_js = '''

async function doRevise(name, ch, baseVersion, intent) {
  if (!intent || !intent.trim()) { toast("请填写微调意图"); return; }
  const cover = document.createElement("div");
  cover.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:999;display:flex;align-items:center;justify-content:center;color:#fff;font-size:15px";
  cover.textContent = "微调修订中（两次 LLM 调用：定向修订 + 状态提案重提炼）…";
  document.body.appendChild(cover);
  try {
    const r = await fetch(`/api/book/${name}/revise/${ch}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({intent: intent.trim(), base_version: baseVersion || undefined})
    });
    const j = await r.json();
    if (!r.ok) { toast(j.error || ("HTTP " + r.status)); return; }
    toast(`微调完成：新版本 ${j.version}（基于 ${j.base_version || "最新"}）`);
    const a = j.audit || {};
    if (a.issues && a.issues.length) {
      console.log("合理性审核 issues：", a.issues);
    }
    await refreshRoute();
  } catch (e) { toast("微调失败：" + e); }
  finally { cover.remove(); }
}

function openReviseModal(name, ch, drafts) {
  const latest = drafts && drafts.length ? drafts[drafts.length - 1].version : "";
  const modal = document.createElement("div");
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:998;display:flex;align-items:center;justify-content:center";
  modal.innerHTML = `
    <div style="background:var(--bg,#faf7f2);color:var(--fg,#222);border-radius:10px;padding:22px;width:min(560px,92vw);max-height:86vh;overflow:auto">
      <h3>✎ 微调剧情 — 第 ${ch} 章</h3>
      <p class="small muted">基于版本：<b class="mono">${esc(latest)}</b> 定向修订，产出新版本（不覆盖旧版）。只改意图涉及的部分，其余逐字保留。</p>
      <textarea id="rv-intent" rows="4" style="width:100%;box-sizing:border-box;font:inherit"
        placeholder="例：贺三刀摊牌太早，把威胁改到章末收账人出现之后再发生；陆小满的反应从硬顶改成虚与委蛇"></textarea>
      <div class="small muted" style="margin-top:6px">微调后自动重提炼状态提案并跑合理性审核（审核结果在草稿列表查看）。</div>
      <div style="display:flex;gap:10px;margin-top:14px;justify-content:flex-end">
        <button class="btn" id="rv-cancel">取消</button>
        <button class="btn primary" id="rv-go">✎ 修订出新版</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector("#rv-cancel").onclick = () => modal.remove();
  modal.querySelector("#rv-go").onclick = async () => {
    const intent = modal.querySelector("#rv-intent").value.trim();
    if (!intent) { toast("请填写微调意图"); return; }
    modal.remove();
    await doRevise(name, ch, latest, intent);
  };
}'''
c = c[:insert_pos] + revise_js + c[insert_pos:]

# ---- 4. drafts 条目：微调入口也需要 report.audit 在 GET chapter 数据里（后端 chapter_status_view 已含 drafts？确认在后端补）----
io.open(F, "w", encoding="utf-8").write(c)
print("webgui.html patched: badge + revise button + modal + doRevise")
