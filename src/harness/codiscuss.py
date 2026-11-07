"""人物共创讨论板：作者 × AI 联合编剧的人物共创会话。

数据：workspaces/<书>/discussions/codiscuss.session.json
  {"brief": 初始设定, "turns": [{"role": "ai|user", "content": "..."}], "updated_at": ...}

落卡：POST save {extract: true} 让 LLM 从讨论提炼 story-bible 格式人物数组；
前端预览表单确认后 POST save {characters: [...]} 写入 bible.characters。
"""

import json
import os
from datetime import datetime

CODISCUSS_SYSTEM = {
    "zh": (
        "你是这部小说的联合编剧，正在与作者共创人物。基于书的基础设定提议人物方向。\n\n"
        "工作方式：\n"
        "1. 首轮提议 2-3 个人物候选（覆盖主角/对手/关键配角的功能位），每个给出："
        "姓名建议、一句话人物卡、want（表层欲望）、need（深层需求）、wound（旧伤）、"
        "value（底线）、fear（恐惧）、contradiction（内在矛盾）、口头禅或声口要点、"
        "与故事 logline 的关系。\n"
        "2. 作者会反馈。根据反馈修改、深化、或推倒重来。敢于否决不合理的人物并给出理由；"
        "也要敢于指出设定里潜在的金矿（作者没意识到的戏剧性）。\n"
        "3. 配角也要有独立 want（不当工具人）；对手要有自洽的逻辑（不是纯恶）；"
        "contradiction 是戏剧性的引擎，每个人物至少一条。\n"
        "4. 作者说「落卡」或「定稿」时，输出完整人物卡的 JSON 数组（story-bible 格式），"
        "除 JSON 代码块外不要任何其他文字。格式：\n"
        '```json\n[{"name": "...", "card": "一句话人物卡", "anchors": ["不可变锚点"], '
        '"want": "...", "need": "...", "wound": "...", "value": "...", "fear": "...", '
        '"contradiction": "...", "voice": {"catchphrases": ["..."], "speech_habits": ["..."], '
        '"forbidden": ["..."], "sample_line": ""}, '
        '"knowledge_rules": {"learn": [], "never_learn": []}, "lorebook": []}]\n```\n\n'
        "全程用中文。回复紧凑，不要客套。"
    ),
    "en": (
        "You are the co-writer of this novel, workshopping characters with the author "
        "based on the book's premise.\n\n"
        "Working mode:\n"
        "1. First propose 2-3 character candidates (protagonist / antagonist / key support), "
        "each with: suggested name, one-line card, want, need, wound, value, fear, "
        "contradiction, voice notes, and relation to the logline.\n"
        "2. The author will push back. Revise, deepen, or scrap and restart. Dare to reject "
        "weak characters with reasons; also point out dramatic gold the author missed.\n"
        "3. Side characters need independent wants (no tool people); antagonists need "
        "self-consistent logic (not pure evil); contradiction is the engine of drama — "
        "at least one per character.\n"
        "4. When the author says 'save' or 'lock', output the full character cards as a "
        "JSON array (story-bible format) with no other text:\n"
        '```json\n[{"name": "...", "card": "...", "anchors": [...], "want": "...", '
        '"need": "...", "wound": "...", "value": "...", "fear": "...", '
        '"contradiction": "...", "voice": {...}, "knowledge_rules": {}, "lorebook": []}]\n```\n\n'
        "Be concise. No pleasantries."
    ),
}


def codiscuss_path(book):
    """路径 helper（ws_dir 由 workbench 提供，此处独立拼装避免循环导入）。"""
    import workbench as _wb  # noqa: E402（延迟导入）

    return os.path.join(_wb.ws_dir(book), "discussions", "codiscuss.session.json")


def load_codiscuss(book):
    p = codiscuss_path(book)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_codiscuss_session(book, data):
    os.makedirs(os.path.dirname(codiscuss_path(book)), exist_ok=True)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(codiscuss_path(book), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def codiscuss_brief(bible, brief_extra=""):
    b = bible.get("book", {})
    chars = bible.get("characters", [])
    have = "\n".join(f"- {c.get('name')}：{c.get('card', '')}" for c in chars) or "（尚无人物）"
    lang = b.get("language", "zh")
    if lang == "en":
        return (
            f"Title: {b.get('title')}\nGenre: {b.get('genre')}\nPlatform: {b.get('platform')}\n"
            f"Logline: {b.get('logline')}\nWorld: {bible.get('world', {}).get('setting', '-')}\n"
            f"Existing characters:\n{have}\n"
            f"Author's initial thoughts: {brief_extra or '(none yet)'}"
        )
    return (
        f"《{b.get('title')}》 类型：{b.get('genre')} 平台：{b.get('platform')}\n"
        f"一句话故事：{b.get('logline')}\n世界观：{bible.get('world', {}).get('setting', '-')}\n"
        f"已有人物：\n{have}\n"
        f"作者的初始想法：{brief_extra or '（还没有）'}"
    )


def codiscuss_messages(bible, turns, brief_extra=""):
    lang = bible.get("book", {}).get("language", "zh")
    msgs = [{"role": "system", "content": CODISCUSS_SYSTEM[lang]}]
    if not turns:
        msgs.append({"role": "user", "content": codiscuss_brief(bible, brief_extra)})
    else:
        for t in turns:
            msgs.append({"role": "user" if t["role"] == "user" else "assistant",
                         "content": t["content"]})
    return msgs


def extract_characters_from_discussion(turns, client, book, lang="zh"):
    """落卡提炼：从讨论记录提炼 story-bible 格式人物数组（LLM 一次调用）。"""
    dialogue = "\n\n".join(
        f"【{'作者' if t['role'] == 'user' else '编剧'}】{t['content']}" for t in turns)
    if lang == "en":
        prompt = (
            "From the character co-creation discussion below, distill ALL agreed characters "
            "into a strict JSON array (story-bible format). Each entry: name, card (one line), "
            "anchors (immutable personality facts, 1-3), want, need, wound, value, fear, "
            "contradiction, voice {catchphrases, speech_habits, forbidden, sample_line}, "
            "knowledge_rules {learn: [], never_learn: []}, lorebook []. "
            "Output ONLY the JSON array, no other text.\n\nDiscussion:\n" + dialogue[:12000])
    else:
        prompt = (
            "从下面的人物共创讨论中，提炼所有已达成共识的人物，输出严格 JSON 数组"
            "（story-bible 格式，不要其他文字）。每个条目：name/card（一句话人物卡）/"
            "anchors（不可变锚点 1-3 条）/want/need/wound/value/fear/contradiction/"
            "voice{catchphrases, speech_habits, forbidden, sample_line}/"
            "knowledge_rules{learn: [], never_learn: []}/lorebook[]。"
            "讨论中未定稿的人物不要输出。\n\n讨论记录：\n" + dialogue[:12000])
    raw = client.chat([{"role": "user", "content": prompt}], tag="codiscuss-extract")
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        raise ValueError("LLM 未返回 JSON 数组")
    chars = json.loads(m.group(0))
    # 规范化：id 生成 + name 必填
    out = []
    for i, c in enumerate(chars, start=1):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        c.setdefault("id", f"char_{i:02d}")
        c.setdefault("card", "")
        c.setdefault("anchors", [])
        c.setdefault("knowledge_rules", {"learn": [], "never_learn": []})
        c.setdefault("lorebook", [])
        out.append(c)
    return out
