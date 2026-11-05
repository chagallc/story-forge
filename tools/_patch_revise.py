#!/usr/bin/env python3
"""给 workbench.py 加 revise_core（微调剧情核心）+ audit import。"""
import io

F = "workbench.py"
c = io.open(F, encoding="utf-8").read()

if "from src.harness import audit" not in c:
    c = c.replace(
        "from src.harness import graph as gh  # noqa: E402",
        "from src.harness import graph as gh  # noqa: E402\n"
        "from src.harness import audit as audit_mod  # noqa: E402",
        1)

anchor = ('            "lint_path": fd["lint_path"], "report": fd["report"], '
          '"flags": fd["flags"], **dx}')
assert anchor in c, "wcc return anchor missing"

revise = anchor + '''


REVISE_PROMPT = {
    "zh": (
        "你是这部小说的作者。下面是第 {ch} 章的当前稿。作者的微调意图：{intent}\\n"
        "要求：只修改意图涉及的部分，未涉及的段落尽量逐字保留；保持人物声口与动机链；"
        "保持既有伏笔与钩子不丢失；不要新增总结式收尾。输出修改后的全文，不要任何说明。"
    ),
    "en": (
        "You are the author of this novel. Below is the current draft of chapter {ch}. "
        "The author's revision intent: {intent}\\n"
        "Fix ONLY what the intent concerns; keep untouched passages verbatim; "
        "preserve character voices and motive chains; keep existing hooks intact; "
        "no summarizing endings. Output the full revised text only."
    ),
}


def revise_core(book, ch, intent, base_version=None, bible=None, log=None):
    """微调剧情：基于指定版本定向修订，产出新 draft 版本（不覆盖旧版）。

    与 write 的差别：write 从章节卡+空页生成；revise 从既有稿+意图定向修订。
    产物链一致：drafts/v{NNN}.md + .delta.json（状态可能变）+ .lint.json + 合理性审核。
    章节卡不变（微调是执行层，不改合约）。
    """
    log = log or (lambda m: None)
    bible = bible or load_bible(book)
    lang = bible.get("book", {}).get("language", "zh")
    ddir = drafts_dir(book, ch)
    versions = sorted(f for f in os.listdir(ddir)
                      if re.match(r"v\\d+\\.md$", f)) if os.path.isdir(ddir) else []
    if base_version:
        base_path = os.path.join(ddir, f"{base_version}.md")
    else:
        base_path = os.path.join(ddir, versions[-1]) if versions else None
    if not base_path or not os.path.exists(base_path):
        raise Refused("该章没有可微调的草稿。先 write。")
    base_text = open(base_path, encoding="utf-8").read()

    client = client_for(bible, "writer", book)
    prompt = REVISE_PROMPT[lang].format(ch=ch, intent=intent)
    text = client.chat(
        [{"role": "system", "content": WRITER_SYSTEM[lang]},
         {"role": "user", "content": prompt + "\\n\\n【当前稿】\\n" + base_text}],
        tag=f"revise-ch{ch:02d}")

    version = f"v{next_draft_no(ddir):03d}"
    draft_path = os.path.join(ddir, f"{version}.md")
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(text)

    lint = lint_chapter(text, lang)
    lint_path = os.path.join(ddir, f"{version}.lint.json")
    _write_json(lint_path, {
        "chapter": ch, "draft": version, "flags": lint["flags"],
        "checks": lint.get("checks", {}), "evidence": lint.get("evidence", {}),
        "source_text_sha1": text_sha1(text),
        "generated_at": datetime.now().isoformat(timespec="seconds")})

    dx = write_delta_core(book, bible, ch, version, text, log=log)

    # 合理性审核（reader 通道，异构；失败不阻塞）
    audit_result = None
    try:
        aclient = client_for(bible, "reader", book)
        prev_tail = ""
        if ch > 1:
            canon_prev = os.path.join(ws_dir(book), "chapters", f"ch{ch-1:02d}", "canon.md")
            if os.path.exists(canon_prev):
                prev_tail = open(canon_prev, encoding="utf-8").read()[-400:]
        audit_result = audit_mod.audit_chapter(bible, ch, text, prev_tail, aclient, lang)
        log(f"  合理性审核：{audit_summary(audit_result)}")
    except Exception as e:  # noqa: BLE001
        audit_result = {"issues": [], "audit_error": str(e)[:200]}
        log(f"  合理性审核失败（不阻塞）：{str(e)[:120]}")

    return {"version": version, "text": text, "draft_path": draft_path,
            "lint_path": lint_path, "lint_report": lint["flags"],
            "base_version": base_version or (versions[-1].replace(".md", "") if versions else None),
            "intent": intent, **dx, "audit": audit_result}


def audit_summary(audit_result):
    return audit_mod.audit_summary(audit_result)'''

c = c.replace(anchor, revise, 1)

# re import 检查（revise_core 里用了 re.match）
if "\nimport re\n" not in c:
    c = c.replace("import json\n", "import json\nimport re\n", 1)

io.open(F, "w", encoding="utf-8").write(c)
print("revise_core inserted, audit import ok")
