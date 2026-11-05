"""正史状态层（M2 P2/P6）：story-state.json 的加载 / 校验 / 原子推进 / 豁免台账。

设计：docs/plans/M2-workorder.md P2 + 蓝图裁决二（state 是唯一动态状态权威，
只允许 reducer 修改——本模块即 reducer，workbench 不直接改 state 内部字段）。

- StoryState 持有 workspaces/<书>/state/story-state.json
  {revision, as_of_chapter, characters:{id:{knowledge:{knows,unknown_to_them,false_beliefs},
   location, injuries, inventory, relationships}}, facts:{}, hooks:{}, timeline:[], exemptions:[]}
- validate_delta / apply_delta / commit_delta：STATE_DELTA 白名单 reducer。
  每个 op 必带 evidence（正文原文子串）；learn 与 never_learn 冲突硬拒绝；
  commit 原子推进（临时文件 + os.replace），提交前备份 .bak-{revision}
- exemptions（P6 豁免即状态）：指纹绑定正文 hash，正文变化自动失效

标准库 only；不依赖 engine/ledger（避免 reducer 与叙事层耦合）。
"""
import hashlib
import json
import os
import shutil
from datetime import datetime

# op 白名单：op -> (必填字段, 说明)。增补 op 必须在这里显式注册。
OP_SPECS = {
    "learn": (("character_id", "fact_id", "evidence"), "人物获知事实"),
    "set_location": (("character_id", "value", "evidence"), "设置人物位置"),
    "set_inventory": (("character_id", "value", "evidence"), "人物物品变动（str=添一件 / list=整体置换）"),
    "advance_hook": (("hook_id", "action", "evidence"), "钩子推进（plant/develop/payoff）"),
    "add_relationship": (("a", "b", "type", "evidence"), "人物关系建立或变化（a 对 b）"),
    "set_false_belief": (("character_id", "value", "evidence"), "人物错误信念"),
}


def _char_skeleton():
    return {"knowledge": {"knows": [], "unknown_to_them": [], "false_beliefs": []},
            "location": "", "injuries": [], "inventory": [], "relationships": {}}


