#!/usr/bin/env python3
"""从 Scans 历史打开最近文档，读 AI 检测结果。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

# 点左栏 Scans
r = evaluate("""(function(){
  var els = document.querySelectorAll('button, a, div');
  for (var e of els) {
    var t = (e.innerText || '').trim();
    if (t === 'Scans') { e.click(); return 'clicked-scans'; }
  }
  return 'not-found';
})()""", "gptzero")
print("scans:", r["result"]["value"])
time.sleep(3)

# 找最近的文档（标题包含 Kesh/wheel 的）并打开
r = evaluate("""JSON.stringify((function(){
  var items = [];
  document.querySelectorAll('a, button, [class*=scan], [class*=document], [class*=row]').forEach(function(e){
    var t = (e.innerText || '').trim();
    if (t.indexOf('wheel threw sparks') >= 0 || t.indexOf('Kesh') >= 0) {
      var r = e.getBoundingClientRect();
      if (r.width > 100) items.push({t: t.slice(0, 60), w: Math.round(r.width), h: Math.round(r.height), tag: e.tagName});
    }
  });
  return items.slice(0, 5);
})())""", "gptzero")
items = json.loads(r["result"]["value"])
print("history items:", json.dumps(items, ensure_ascii=False, indent=1))

if items:
    OPEN = """(function(){
      var els = document.querySelectorAll('a, button, [class*=scan], [class*=document], [class*=row]');
      for (var e of els) {
        var t = (e.innerText || '').trim();
        if ((t.indexOf('wheel threw sparks') >= 0 || t.indexOf('Kesh') >= 0) && e.getBoundingClientRect().width > 100) { e.click(); return 'opened'; }
      }
      return 'fail';
    })()"""
    r = evaluate(OPEN, "gptzero")
    print("open:", r["result"]["value"])
    time.sleep(5)

# 读取结果：找 AI 概率大数字
r = evaluate("""JSON.stringify((function(){
  var body = document.body.innerText;
  var out = {};
  out.pcts = (body.match(/\\d{1,3}(\\.\\d+)?\\s*%/g) || []).slice(0, 12);
  var m = body.match(/\\d{1,3}(\\.\\d+)?\\s*%[^\\n]{0,60}(?:AI|probability|generated|human)/i) || body.match(/(?:probability|generated)[^\\n%]{0,60}\\d{1,3}(\\.\\d+)?\\s*%/i);
  out.aiLine = m ? m[0].slice(0, 100) : null;
  var s = body.match(/\\d+\\s+of\\s+\\d+\\s+sentences?/i);
  out.sentences = s ? s[0] : null;
  return out;
})())""", "gptzero")
print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
