#!/usr/bin/env python3
"""GPTZero 页面探查：cookie 弹窗、登录状态、输入框。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402

# 1. 关 cookie 弹窗
evaluate("""(function(){
  var btns = Array.from(document.querySelectorAll('button, a'));
  for (var b of btns) {
    var t = (b.innerText || '').trim();
    if (t === 'Accept' || t === 'Accept all' || t === 'I Accept') { b.click(); return 'accepted'; }
  }
  return 'no-banner';
})()""", "gptzero")
time.sleep(1)

# 2. 探查
r = evaluate("""JSON.stringify((function(){
  var out = {};
  var tas = document.querySelectorAll('textarea');
  out.textareas = Array.from(tas).map(function(t){var r = t.getBoundingClientRect(); return {ph: (t.placeholder||'').slice(0,60), w: Math.round(r.width), h: Math.round(r.height)}});
  var ces = document.querySelectorAll('[contenteditable="true"]');
  out.editables = ces.length;
  var loginish = [];
  document.querySelectorAll('a, button').forEach(function(el){
    var t = (el.innerText||'').trim();
    if (/sign in|log in|sign up|dashboard/i.test(t) && t.length < 30) loginish.push(t);
  });
  out.loginLinks = loginish.slice(0, 6);
  var detectBtn = [];
  document.querySelectorAll('button').forEach(function(el){
    var t = (el.innerText||'').trim();
    if (/detect|scan|check|get results/i.test(t) && t.length < 40) detectBtn.push(t);
  });
  out.detectButtons = detectBtn.slice(0, 6);
  return out;
})())""", "gptzero")
print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