def _atomic_write(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def text_sha1(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


class StoryState:
    """story-state.json 的唯一读写入口（reducer）。"""

    def __init__(self, path: str):
        self.path = path
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}
        # 防御补默认（老 state / 手工残缺文件）
        self.data.setdefault("revision", 0)
        self.data.setdefault("as_of_chapter", 0)
        self.data.setdefault("characters", {})
        self.data.setdefault("facts", {})
        self.data.setdefault("hooks", {})
        self.data.setdefault("timeline", [])
        self.data.setdefault("exemptions", [])

    @property
    def revision(self) -> int:
        return int(self.data.get("revision", 0))

    def ensure_characters(self, ids):
        """为 bible 人物补骨架（不覆盖已有动态数据）。"""
        for cid in ids:
            if cid:
                self.data["characters"].setdefault(cid, _char_skeleton())

    def character(self, cid: str) -> dict:
        return self.data["characters"].setdefault(cid, _char_skeleton())

    # ---------------- STATE_DELTA 校验 ----------------

    def _never_learn_conflict(self, op, knowledge_rules) -> str | None:
        """learn 与 never_learn 冲突硬拒绝（规则来自 bible 人物卡，由调用方传入）。"""
        if op.get("op") != "learn" or not knowledge_rules:
            return None
        cid = op.get("character_id")
        rules = knowledge_rules.get(cid) or {}
        if op.get("fact_id") in (rules.get("never_learn") or []):
            return (f"硬拒绝：op learn 的 {cid} 在 never_learn 名单中包含 "
                    f"{op.get('fact_id')}（learn 与 never_learn 冲突）")
        return None

    def validate_delta(self, delta, draft_text: str, knowledge_rules=None) -> list:
        """校验 STATE_DELTA，返回违规清单（空 = 通过）。不改内存。"""
        v = []
        if not isinstance(delta, dict):
            return ["delta 必须是 JSON 对象"]
        ch = delta.get("chapter")
        if isinstance(ch, bool) or not isinstance(ch, int) or ch < 1:
            v.append(f"delta.chapter 必须是正整数（实际为 {ch!r}）")
        if not delta.get("draft") or not isinstance(delta.get("draft"), str):
            v.append("delta.draft 必须是非空字符串（草稿版本号，如 v001）")
        bsr = delta.get("base_state_revision")
        if isinstance(bsr, bool) or not isinstance(bsr, int):
            v.append(f"base_state_revision 必须是 int（实际为 {bsr!r}）")
        elif bsr != self.revision:
            v.append(f"base_state_revision={bsr} 与当前 state.revision={self.revision} 不匹配"
                     f"（state 已推进，请基于最新 state 重新生成 delta）")
        ops = delta.get("ops")
        if not isinstance(ops, list):
            v.append("delta.ops 必须是数组")
            return v
        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                v.append(f"ops[{i}] 必须是对象")
                continue
            name = op.get("op")
            if name not in OP_SPECS:
                v.append(f"ops[{i}] 非白名单 op：{name!r}（允许：{', '.join(sorted(OP_SPECS))}）")
                continue
            required, _ = OP_SPECS[name]
            for field in required:
                val = op.get(field)
                if isinstance(val, str) and not val.strip():
                    v.append(f"ops[{i}] {name} 缺少必填字段：{field}")
                elif val is None:
                    v.append(f"ops[{i}] {name} 缺少必填字段：{field}")
            ev = op.get("evidence")
            if isinstance(ev, str) and ev.strip() and isinstance(draft_text, str):
                if ev not in draft_text:
                    v.append(f"ops[{i}] {name} 的 evidence 不是正文子串：『{(ev or '')[:30]}…』")
            conflict = self._never_learn_conflict(op, knowledge_rules)
            if conflict:
                v.append(conflict)
        return v

    def apply_delta(self, delta, draft_text: str, knowledge_rules=None) -> list:
        """校验并应用到内存（不落盘）。返回违规清单；有违规则不应用。"""
        v = self.validate_delta(delta, draft_text, knowledge_rules)
        if v:
            return v
        self._apply_ops(delta)
        return []

    def _apply_ops(self, delta):
        ch = delta.get("chapter")
        for op in delta.get("ops", []):
            name = op.get("op")
            if name == "learn":
                c = self.character(op["character_id"])
                if op["fact_id"] not in c["knowledge"]["knows"]:
                    c["knowledge"]["knows"].append(op["fact_id"])
                fact = self.data["facts"].setdefault(
                    op["fact_id"], {"learned_by": [], "chapters": []})
                if op["character_id"] not in fact["learned_by"]:
                    fact["learned_by"].append(op["character_id"])
                if ch not in fact["chapters"]:
                    fact["chapters"].append(ch)
            elif name == "set_location":
                self.character(op["character_id"])["location"] = op["value"]
            elif name == "set_inventory":
                c = self.character(op["character_id"])
                val = op["value"]
                if isinstance(val, list):
                    c["inventory"] = list(val)
                elif val not in c["inventory"]:
                    c["inventory"].append(val)
            elif name == "advance_hook":
                h = self.data["hooks"].setdefault(
                    op["hook_id"], {"history": []})
                h["status"] = op["action"]
                h["chapter"] = ch
                h["evidence"] = op["evidence"]
                h["history"].append({"chapter": ch, "action": op["action"],
                                     "evidence": op["evidence"]})
            elif name == "add_relationship":
                c = self.character(op["a"])
                c["relationships"][op["b"]] = {"type": op["type"], "chapter": ch,
                                               "evidence": op["evidence"]}
            elif name == "set_false_belief":
                c = self.character(op["character_id"])
                if op["value"] not in c["knowledge"]["false_beliefs"]:
                    c["knowledge"]["false_beliefs"].append(op["value"])

    def commit_delta(self, delta, draft_text: str = "", knowledge_rules=None) -> list:
        """校验通过后原子推进：备份 -> 应用 -> revision+=1 -> os.replace 落盘。

        返回违规清单（非空 = 未落盘未推进）。
        """
        v = self.validate_delta(delta, draft_text, knowledge_rules)
        if v:
            return v
        backup = f"{self.path}.bak-{self.revision}"
        if os.path.exists(self.path):
            shutil.copyfile(self.path, backup)
        else:
            _atomic_write(backup, self.data)  # 首次提交：留初始态备份，保证 .bak-{revision} 恒存在
        self._apply_ops(delta)
        self.data["revision"] = self.revision + 1
        self.data["as_of_chapter"] = max(int(self.data.get("as_of_chapter", 0)),
                                         int(delta.get("chapter", 0)))
        self.data["timeline"].append({
            "chapter": delta.get("chapter"),
            "draft": delta.get("draft"),
            "ops": [op.get("op") for op in delta.get("ops", [])],
            "committed_at": datetime.now().isoformat(timespec="seconds"),
        })
        _atomic_write(self.path, self.data)
        return []

    def save(self):
        """非推进性保存（豁免台账等）：原子写，不 bump revision、不备份。"""
        _atomic_write(self.path, self.data)

    # ---------------- 豁免（P6） ----------------

    @staticmethod
    def make_fingerprint(rule: str, chapter: int, entity: str, source_text_hash: str) -> str:
        raw = f"{rule}|{chapter}|{entity or ''}|{source_text_hash}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def add_exemption(self, rule: str, chapter: int, source_text_hash: str,
                      reason: str, entity: str = "", created_by: str = "author") -> dict:
        ids = [int(e["id"][2:]) for e in self.data["exemptions"]
               if str(e.get("id", "")).startswith("EX") and e["id"][2:].isdigit()]
        ex = {
            "id": f"EX{max(ids, default=0) + 1:03d}",
            "rule": rule,
            "fingerprint": self.make_fingerprint(rule, chapter, entity, source_text_hash),
            "scope": {"chapter": chapter, **({"character_id": entity} if entity else {})},
            "source_text_hash": source_text_hash,
            "reason": reason,
            "created_by": created_by,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.data["exemptions"].append(ex)
        return ex

    def _rule_short(self, rule: str) -> str:
        return (rule or "").strip().split(".")[-1].strip().lower()

    def active_exemptions(self, chapter: int, source_text_hash: str = "") -> list:
        """当前有效的豁免：章节匹配 + 正文 hash 未变（变则自动失效）。"""
        out = []
        for ex in self.data.get("exemptions", []):
            scope = ex.get("scope") or {}
            if scope.get("chapter") != chapter:
                continue
            if source_text_hash and ex.get("source_text_hash") != source_text_hash:
                continue  # 正文已变化，豁免自动失效
            out.append(ex)
        return out

    def filter_flags(self, flags: list, chapter: int, source_text_hash: str = "") -> tuple:
        """lint 汇报过滤：返回 (保留 flags, 被豁免 flags)。"""
        acts = self.active_exemptions(chapter, source_text_hash)
        shorts = {self._rule_short(e["rule"]) for e in acts}
        kept = [f for f in flags if self._rule_short(f) not in shorts]
        exempted = [f for f in flags if self._rule_short(f) in shorts]
        return kept, exempted
