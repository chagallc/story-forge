#!/usr/bin/env python3
"""截图朱雀页面 + 查通知内容。"""
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate, pick_page  # noqa: E402
import websocket  # noqa: E402
import json  # noqa: E402
import base64  # noqa: E402


def screenshot(path):
    page = pick_page("ai-detect")
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                with open(path, "wb") as f:
                    f.write(base64.b64decode(msg["result"]["data"]))
                return path
    finally:
        ws.close()


evaluate("window.scrollTo(0,0)", "ai-detect")
time.sleep(1)
r = evaluate('JSON.stringify({notif: (function(){var n=document.querySelector(".el-notification__content"); return n? n.innerText.slice(0,150) : null})()})', "ai-detect")
print("notification:", r["result"]["value"])
print("screenshot:", screenshot(r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge\output\zhuque-page.png"))
