#!/usr/bin/env python3
"""GPTZero 弹窗通吃 + Scan + 读结果（在已注入文本的编辑器上运行）。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

DISMISS_JS = """(function(){
  var killed = [];
  // 弹窗内可点击的跳过项
  var keywords = ['maybe later', 'continue free', 'pass on premium', 'skip', 'not now'];
  var els = document.querySelectorAll('a, button, span');
  for (var e of els) {
    var t = (e.innerText || '').trim().toLowerCase();
    for (var k of keywords) {
      if (t === k || t.indexOf(k) >= 0 && t.length < 40) {
        var r = e.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) { e.click(); killed.push(t); break; }
      }
    }
  }
  return killed.length ? killed.join('|') : 'none';
})()"""

SCAN_JS = """(function(){
  var btns = Array.from(document.querySelectorAll('button'));
  for (var b of btns) {
    var t = (b.innerText || '').trim();
    var r = b.getBoundingClientRect();
    if ((t === 'Scan' || t === 'Scan →' || t.indexOf('Scan') === 0 && t.length < 15) && r.width > 80 && r.height > 30) {
      b.click();
      return 'CLICKED:' + t + ':' + Math.round(r.width) + 'x' + Math.round(r.height);
    }
  }
  return 'NO_SCAN';
})()"""

RESULT_JS = """JSON.stringify((function(){
  var body = document.body.innerText;
  var out = {};
  var m = body.match(/\\d{1,3}(\\.\\d+)?\\s*%\\s*(?:probability|AI)/i) || body.match(/AI\\s*(?:probability|detection)[^\\n%]{0,40}\\d{1,3}(\\.\\d+)?\\s*%/i);
  out.aiProb = m ? m[0] : null;
  var words = body.match(/\\d{3,}\\s+words?/i);
  out.words = words ? words[0] : null;
  return out;
})())"""

for round_no in range(3):
    r = evaluate(DISMISS_JS, "gptzero")
    print(f"[{round_no}] dismiss:", r["result"]["value"])
    time.sleep(1)
    r = evaluate(SCAN_JS, "gptzero")
    scan = r["result"]["value"]
    print(f"[{round_no}] scan:", scan)
    if scan.startswith("CLICKED"):
        break
    time.sleep(1)

# 轮询结果
final = None
for i in range(30):
    time.sleep(5)
    evaluate(DISMISS_JS, "gptzero")
    r = evaluate(RESULT_JS, "gptzero")
    try:
        data = json.loads(r["result"]["value"])
    except Exception:
        continue
    if data.get("aiProb") and data.get("words"):
        final = data
        print("RESULT:", json.dumps(data, ensure_ascii=False))
        break
    if i % 4 == 0:
        print(f"  [{i}] {json.dumps(data)}")

if not final:
    print("no result captured; may need manual check")
