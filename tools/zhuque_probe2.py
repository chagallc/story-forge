#!/usr/bin/env python3
import json
import sys

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

PROBE = """JSON.stringify((function(){
  var out = {};
  var un = document.querySelector('.user-name');
  out.userName = un ? un.innerText : null;
  var loginBtn = null;
  document.querySelectorAll('button, div, span, a').forEach(function(el){
    if (el.children.length === 0 && el.innerText && el.innerText.trim() === '登录') loginBtn = true;
  });
  out.hasLoginText = !!loginBtn;
  var cands = [];
  document.querySelectorAll('div, section').forEach(function(el){
    var cls = String(el.className || '');
    if (/input|edit|content|text|area/i.test(cls) && el.offsetParent !== null) {
      var r = el.getBoundingClientRect();
      if (r.width > 200 && r.height > 60) cands.push({cls: cls.slice(0,60), w: Math.round(r.width), h: Math.round(r.height), ce: el.isContentEditable, tag: el.tagName});
    }
  });
  out.candidates = cands.slice(0, 10);
  return out;
})())"""

r = evaluate(PROBE, "ai-detect")
v = r.get("result", {}).get("value")
print(json.dumps(json.loads(v), ensure_ascii=False, indent=1))
