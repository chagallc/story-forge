#!/usr/bin/env python3
"""读 webgui 页面内容 + 截图（URL 匹配 17890）。"""
import base64
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402
import websocket  # noqa: E402

time.sleep(2)
r = evaluate('JSON.stringify({title: document.title, body: document.body.innerText.slice(0, 500)})', "17890")
res = r.get("result", {})
if "result" in res:
    print(json.dumps(json.loads(res["result"]["value"]), ensure_ascii=False, indent=1))
else:
    print("RAW:", json.dumps(r, ensure_ascii=False)[:400])

pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5))
page = [t for t in pages if t.get("type") == "page" and "17890" in t.get("url", "")][0]
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
try:
    ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == 1:
            with open(r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge\output\webgui-preview.png", "wb") as f:
                f.write(base64.b64decode(msg["result"]["data"]))
            print("shot saved")
            break
finally:
    ws.close()
