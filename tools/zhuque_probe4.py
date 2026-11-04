#!/usr/bin/env python3
"""定位朱雀输入框：找包含示例文本的元素，检查其可编辑性。"""
import json
import sys

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

PROBE = """JSON.stringify((function(){
  var els = document.querySelectorAll('div, p, section');
  var hits = [];
  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    if (el.children.length === 0 && el.innerText && el.innerText.indexOf('穿上了那件我极熟识') >= 0) {
      var chain = [];
      var cur = el;
      for (var j = 0; j < 5 && cur; j++) {
        chain.push({tag: cur.tagName, cls: String(cur.className).slice(0, 60), ce: cur.isContentEditable, tabidx: cur.tabIndex, role: cur.getAttribute('role')});
        cur = cur.parentElement;
      }
      hits.push(chain);
      break;
    }
  }
  return {found: hits.length > 0, chain: hits[0] || null};
})())"""

r = evaluate(PROBE, "ai-detect")
print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
