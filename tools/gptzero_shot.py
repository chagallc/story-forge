#!/usr/bin/env python3
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
from cdp import evaluate  # noqa: E402
import websocket  # noqa: E402
import base64  # noqa: E402


def screenshot(path):
    page = [t for t in json.load(__import__("urllib.request", fromlist=["urlopen"]).urlopen("http://127.0.0.1:9222/json", timeout=5)) if t.get("type") == "page" and "gptzero" in t.get("url", "")][0]
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


r = evaluate('JSON.stringify({url: location.href.slice(0,80), headline: (function(){var els = document.querySelectorAll("h1, h2, [class*=score], [class*=result]"); return Array.from(els).map(function(e){return e.innerText.trim().slice(0,80)}).filter(Boolean).slice(0,6)})()})', "gptzero")
print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))
print("shot:", screenshot(r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge\output\gptzero-result.png"))
