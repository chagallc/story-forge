#!/usr/bin/env python3
"""探查朱雀页面的输入区结构。"""
import json
import sys

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

PROBE = """JSON.stringify((function(){
  var out = {frames: []};
  document.querySelectorAll('iframe').forEach(function(f){
    var accessible = false, inner = '';
    try { inner = f.contentDocument.body.innerText.slice(0,150); accessible = true; } catch(e) { inner = 'CROSS-ORIGIN: ' + e.message.slice(0,40); }
    out.frames.push({src: (f.src||'').slice(0,100), accessible: accessible, inner: inner});
  });
  // 全页可聚焦元素
  var focusables = [];
  document.querySelectorAll('*').forEach(function(el){
    var st = getComputedStyle(el);
    if ((st.userSelect !== 'none') && el.children.length === 0 && el.offsetParent !== null) {
      var t = (el.tagName + '.' + String(el.className).slice(0,40));
      if (focusables.length < 20) focusables.push(t);
    }
  });
  out.leafEls = focusables;
  return out;
})())"""

r = evaluate(PROBE, "ai-detect")
v = r.get("result", {}).get("value") if isinstance(r.get("result"), dict) else None
if v is None:
    print("RAW:", json.dumps(r, ensure_ascii=False)[:800])
else:
    data = json.loads(v)
    print(json.dumps(data, ensure_ascii=False, indent=1)[:2000])
