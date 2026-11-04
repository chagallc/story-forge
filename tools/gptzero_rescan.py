#!/usr/bin/env python3
"""GPTZero 完整重扫：清空编辑器→全文粘贴→确认字数→Scan→关弹窗→读结果。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
print(f"source chars={len(text)} words={len(text.split())}")

payload = json.dumps(text, ensure_ascii=False)
r = evaluate(f"window.__GZ_TEXT__ = {payload}; 'loaded'", "gptzero")

# 清空 + 分块粘贴（大文本一次性 insertText 可能被截断）
CLEAR_PASTE = """(function(){
  var ed = document.querySelector('[contenteditable="true"]');
  if (!ed) return 'NO_EDITOR';
  ed.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('delete', false, null);
  return 'cleared:' + (ed.innerText || '').length;
})()"""
r = evaluate(CLEAR_PASTE, "gptzero")
print(r["result"]["value"])

CHUNK_PASTE = """(function(chunk){
  var ed = document.querySelector('[contenteditable="true"]');
  ed.focus();
  document.execCommand('insertText', false, chunk);
  return 'ok';
})(window.__GZ_CHUNK__)"""

chunks = []
size = 2000
for i in range(0, len(text), size):
    chunks.append(text[i:i + size])
print(f"pasting {len(chunks)} chunks ...")
for i, chunk in enumerate(chunks):
    r = evaluate(f"window.__GZ_CHUNK__ = {json.dumps(chunk, ensure_ascii=False)}; 'ready'", "gptzero")
    r = evaluate(CHUNK_PASTE, "gptzero")
    time.sleep(0.3)

time.sleep(2)
r = evaluate('JSON.stringify({editorLen: (document.querySelector("[contenteditable=true]")||{innerText:""}).innerText.length, wordCount: (document.body.innerText.match(/\\d+,?\\d* characters/) || ["?"])[0]})', "gptzero")
print("editor state:", r["result"]["value"])

# Scan
SCAN = """(function(){
  var btns = Array.from(document.querySelectorAll('button'));
  for (var b of btns) {
    var r = b.getBoundingClientRect();
    var t = (b.innerText || '').trim();
    if (t === 'Scan' && r.width > 100) { b.click(); return 'CLICKED'; }
  }
  return 'NO_SCAN';
})()"""
r = evaluate(SCAN, "gptzero")
print("scan:", r["result"]["value"])

# 等 + 关弹窗 + 读结果
for i in range(24):
    time.sleep(5)
    r = evaluate("""(function(){
      var els = document.querySelectorAll('a, button');
      for (var e of els) {
        var t = (e.innerText || '').toLowerCase();
        if (t.indexOf('continue free') >= 0) { e.click(); return 'popup-closed'; }
      }
      return 'no-popup';
    })()""", "gptzero")
    state = r["result"]["value"]
    r = evaluate("""JSON.stringify((function(){
      var body = document.body.innerText;
      var m = body.match(/\\d{1,3}(\\.\\d+)?\\s*%\\s*(?:probability|AI)/i);
      var words = body.match(/\\d+\\s+words?/i);
      return {aiProb: m ? m[0] : null, words: words ? words[0] : null};
    })())""", "gptzero")
    data = json.loads(r["result"]["value"])
    if data.get("aiProb") and data.get("words") and int("".join(c for c in data["words"] if c.isdigit())) > 1000:
        print("RESULT:", json.dumps(data, ensure_ascii=False))
        break
    if i == 23:
        print("FINAL:", json.dumps(data, ensure_ascii=False))
    else:
        print(f"  [{i}] {state} {json.dumps(data)}")
