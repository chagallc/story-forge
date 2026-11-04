#!/usr/bin/env python3
"""朱雀 AI 检测驱动：通过 CDP Chrome 自动粘贴文本并检测。

用法：python tools/zhuque_detect.py <文本文件路径> [标签]
输出：JSON 结果（AI 含量、命中率等），并保存截图。
前置：CDP Chrome 已运行（remote-debugging-port=9222），朱雀页面已打开。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools"))
from cdp import evaluate, pick_page  # noqa: E402  # OH-WorkSpace/tools/cdp.py

SET_TEXT_JS = """
(function(text){
  // 找输入区：textarea / contenteditable / 富文本编辑器都试
  var el = document.querySelector('textarea')
        || document.querySelector('.ql-editor')
        || document.querySelector('.ProseMirror')
        || document.querySelector('[contenteditable="true"]')
        || document.querySelector('[contenteditable]')
        || document.querySelector('.editor, [class*=editor] [class*=input], [class*=textarea]');
  if (!el) return 'NO_EDITOR';
  el.focus();
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    var proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value') ? el : null;
    el.value = text;
    el.dispatchEvent(new Event('input', {bubbles: true}));
  } else {
    // contenteditable / 富文本：粘贴级插入
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, text);
  }
  return 'SET:' + (el.innerText || el.value || '').length;
})(window.__DETECT_TEXT__)
"""

CLICK_DETECT_JS = """
(function(){
  var btns = Array.from(document.querySelectorAll('button, div[class*=btn], a'));
  for (var b of btns) {
    var t = (b.innerText || '').replace(/\\s+/g, '');
    if (t.includes('立即检测')) { b.click(); return 'CLICKED:' + t; }
  }
  return 'NO_BUTTON';
})();
"""

READ_RESULT_JS = """
(function(){
  var body = document.body.innerText;
  var m = body.match(/(AI|人)[^\\n]{0,30}(含量|比例|生成|创作)[^\\n]{0,40}/g) || [];
  var pct = body.match(/\\d{1,3}(\\.\\d+)?\\s*%/g) || [];
  return JSON.stringify({snips: m.slice(0, 8), pcts: pct.slice(0, 8), tail: body.slice(-600)});
})()
"""


def _val(r):
    """从 cdp.evaluate 返回值中安全取 value。"""
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return f"JS_ERROR: {json.dumps(res['exceptionDetails'], ensure_ascii=False)[:200]}"
    return res.get("result", res).get("value") if isinstance(res.get("result"), dict) else res.get("value")
def main():
    path = sys.argv[1]
    label = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(path)
    text = open(path, encoding="utf-8").read()
    print(f"[{label}] 文本长度: {len(text)} 字符")

    # 文本通过 window 变量传入，绕开转义问题
    payload = json.dumps(text, ensure_ascii=False)
    r = evaluate(f"window.__DETECT_TEXT__ = {payload}; 'loaded'", "ai-detect")
    print("set-text-var:", _val(r))

    r = evaluate(SET_TEXT_JS, "ai-detect")
    print("set-text:", _val(r))

    time.sleep(1)
    r = evaluate(CLICK_DETECT_JS, "ai-detect")
    print("click:", _val(r))

    # 轮询结果（检测一般 5-20 秒）
    result = None
    for i in range(24):
        time.sleep(5)
        r = evaluate(READ_RESULT_JS, "ai-detect")
        try:
            data = json.loads(_val(r))
        except Exception:
            continue
        # 检测完成后页面会出现百分比；出现即返回
        if data.get("pcts"):
            result = data
            break
        if i == 23:
            result = data

    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
