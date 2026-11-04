#!/usr/bin/env python3
"""GPTZero 全流程：新扫描 → 注入 → Scan → 关弹窗 → 读结果。

用法：python tools/gptzero_fullflow.py <文本文件>
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

path = sys.argv[1]
label = os.path.basename(path)
text = open(path, encoding="utf-8").read()
print(f"[{label}] chars={len(text)} words={len(text.split())}")

# 1. 导航到 app 新扫描
evaluate("location.href = 'https://app.gptzero.me/'", "gptzero")
time.sleep(6)

# 2. 点 New Scan（如果有的话）
r = evaluate("""(function(){
  var els = document.querySelectorAll('button, a, div');
  for (var e of els) {
    var t = (e.innerText || '').trim();
    if (t === 'New Scan' || t.indexOf('New Scan') === 0) { e.click(); return 'new-scan'; }
  }
  return 'already-editor';
})()""", "gptzero")
print("new-scan:", r["result"]["value"])
time.sleep(3)

# 3. 分块注入
payload = json.dumps(text, ensure_ascii=False)
evaluate(f"window.__GZ_TEXT__ = {payload}; 'loaded'", "gptzero")

r = evaluate("""(function(text){
  var ed = document.querySelector('[contenteditable="true"]');
  if (!ed) return 'NO_EDITOR';
  ed.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('delete', false, null);
  return 'cleared';
})(window.__GZ_TEXT__)""", "gptzero")
print("clear:", r["result"]["value"])

size = 1800
ok = 0
for i in range(0, len(text), size):
    chunk = text[i:i + size]
    evaluate(f"window.__C__ = {json.dumps(chunk, ensure_ascii=False)}; 1", "gptzero")
    r = evaluate("""(function(c){
      var ed = document.querySelector('[contenteditable="true"]');
      ed.focus();
      document.execCommand('insertText', false, c);
      return 'ok';
    })(window.__C__)""", "gptzero")
    if str(r["result"]["value"]) == "ok":
        ok += 1
    time.sleep(0.3)
print(f"chunks pasted: {ok}")

time.sleep(2)
r = evaluate('JSON.stringify({len: (document.querySelector("[contenteditable=true]")||{innerText:""}).innerText.length})', "gptzero")
print("editor len:", r["result"]["value"])

# 4. Scan（循环关弹窗 + 点 Scan）
for attempt in range(4):
    evaluate("""(function(){
      var kws = ['maybe later', 'continue free', 'pass on premium', 'skip', 'not now'];
      var els = document.querySelectorAll('a, button, span');
      for (var e of els) {
        var t = (e.innerText || '').trim().toLowerCase();
        for (var k of kws) {
          if (t && t.indexOf(k) >= 0 && t.length < 40) {
            var r = e.getBoundingClientRect();
            if (r.width > 0) { e.click(); return; }
          }
        }
      }
    })()""", "gptzero")
    time.sleep(1)
    r = evaluate("""(function(){
      var btns = Array.from(document.querySelectorAll('button'));
      for (var b of btns) {
        var t = (b.innerText || '').trim();
        var r = b.getBoundingClientRect();
        if (t.indexOf('Scan') === 0 && t.length < 15 && r.width > 80 && r.height > 30) { b.click(); return 'CLICKED:' + t; }
      }
      return 'NO_SCAN';
    })()""", "gptzero")
    scan = r["result"]["value"]
    print(f"scan attempt {attempt}: {scan}")
    if scan.startswith("CLICKED"):
        break
    time.sleep(2)

# 5. 轮询读结果
final = None
for i in range(30):
    time.sleep(5)
    evaluate("""(function(){
      var kws = ['maybe later', 'continue free', 'pass on premium'];
      var els = document.querySelectorAll('a, button');
      for (var e of els) {
        var t = (e.innerText || '').trim().toLowerCase();
        for (var k of kws) { if (t.indexOf(k) >= 0 && t.length < 40) { var r = e.getBoundingClientRect(); if (r.width > 0) { e.click(); return; } } }
      }
    })()""", "gptzero")
    r = evaluate("""JSON.stringify((function(){
      var body = document.body.innerText;
      var m = body.match(/\\d{1,3}(\\.\\d+)?\\s*%\\s*(?:probability|AI)/i) || body.match(/AI[- ]generated[^\\n]{0,50}\\d{1,3}\\s*%/i);
      var words = body.match(/\\d{3,}\\s+words?/i);
      return {aiProb: m ? m[0] : null, words: words ? words[0] : null};
    })())""", "gptzero")
    try:
        data = json.loads(r["result"]["value"])
    except Exception:
        continue
    if data.get("aiProb") and data.get("words"):
        final = data
        print("RESULT:", json.dumps(data, ensure_ascii=False))
        break
    if i % 3 == 0:
        print(f"  [{i}] {json.dumps(data)}")

if not final:
    print("RESULT: not captured")
