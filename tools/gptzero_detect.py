#!/usr/bin/env python3
"""GPTZero 网页版检测驱动。

用法：python tools/gptzero_detect.py <文本文件> [标签]
前置：CDP Chrome 已开 gptzero.me。
"""
import json
import os
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

SET_TEXT = """
(function(text){
  var ta = document.querySelector('textarea');
  if (!ta) return 'NO_TEXTAREA';
  ta.focus();
  var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, text);
  ta.dispatchEvent(new Event('input', {bubbles: true}));
  return 'SET:' + ta.value.length;
})(window.__GZ_TEXT__)
"""

CLICK_SCAN = """
(function(){
  var btns = Array.from(document.querySelectorAll('button'));
  for (var b of btns) {
    var t = (b.innerText || '').trim();
    if (t === 'Scan' || t.startsWith('Scan ')) { b.click(); return 'CLICKED:' + t; }
  }
  return 'NO_SCAN_BUTTON';
})();
"""

READ_RESULT = """
(function(){
  var body = document.body.innerText;
  var pct = body.match(/\\d{1,3}(\\.\\d+)?\\s*%/g) || [];
  var aiWords = body.match(/AI[- ]?[Gg]enerated[^\\n]{0,80}/g) || [];
  var human = body.match(/\\d+\\s*(?:of\\s*)?sentences?[^\\n]{0,60}/g) || [];
  return JSON.stringify({pcts: pct.slice(0, 6), aiSnips: aiWords.slice(0, 3), sentenceSnips: human.slice(0, 3), tail: body.length});
})()
"""


def main():
    path = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(path)
    text = open(path, encoding="utf-8").read()
    print(f"[{label}] chars={len(text)} words={len(text.split())}")

    payload = json.dumps(text, ensure_ascii=False)
    r = evaluate(f"window.__GZ_TEXT__ = {payload}; 'loaded'", "gptzero")
    print("var:", r["result"]["value"])

    r = evaluate(SET_TEXT, "gptzero")
    print("set:", r["result"]["value"])
    if str(r["result"]["value"]).startswith("NO"):
        sys.exit(1)

    time.sleep(1)
    r = evaluate(CLICK_SCAN, "gptzero")
    print("click:", r["result"]["value"])

    # 轮询结果
    for i in range(30):
        time.sleep(5)
        r = evaluate(READ_RESULT, "gptzero")
        try:
            data = json.loads(r["result"]["value"])
        except Exception:
            continue
        # 结果页出现高置信百分比（>0 且非 100 的轮次），或导航到结果页
        if data.get("pcts") and i > 2:
            print(json.dumps(data, ensure_ascii=False, indent=1))
            break
        if i == 29:
            print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
