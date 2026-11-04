#!/usr/bin/env python3
"""切到 AI detection 主 tab 并读取结果。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

# 顶部 tab 组：第一个（图标无文字的）是 AI detection 主结果
CLICK_TAB = """(function(){
  var tabs = document.querySelectorAll('button, [role=tab]');
  var scored = [];
  for (var e of tabs) {
    var r = e.getBoundingClientRect();
    if (r.top > 60 && r.top < 130 && r.width > 60 && r.height > 30 && r.width < 220) {
      scored.push({t: (e.innerText || '(icon)').trim().slice(0, 20), x: Math.round(r.left), el: e});
    }
  }
  scored.sort(function(a, b){ return a.x - b.x; });
  if (scored.length) { scored[0].el.click(); return 'clicked:' + scored[0].t + '@x' + scored[0].x; }
  return 'no-tab';
})()"""

r = evaluate(CLICK_TAB, "gptzero")
print("tab:", r["result"]["value"])
time.sleep(3)

r = evaluate("""JSON.stringify((function(){
  var body = document.body.innerText;
  var out = {};
  out.pcts = (body.match(/\\d{1,3}(\\.\\d+)?\\s*%/g) || []).slice(0, 12);
  var m = body.match(/\\d{1,3}(\\.\\d+)?\\s*%[^\\n]{0,50}(?:probability|AI|generated|human)/i);
  out.aiLine = m ? m[0].slice(0, 80) : null;
  var s = body.match(/\\d+\\s+of\\s+\\d+\\s+sentences?[^\\n]{0,60}/i);
  out.sentences = s ? s[0] : null;
  return out;
})())""", "gptzero")
print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
