#!/usr/bin/env python3
"""循环关闭 GPTZero 所有促销弹窗，直到没有可关的。"""
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

CLOSE = """(function(){
  var els = document.querySelectorAll('a, button');
  for (var e of els) {
    var t = (e.innerText || '').toLowerCase();
    if ((t.indexOf('continue free') >= 0 || t.indexOf('pass on') >= 0 || t.indexOf('maybe later') >= 0 || t.indexOf('not now') >= 0) && t.length < 45) {
      var rc = e.getBoundingClientRect();
      if (rc.width > 0 && rc.height > 0) { e.click(); return 'closed:' + t.slice(0, 35); }
    }
  }
  return 'none';
})()"""

for i in range(8):
    r = evaluate(CLOSE, "gptzero")
    v = r["result"]["value"]
    print(i, v)
    if v == "none":
        break
    time.sleep(2)
print("done")
