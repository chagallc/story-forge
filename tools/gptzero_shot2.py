#!/usr/bin/env python3
"""GPTZero 结果页截图。"""
import base64
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\tools")
import websocket  # noqa: E402


def main():
    time.sleep(2)
    pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5))
    page = [t for t in pages if t.get("type") == "page" and "gptzero" in t.get("url", "")][0]
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                with open(r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge\output\gptzero-result.png", "wb") as f:
                    f.write(base64.b64decode(msg["result"]["data"]))
                print("shot saved")
                return
    finally:
        ws.close()


if __name__ == "__main__":
    main()
