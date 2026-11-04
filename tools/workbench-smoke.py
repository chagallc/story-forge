#!/usr/bin/env python3
"""工作台冒烟测试：建书 → 人物卡 → 讨论(REPL 自动输入 lock) → lock → write 1 章。

全流程验证 story-bible → spec 适配 → E 臂落笔管线。
"""
import json
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import workbench as wb  # noqa: E402

BOOK = "smoke-wb"

# 1. 建 workspace（直接构造，跳过交互）
if not os.path.exists(wb.bible_path(BOOK)):
    d = wb.ws_dir(BOOK)
    os.makedirs(os.path.join(d, "chapters"), exist_ok=True)
    os.makedirs(os.path.join(d, "discussions"), exist_ok=True)
    bible = {
        "book": {"title": "雾锁九门", "genre": "都市悬疑", "language": "zh", "platform": "qidian",
                 "logline": "典当行学徒发现每件死当品里都住着一个未完成的执念，而最新的一件，是他失踪师父的怀表。"},
        "opening_contract": {"want_visible_by": 1500, "disturbance_in_ch1": True,
                             "dialogue_ratio_min": 0.40, "no_info_dump": True, "notes": "0005"},
        "characters": [
            {"name": "陆小满", "card": "24岁，九门典当行学徒，眼力毒，嘴更快。",
             "want": "赎回师父留下的怀表，弄清他失踪那晚去了哪",
             "need": "承认师父可能自己有秘密，而非只有受害者叙事",
             "wound": "孤儿，师父是唯一给过他姓氏的人",
             "value": "当铺规矩：死当不问来路——但他今天想破例",
             "fear": "师父是自愿消失的，根本没打算带上他",
             "contradiction": "守规矩的学徒要做一行里最破规矩的事",
             "voice": {"catchphrases": ["按规矩说", "这物件不干净"], "speech_habits": ["短句", "先报价后说话"],
                       "sample_line": "按规矩说，死当不问来路。"}},
            {"name": "贺三刀", "card": "55岁，行会老理事，笑面，账算得极清。",
             "want": "把九门典当行并进行会统一管理",
             "need": "挽回三十年前他亲手做砸的一桩局",
             "wound": "当年他师父也是这样消失的，他选择了闭嘴",
             "value": "行会秩序高于个人恩怨",
             "fear": "陆小满查到当年的局和他有关",
             "contradiction": "最讲规矩的人靠破坏规矩起家",
             "voice": {"catchphrases": ["喝茶喝茶"], "speech_habits": ["绕着说", "从不先出价"], "sample_line": "喝茶喝茶，急什么。"}},
        ],
        "world": {"setting": "九十年代末，某南方城市的老九门典当行街", "glossary": ["死当", "九门", "行会"]},
        "arc": {"template": "悬疑假设弧", "anchors": [], "total_chapters": 12},
        "ledger": [{"id": "F1", "plant_chapter": 1, "reveal_chapter": 3,
                    "hook": "怀表背面刻着一个不属于师父籍贯的地名，只给特写不解释",
                    "reveal_plan": "地名是师父三十年前当学徒的旧铺号，贺三刀当年就在那里", "canary": "泉 lock"}],
        "chapters": {},
    }
    wb.save_bible(BOOK, bible)
    print("bible seeded")
else:
    print("bible exists, skip seed")

# 2. 模拟讨论：写入一个预设讨论记录（跳过 REPL 交互，直接测 lock 的细胞提炼）
disc_dir = os.path.join(wb.ws_dir(BOOK), "discussions")
log_path = os.path.join(disc_dir, "ch01.jsonl")
turns = [
    {"role": "user", "content": "书况：雾锁九门……我们来讨论第 1 章。"},
    {"role": "ai", "content": ("候选方向：A) 开场在当铺夜班，陆小满收到师父的怀表死当（扰动=怀表背面刻着陌生地名'泉 lock'），"
                              "贺三刀同一夜登门喝茶施压要把行并走；B) 开场在行会饭局……推荐 A：扰动第1场落地，"
                              "want（赎表查师父）在前800字经对话显性化，对话密度约55%，动机压力打陆小满的fear"
                              "（师父可能自愿消失）与贺三刀的contradiction。")},
    {"role": "user", "content": "选A。对话密度再加一点，贺三刀的威胁全部用喝茶的场面话说，不要明说。"},
    {"role": "ai", "content": ("一致。第1章细胞：开场即夜班收表，扰动=地名刻痕，贺三刀夜访全用场面话施压"
                              "（对话密度约60%），章末钩子=陆小满发现怀表停在师父失踪那晚的时刻。"
                              "动机压力：陆小满[want]被'赎表要钱'逼向贺三刀，代价是接受并行的条件；"
                              "贺三刀[contradiction]用规矩话术破坏规矩，代价是留下把柄。")},
]
with open(log_path, "w", encoding="utf-8") as f:
    for t in turns:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
bible = wb.load_bible(BOOK)
bible["chapters"]["1"] = {"status": "discussed", "discussion": log_path}
wb.save_bible(BOOK, bible)
print("discussion seeded")

# 3. lock（交互确认 y）
os.chdir(ROOT)
r = subprocess.run([sys.executable, "workbench.py", "lock", BOOK, "1"],
                   input="y\n", capture_output=True, text=True, encoding="utf-8")
print("--- lock ---")
print(r.stdout[-1500:] if r.stdout else r.stderr[-800:])

# 4. write
r = subprocess.run([sys.executable, "workbench.py", "write", BOOK, "1"],
                   capture_output=True, text=True, encoding="utf-8", timeout=600)
print("--- write ---")
print(r.stdout[-800:] if r.stdout else r.stderr[-800:])

# 5. status
r = subprocess.run([sys.executable, "workbench.py", "status", BOOK],
                   capture_output=True, text=True, encoding="utf-8")
print("--- status ---")
print(r.stdout)
