#!/usr/bin/env python3
"""关闭 GPTZero 促销弹窗并读取扫描结果。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

CLOSE_JS = """(function(){
  var els = document.querySelectorAll('a, button');
  for (var e of els) {
    var t = (e.innerText || '').toLowerCase();
    if (t.indexOf('continue free') >= 0 || t.indexOf('pass on premium') >= 0) { e.click(); return 'closed'; }
  }
  return 'not-found';
})()"""

READ_JS = """JSON.stringify((function(){
  var body = document.body.innerText;
  var out = {};
  var aiProb = body.match(/\\d{1,3}(\\.\\d+)?\\s*%\\s*(?:probability|AI)/i) || body.match(/(?:probability|AI)[^\\n]{0,30}\\d{1,3}(\\.\\d+)?\\s*%/i);
  out.aiProb = aiProb ? aiProb[0] : null;
  out.pcts = (body.match(/\\d{1,3}(\\.\\d+)?\\s*%/g) || []).slice(0, 10);
  var sents = body.match(/\\d+\\s+of\\s+\\d+\\s+sentences[^\\n]{0,60}/i);
  out.sentences = sents ? sents[0] : null;
  var words = body.match(/\\d+\\s+words? detected[^\\n]{0,40}/i) || body.match(/\\d+\\s+words?/i);
  out.words = words ? words[0] : null;
  return out;
})())"""

r = evaluate(CLOSE_JS, "gptzero")
print("close:", r["result"]["value"])
time.sleep(3)
r = evaluate(READ_JS, "gptzero")
try:
    print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
except Exception:
    print(json.dumps(r, ensure_ascii=False)[:500])
