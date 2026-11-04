#!/usr/bin/env python3
"""关闭升级弹窗，读取背景中的扫描结果。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

# 点 X 关闭
r = evaluate("""(function(){
  var closes = document.querySelectorAll('[aria-label*=Close], [class*=close], svg[class*=close], button');
  for (var e of closes) {
    var r = e.getBoundingClientRect();
    // 弹窗右上角的 X 通常在屏幕上部右侧
    if (r.top > 50 && r.top < 130 && r.left > 1000) { e.click(); return 'closed-x:' + Math.round(r.left) + ',' + Math.round(r.top); }
  }
  // 或按 ESC
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  return 'esc-sent';
})()""", "gptzero")
print("close:", r["result"]["value"])
time.sleep(2)

# 读取页面上所有百分比和关键信息
r = evaluate("""JSON.stringify((function(){
  var body = document.body.innerText;
  var out = {};
  out.pcts = (body.match(/\\d{1,3}(\\.\\d+)?\\s*%/g) || []).slice(0, 12);
  var m = body.match(/\\d{1,3}\\s*%[^\\n]{0,60}(?:AI|artificial)/i) || body.match(/(?:AI|artificial)[^\\n%]{0,50}\\d{1,3}\\s*%/i);
  out.aiLine = m ? m[0] : null;
  out.hasHighlight = document.querySelectorAll('[class*=highlight], [class*=sentence], mark').length;
  var scoreEls = document.querySelectorAll('[class*=score], [class*=prob], [class*=gauge]');
  out.scoreEls = Array.from(scoreEls).map(function(e){ return (e.innerText||'').trim().slice(0, 40).replace(/\\n/g, ' '); }).filter(Boolean).slice(0, 5);
  return out;
})())""", "gptzero")
print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
