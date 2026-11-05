#!/usr/bin/env python3
"""直接复现 api_revise 的 revise_core 调用，抓完整栈。"""
import sys
import traceback

sys.path.insert(0, r"C:\Users\Lucia Zou\Desktop\OH-WorkSpace\story-forge-webgui")
import workbench as wb  # noqa: E402

log_lines = []
try:
    result = wb.revise_core(
        "webgui-smoke", 1,
        "测试微调：把贺三刀的威胁挪到章末",
        base_version="v001",
        log=log_lines)
    print("OK version:", result["version"])
    print("audit:", result.get("audit"))
    for line in log_lines:
        print("log:", line)
except Exception:
    traceback.print_exc()
