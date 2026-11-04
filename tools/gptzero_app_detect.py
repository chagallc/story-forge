#!/usr/bin/env python3
"""GPTZero app 版检测（登录态编辑器界面）。

用法：python tools/gptzero_app_detect.py <文本文件> [标签]
"""
import json
import os
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

FIND_EDITOR = """JSON.stringify((function(){
  var ces = document.querySelectorAll('[contenteditable="true"]');
  var out = Array.from(ces).map(function(e){
    var r = e.getBoundingClientRect();
    return {cls: String(e.className).slice(0,60), w: Math.round(r.width), h: Math.round(r.height)};
  });
  return out;
})())"""

SET_TEXT_APP = """
(function(text){
  var ed = document.querySelector('[contenteditable="true"]');
  if (!ed) return 'NO_EDITOR';
  ed.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('insertText', false, text);
  var len = (ed.innerText || '').length;
  return 'SET:' + len;
})(window.__GZ_TEXT__)
"""

CLICK_SCAN_APP = """
(function(){
  var btns = Array.from(document.querySelectorAll('button'));
  for (var b of btns) {
    var t = (b.innerText || '').trim();
    if (t === 'Scan' || t === 'Scan  →' || (t.startsWith('Scan') && t.length < 12)) {
      var r = b.getBoundingClientRect();
      if (r.width > 100) { b.click(); return 'CLICKED:' + t; }
    }
  }
  return 'NO_SCAN';
})();
"""

READ_APP_RESULT = """
(function(){
  var body = document.body.innerText;
  var pct = body.match(/\\d{1,3}(\\.\\d+)?\\s*%/g) || [];
  var aiSent = body.match(/\\d+\\s*(?:of\\s*)?\\d+\\s*(?:sentences?|提示)/i);
  var avg = body.match(/average[^\\n]{0,60}/i) || [];
  return JSON.stringify({pcts: pct.slice(0, 8), aiSentences: aiSent ? aiSent[0] : null, avgLine: avg[0] || null, len: body.length});
})()
"""


def main():
    path = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(path)
    text = open(path, encoding="utf-8").read()
    print(f"[{label}] chars={len(text)} words={len(text.split())}")

    r = evaluate(FIND_EDITOR, "gptzero")
    print("editors:", r["result"]["value"])

    payload = json.dumps(text, ensure_ascii=False)
    evaluate(f"window.__GZ_TEXT__ = {payload}; 'loaded'", "gptzero")

    r = evaluate(SET_TEXT_APP, "gptzero")
    print("set:", r["result"]["value"])
    if "SET:" not in str(r["result"]["value"]):
        sys.exit(1)

    time.sleep(2)
    r = evaluate(CLICK_SCAN_APP, "gptzero")
    print("click:", r["result"]["value"])

    for i in range(36):
        time.sleep(5)
        r = evaluate(READ_APP_RESULT, "gptzero")
        try:
            data = json.loads(r["result"]["value"])
        except Exception:
            continue
        if data.get("pcts") and i > 3:
            print(json.dumps(data, ensure_ascii=False, indent=1))
            break
        if i == 35:
            print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
