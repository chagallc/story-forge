"""最小故事图谱（M3A P-G1/P-G2）：ChapterFact 抽取校验、遗漏检测、facts 重放成图。

设计：docs/plans/M3A-workorder.md。图谱是**派生层**：
- 绝不写 state/story-state.json（遗漏只产警告与待审补丁文件 graph/chNN.omissions.json）
- facts 不可变 append-only：首版 graph/facts/chNN.fact.json，重抽产 chNN.fact.vN.json，
  graph/index.json 登记版本（latest 指针供 map/对照使用）
- evidence 必须是 canon 子串（代码校验，非子串丢弃并警告）
- 图数据从 facts 重放（不持久化图状态），--as-of N 可回放任意时刻

节点类型（第一版子集，克制）：Character / Chapter / Event / Location
边类型：PARTICIPATES_IN(role) / OCCURS_AT / CAUSES / RELATES_TO(type, valid_from, valid_to)
/ KNOWS(fact, from_chapter)。Item/Faction/ArcReflection/TRANSFERS_ITEM 等明确不进 M3A。

标准库 only；本模块不做任何 LLM 调用（client 由调用方注入）。
"""
import json
import os
from datetime import datetime

# state_changes_observed.kind → 对应 delta op（遗漏检测的对照表）
KIND_TO_OP = {
    "location": "set_location",
    "inventory": "set_inventory",
    "knowledge": "learn",
    "false_belief": "set_false_belief",
    "relationship": "add_relationship",
}
# injury 等无对应 op 的 kind 不参与遗漏检测（delta 白名单里没有，对照恒误报）
OMISSION_KINDS = set(KIND_TO_OP)


# ---------------- 路径与 index ----------------

def graph_dir(book_ws):
    return os.path.join(book_ws, "graph")


def facts_dir(book_ws):
    return os.path.join(graph_dir(book_ws), "facts")


def fact_file(book_ws, ch, version=None):
    name = f"ch{ch:02d}.fact.json" if version in (None, 1) else f"ch{ch:02d}.fact.v{version}.json"
    return os.path.join(facts_dir(book_ws), name)


def index_path(book_ws):
    return os.path.join(graph_dir(book_ws), "index.json")


def load_index(book_ws):
    p = index_path(book_ws)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass  # index 损坏视为空（facts 文件仍在，可重建 index）
    return {"chapters": {}}


def save_index(book_ws, index):
    os.makedirs(graph_dir(book_ws), exist_ok=True)
    with open(index_path(book_ws), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def register_fact(book_ws, ch, filename):
    """append-only 登记：返回该章的 index 条目 {versions:[...], latest:...}。"""
    index = load_index(book_ws)
    entry = index["chapters"].setdefault(str(ch), {"versions": []})
    if filename not in entry["versions"]:
        entry["versions"].append(filename)
    entry["latest"] = entry["versions"][-1]
    save_index(book_ws, index)
    return entry


def save_fact(book_ws, fact):
    """保存抽取结果：首版 chNN.fact.json，重抽 chNN.fact.vN.json（永不覆盖旧文件）。"""
    os.makedirs(facts_dir(book_ws), exist_ok=True)
    index = load_index(book_ws)
    versions = index["chapters"].get(str(fact["chapter"]), {}).get("versions", [])
    path = fact_file(book_ws, fact["chapter"], version=len(versions) + 1)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fact, f, ensure_ascii=False, indent=2)
    entry = register_fact(book_ws, fact["chapter"], os.path.basename(path))
    return path, entry


def load_latest_fact(book_ws, ch):
    entry = load_index(book_ws)["chapters"].get(str(ch))
    if not entry:
        p = fact_file(book_ws, ch)
        if os.path.exists(p):  # 无 index 的旧数据（手工放置）：直接探测首版文件
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        return None
    p = os.path.join(facts_dir(book_ws), entry.get("latest") or entry["versions"][-1])
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_all_latest_facts(book_ws, as_of=None):
    """{chapter: fact}，取各章 latest 版本，章号升序。"""
    index = load_index(book_ws)
    out = {}
    for ch_str, entry in index.get("chapters", {}).items():
        ch = int(ch_str)
        if as_of is not None and ch > as_of:
            continue
        name = entry.get("latest") or (entry.get("versions") or [None])[-1]
        if not name:
            continue
        p = os.path.join(facts_dir(book_ws), name)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    out[ch] = json.load(f)
            except json.JSONDecodeError:
                continue  # 单章 facts 损坏不影响整体重放
    return dict(sorted(out.items()))


# ---------------- 抽取：prompt / 规范化 / evidence 校验 ----------------

def build_extraction_prompt(bible, ch, canon_text, state_revision, draft_version):
    """实体词典（人物 id/name + glossary + 暗账 id）注入，稳定 id 引用。"""
    chars = "、".join(f"{c.get('id', '?')}（{c.get('name', '?')}）"
                      for c in bible.get("characters", []) if isinstance(c, dict))
    glossary = "、".join(bible.get("world", {}).get("glossary", []) or [])
    ledger_ids = "、".join(e["id"] for e in bible.get("ledger", []))
    return (
        f"以下是第 {ch} 章的 canon 正文（state.revision={state_revision}）。请抽取章级事实"
        f"（ChapterFact），输出严格 JSON（不要任何其他文字）：\n"
        f'{{"chapter": {ch}, "events": [{{"description": "事件一句话", '
        f'"participants": ["人物id"], "location": "地点", "modality": "actual", '
        f'"evidence": "正文原文连续子串（逐字复制）", "caused_by": ["前序事件id如ev_001_02，无则[]"]}}], '
        f'"state_changes_observed": [{{"character_id": "人物id", '
        f'"kind": "location|inventory|knowledge|false_belief|relationship", '
        f'"value": "变化值（relationship 填关系类型）", '
        f'"target": "relationship 时对方人物id，其他留空", '
        f'"evidence": "正文原文连续子串"}}], '
        f'"hooks_touched": [{{"hook_id": "暗账id", "action": "plant|develop|payoff"}}], '
        f'"unresolved_questions": ["本章留下的未解问题"]}}\n'
        f"规则：evidence 必须逐字来自正文（会做子串校验，非子串会被丢弃）；"
        f"participants/character_id 必须用人物 id（不要用名字），可选：{chars}；"
        f"hooks_touched.hook_id 只能从这些暗账 id 里选：{ledger_ids or '（无）'}（无则空数组）；"
        f"只登记正文里确实发生的事。\n"
        f"世界观词条（供参照）：{glossary or '（无）'}\n"
        f"版本标记：{draft_version}\n\n正文：\n{canon_text}")


def normalize_fact(raw, bible, canon_text, ch, state_revision, extractor_model):
    """LLM 原始输出 → 合法 ChapterFact：补 id、evidence 子串校验（非子串丢弃并警告）。"""
    warnings = []
    raw = raw if isinstance(raw, dict) else {}
    id_by_name = {c.get("name"): c.get("id") for c in bible.get("characters", [])
                  if isinstance(c, dict) and c.get("name") and c.get("id")}
    fact = {
        "chapter": ch,
        "canon_revision": state_revision,
        "extractor_model": extractor_model,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "events": [],
        "state_changes_observed": [],
        "hooks_touched": [],
        "unresolved_questions": [],
    }
    for i, ev in enumerate(raw.get("events") or []):
        if not isinstance(ev, dict):
            continue
        ev = dict(ev)
        evidence = str(ev.get("evidence") or "").strip()
        desc = str(ev.get("description") or "").strip()
        if not desc:
            warnings.append(f"events[{i}] 缺 description，丢弃")
            continue
        if not evidence:
            warnings.append(f"events[{i}] 缺 evidence，丢弃")
            continue
        if evidence not in canon_text:
            warnings.append(f"events[{i}]（{desc[:20]}…）evidence 非 canon 子串，丢弃")
            continue
        participants = []
        for p in ev.get("participants") or []:
            p = id_by_name.get(p, p)  # 名字→id 归一，未知引用原样保留
            if p and p not in participants:
                participants.append(p)
        caused = [str(x) for x in (ev.get("caused_by") or []) if str(x).strip()]
        fact["events"].append({
            "id": f"ev_{ch:03d}_{len(fact['events']) + 1:02d}",
            "description": desc,
            "participants": participants,
            "location": str(ev.get("location") or "").strip(),
            "modality": str(ev.get("modality") or "actual").strip() or "actual",
            "evidence": evidence,
            "caused_by": caused,
        })
    for i, sc in enumerate(raw.get("state_changes_observed") or []):
        if not isinstance(sc, dict):
            continue
        sc = dict(sc)
        kind = str(sc.get("kind") or "").strip().lower()
        evidence = str(sc.get("evidence") or "").strip()
        cid = id_by_name.get(sc.get("character_id"), sc.get("character_id"))
        if kind not in KIND_TO_OP and kind != "injury":
            warnings.append(f"state_changes_observed[{i}] 未知 kind：{kind!r}，丢弃")
            continue
        if not cid:
            warnings.append(f"state_changes_observed[{i}] 缺 character_id，丢弃")
            continue
        if not evidence or evidence not in canon_text:
            warnings.append(f"state_changes_observed[{i}]（{cid}.{kind}）evidence 非 canon 子串，丢弃")
            continue
        entry = {"character_id": cid, "kind": kind,
                 "value": str(sc.get("value") or "").strip(), "evidence": evidence}
        if kind == "relationship":
            target = id_by_name.get(sc.get("target"), sc.get("target"))
            if not target or target == cid:
                warnings.append(f"state_changes_observed[{i}] relationship 缺有效 target，丢弃")
                continue
            entry["target"] = target
        fact["state_changes_observed"].append(entry)
    known_ids = {e["id"] for e in bible.get("ledger", [])}
    for h in raw.get("hooks_touched") or []:
        if isinstance(h, dict) and h.get("hook_id"):
            hid = str(h["hook_id"])
            if hid not in known_ids:
                warnings.append(f"hooks_touched 未知暗账 id：{hid}，丢弃")
                continue
            fact["hooks_touched"].append({"hook_id": hid,
                                          "action": str(h.get("action") or "develop").strip()})
    for q in raw.get("unresolved_questions") or []:
        if str(q).strip():
            fact["unresolved_questions"].append(str(q).strip())
    return fact, warnings


# ---------------- 遗漏检测（对照 delta，绝不改 state） ----------------

def _op_matches(sc, ops):
    kind = sc["kind"]
    expect = KIND_TO_OP[kind]
    cid = sc["character_id"]
    for op in ops:
        if op.get("op") != expect:
            continue
        if expect == "add_relationship":
            a, b = op.get("a"), op.get("b")
            if cid in (a, b) and sc.get("target") in (a, b):
                return True
            continue
        if op.get("character_id") != cid:
            continue
        if expect == "learn":
            # value 是已知暗账 id 时要求 fact_id 精确一致；否则只按人物匹配
            if not sc.get("value") or op.get("fact_id") == sc.get("value"):
                return True
            continue
        return True
    return False


def detect_omissions(fact, delta):
    """正文观察到、delta 未登记的状态变化 → 待审补丁建议（不改任何正史文件）。"""
    ops = (delta or {}).get("ops") or []
    omissions = []
    for sc in fact.get("state_changes_observed", []):
        if sc.get("kind") not in OMISSION_KINDS:
            continue
        if _op_matches(sc, ops):
            continue
        suggested = {"op": KIND_TO_OP[sc["kind"]], "evidence": sc["evidence"]}
        if sc["kind"] == "relationship":
            suggested.update({"a": sc["character_id"], "b": sc.get("target", ""), "type": sc.get("value", "")})
        elif sc["kind"] == "knowledge":
            suggested.update({"character_id": sc["character_id"], "fact_id": sc.get("value", "")})
        else:
            suggested.update({"character_id": sc["character_id"], "value": sc.get("value", "")})
        omissions.append({
            "character_id": sc["character_id"],
            "kind": sc["kind"],
            "value": sc.get("value", ""),
            **({"target": sc["target"]} if "target" in sc else {}),
            "evidence": sc["evidence"],
            "suggested_op": suggested,
        })
    return omissions


def save_omissions(book_ws, ch, omissions, delta_draft):
    os.makedirs(graph_dir(book_ws), exist_ok=True)
    payload = {
        "chapter": ch,
        "delta_draft": delta_draft,
        "note": "待审补丁建议：正文观察到但 delta 未登记的状态变化。人工审核后可把 suggested_op "
                "手工并入对应 drafts/vNNN.delta.json 并重跑 commit 流程；本文件绝不自动改正史。",
        "omissions": omissions,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    p = os.path.join(graph_dir(book_ws), f"ch{ch:02d}.omissions.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return p


# ---------------- 图重放（facts → nodes/edges，不持久化图状态） ----------------

def replay_graph(bible, facts_by_ch, as_of=None):
    """从 facts 重放节点/边。as_of=N 只重放第 1~N 章。"""
    id_name = {c.get("id"): c.get("name") for c in bible.get("characters", [])
               if isinstance(c, dict) and c.get("id")}
    nodes, edges = {}, []

    def node(nid, ntype, label, **attrs):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label, **attrs}
        return nodes[nid]

    def edge(src, dst, etype, chapter=None, **attrs):
        edges.append({"source": src, "target": dst, "type": etype,
                      **({"chapter": chapter} if chapter is not None else {}), **attrs})

    chapters = [c for c in facts_by_ch if as_of is None or c <= as_of]
    rel_seen = {}  # (a,b,type) -> 首次出现章
    for ch in chapters:
        fact = facts_by_ch[ch]
        ch_id = f"ch:{ch}"
        node(ch_id, "Chapter", f"第{ch}章", chapter=ch)
        ev_ids = {}
        for ev in fact.get("events", []):
            ev_id = f"ev:{ev['id']}"
            ev_ids[ev["id"]] = ev_id
            # 章节与事件的归属由 event id（ev_chNN_NN）与 node.chapter 表达，
            # 不设 HAS_EVENT 边（边类型保持工单五类，克制）
            node(ev_id, "Event", ev["description"][:40], chapter=ch,
                 evidence=ev.get("evidence", ""), description=ev["description"])
            for p in ev.get("participants", []):
                node(f"char:{p}", "Character", id_name.get(p, p), character_id=p)
                edge(f"char:{p}", ev_id, "PARTICIPATES_IN", chapter=ch, role="出场")
            if ev.get("location"):
                loc = ev["location"]
                node(f"loc:{loc}", "Location", loc)
                edge(ev_id, f"loc:{loc}", "OCCURS_AT", chapter=ch)
        for ev in fact.get("events", []):
            for prev in ev.get("caused_by", []):
                src = ev_ids.get(prev) or f"ev:{prev}"
                if src in nodes or prev in ev_ids:
                    edge(src, f"ev:{ev['id']}", "CAUSES", chapter=ch)
        for sc in fact.get("state_changes_observed", []):
            cid = sc["character_id"]
            node(f"char:{cid}", "Character", id_name.get(cid, cid), character_id=cid)
            if sc["kind"] == "relationship" and sc.get("target"):
                tid = sc["target"]
                node(f"char:{tid}", "Character", id_name.get(tid, tid), character_id=tid)
                key = tuple(sorted((cid, tid))) + (sc.get("value", ""),)
                if key in rel_seen:
                    continue  # 同对同型关系取首次 valid_from
                rel_seen[key] = ch
                edge(f"char:{cid}", f"char:{tid}", "RELATES_TO", chapter=ch,
                     rel_type=sc.get("value", ""), valid_from=ch, valid_to=None,
                     evidence=sc.get("evidence", ""))
            elif sc["kind"] == "knowledge":
                edge(f"char:{cid}", ch_id, "KNOWS", chapter=ch,
                     fact=sc.get("value", ""), evidence=sc.get("evidence", ""))
    # valid_to 解析：同一对人物出现后续关系定义（无论 type 是否变化，如 同盟→决裂）
    # → 前一条止于其后一章前。type 变更正是关系演进的主场景，必须闭合旧边。
    rel_edges = [e for e in edges if e["type"] == "RELATES_TO"]
    for e in rel_edges:
        later = [x for x in rel_edges
                 if x is not e and {x["source"], x["target"]} == {e["source"], e["target"]}
                 and (x.get("valid_from") or 0) > (e.get("valid_from") or 0)]
        if later:
            e["valid_to"] = min(x["valid_from"] for x in later) - 1
    return {"meta": {"node_count": len(nodes), "edge_count": len(edges),
                     "as_of": as_of, "chapters": chapters,
                     "generated_at": datetime.now().isoformat(timespec="seconds")},
            "nodes": list(nodes.values()), "edges": edges}


# ---------------- map.html 渲染 ----------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>__TITLE__ · 故事地图</title>
<style>
 body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:0;background:#141419;color:#e8e6e3}
 header{padding:10px 16px;background:#1d1d26;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
 header h1{font-size:16px;margin:0;margin-right:8px}
 button.view{background:#2a2a35;border:1px solid #3a3a48;color:#e8e6e3;padding:4px 14px;border-radius:4px;cursor:pointer}
 button.view.on{background:#4a6cf7;border-color:#4a6cf7}
 #slider{width:280px}
 #chapLabel{min-width:110px;font-size:13px;color:#9aa}
 #cy{position:absolute;top:56px;bottom:190px;left:0;right:0}
 #detail{position:absolute;left:0;right:0;bottom:0;height:186px;background:#1d1d26;
   border-top:1px solid #3a3a48;padding:10px 16px;overflow:auto;font-size:13px;line-height:1.7}
 #detail h3{margin:0 0 6px;font-size:14px;color:#8fb0ff}
 .tag{display:inline-block;background:#2a2a35;border-radius:3px;padding:1px 8px;margin-right:6px;color:#9aa;font-size:12px}
 .ev{background:#26262f;border-left:3px solid #4a6cf7;padding:4px 10px;margin:4px 0}
 .hint{color:#889;font-size:12px}
</style>
__VENDOR__
</head>
<body>
<header>
 <h1>__TITLE__</h1>
 <button class="view on" id="btnCausality">剧情因果</button>
 <button class="view" id="btnRelations">人物关系</button>
 <span id="chapLabel">章节 ≤ __MAXCH__</span>
 <input type="range" id="slider" min="0" max="__MAXCH__" value="__MAXCH__">
 <span class="hint">拖动滑块过滤章节；点击节点看 evidence</span>
</header>
<div id="cy"></div>
<div id="detail"><span class="hint">点击节点/边在此显示详情。</span></div>
<script id="graph-data" type="application/json">__DATA__</script>
<script>
__SCRIPT__
</script>
</body>
</html>
"""


def _view_script():
    return r"""
var DATA = JSON.parse(document.getElementById('graph-data').textContent);
var NODES = DATA.nodes, EDGES = DATA.edges;
var detail = document.getElementById('detail');
var currentView = 'causality';
var chapterMax = DATA.meta.as_of || 9999;

var VIEW_FILTER = {
  causality: function(el){ return el.data('vtype') !== 'rel'; },
  relations: function(el){ return el.data('vtype') === 'rel' || el.data('vtype') === 'char'; }
};
function chapterOk(el){
  var n = document.getElementById('slider').valueAsNumber;
  if (el.isEdge()){
    var cf = el.data('valid_from'), ct = el.data('valid_to'), ch = el.data('chapter');
    if (cf != null) return cf <= n && (ct == null || n <= ct);
    if (ch != null) return ch <= n;
    return true;
  }
  var c = el.data('chapter');
  return c == null || c <= n;
}
function esc(s){ var d=document.createElement('div'); d.textContent=(s==null?'':String(s)); return d.innerHTML; }
function show(el){
  var d = el.data();
  var h = '<h3>'+esc(d.label||d.id)+'</h3>'
    + '<div><span class="tag">'+esc(d.ntype||'')+'</span>'
    + (d.chapter!=null?'<span class="tag">第'+d.chapter+'章</span>':'')
    + (d.rel_type?'<span class="tag">关系：'+esc(d.rel_type)+'</span>':'')
    + (d.valid_from!=null?'<span class="tag">valid_from 第'+d.valid_from+'章</span>':'')
    + (d.valid_to!=null?'<span class="tag">valid_to 第'+d.valid_to+'章</span>':'')
    + (d.fact?'<span class="tag">fact：'+esc(d.fact)+'</span>':'') + '</div>'
    + (d.description?'<p>'+esc(d.description)+'</p>':'')
    + (d.evidence?'<div class="ev">evidence 原文：'+esc(d.evidence)+'</div>':'');
  detail.innerHTML = h;
}
function cyElements(){
  var els = [];
  var COLOR = {Chapter:'#5a7bd8',Event:'#d8a45a',Character:'#5abf8a',Location:'#b06ad8'};
  function knowsTarget(id){ return EDGES.some(function(e){return e.type==='KNOWS'&&e.target===id;}); }
  NODES.forEach(function(n){
    var vtype;
    if (currentView==='relations')
      vtype = (n.type==='Character' || knowsTarget(n.id)) ? 'rel' : 'skip';
    else
      vtype = 'plain';
    if (vtype==='skip') return;
    els.push({data:{id:n.id, label:n.label, ntype:n.type, chapter:n.chapter||null,
      evidence:n.evidence||'', description:n.description||'', vtype:vtype,
      color:COLOR[n.type]||'#888'}});
  });
  EDGES.forEach(function(e){
    var vtype = (e.type==='RELATES_TO'||e.type==='KNOWS') ? 'rel' : 'plain';
    if (currentView==='relations' && vtype!=='rel') return;
    if (currentView==='causality' && vtype==='rel') return;
    els.push({data:{id:'e'+els.length, source:e.source, target:e.target, label:
      (e.type==='RELATES_TO'? (e.rel_type||'') : (e.type==='KNOWS'? ('知:'+ (e.fact||'')) :
      (e.type==='PARTICIPATES_IN'? (e.role||e.type) : e.type))),
      ntype:e.type, chapter:e.chapter||null, valid_from:e.valid_from||null,
      valid_to:e.valid_to||null, evidence:e.evidence||'', rel_type:e.rel_type||'',
      fact:e.fact||'', vtype:vtype}});
  });
  return els;
}
function applyFilter(){
  cy.elements().forEach(function(el){
    el.style('display', (VIEW_FILTER[currentView](el) && chapterOk(el)) ? 'element':'none');
  });
  cy.fit(cy.elements(':visible'), 30);
}
function applyFilter(){
  cy.elements().forEach(function(el){
    el.style('display', (VIEW_FILTER[currentView](el) && chapterOk(el)) ? 'element':'none');
  });
  cy.fit(cy.elements(':visible'), 30);
}
var cy = cytoscape({
  container: document.getElementById('cy'),
  elements: cyElements(),
  style: [
    {selector:'node', style:{'background-color':'data(color)','label':'data(label)',
      'color':'#e8e6e3','font-size':9,'text-valign':'bottom','text-margin-y':4,
      'width':22,'height':22,'border-width':1,'border-color':'#555'}},
    {selector:'edge', style:{'width':1.5,'line-color':'#5a6a8a','target-arrow-color':'#5a6a8a',
      'target-arrow-shape':'triangle','curve-style':'bezier','label':'data(label)',
      'font-size':8,'color':'#9ab','text-background-color':'#141419',
      'text-background-opacity':0.8,'text-background-padding':2}},
    {selector:'edge[ntype = "CAUSES"]', style:{'line-color':'#d87a5a','target-arrow-color':'#d87a5a'}},
    {selector:'edge[ntype = "RELATES_TO"]', style:{'line-color':'#5abf8a','target-arrow-color':'#5abf8a'}},
    {selector:'edge[ntype = "KNOWS"]', style:{'line-style':'dashed','line-color':'#8a8ab0',
      'target-arrow-color':'#8a8ab0'}}
  ],
  layout:{name:'cose', animate:false, padding:30}
});
cy.on('tap','node,edge', function(evt){ show(evt.target); });
document.getElementById('btnCausality').onclick = function(){
  currentView='causality'; this.classList.add('on');
  document.getElementById('btnRelations').classList.remove('on');
  cy.elements().remove(); cy.add(cyElements()); applyFilter();
};
document.getElementById('btnRelations').onclick = function(){
  currentView='relations'; this.classList.add('on');
  document.getElementById('btnCausality').classList.remove('on');
  cy.elements().remove(); cy.add(cyElements()); applyFilter();
};
document.getElementById('slider').oninput = function(){
  document.getElementById('chapLabel').textContent = '章节 ≤ ' + this.value;
  applyFilter();
};
applyFilter();
"""


def render_map_html(graph, book_title, vendor_js=None):
    """生成 map.html。vendor_js 为 cytoscape.min.js 文本（None → Mermaid 静态降级）。"""
    max_ch = 0
    for n in graph["nodes"]:
        if n.get("chapter"):
            max_ch = max(max_ch, n["chapter"])
    for e in graph["edges"]:
        if e.get("valid_from"):
            max_ch = max(max_ch, e["valid_from"])
    data = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    if vendor_js:
        script = _view_script()
        vendor = f"<script>{vendor_js}</script>"
    else:
        # 降级：无 cytoscape 时输出 Mermaid 源码的静态页（零依赖，文本可读、可贴到任何 mermaid 渲染器）
        lines = ["graph TD"]
        for e in graph["edges"]:
            src = e["source"].replace(":", "_")
            dst = e["target"].replace(":", "_")
            label = e.get("rel_type") or e.get("fact") or e.get("role") or e["type"]
            lines.append(f'    {src}["{e["source"]}"] -->|{label}| {dst}["{e["target"]}"]')
        for n in graph["nodes"]:
            if not any(e["source"] == n["id"] or e["target"] == n["id"] for e in graph["edges"]):
                lines.append(f'    {n["id"].replace(":", "_")}["{n["label"]}"]')
        mermaid_src = "\n".join(lines)
        vendor = ""
        note = (f"未找到 cytoscape vendor JS（tools/vendor/cytoscape.min.js），已降级为 Mermaid 静态源码。"
                f"节点/边共 {len(graph['nodes'])}/{len(graph['edges'])}，graph.json 与本文件同目录；"
                f"可把下方源码粘贴到任何 mermaid 渲染器出图。")
        script = ("var detail=document.getElementById('detail');"
                  "var h='<h3>Mermaid 降级模式</h3><p>" + note + "</p>';"
                  "h+='<pre id=\"mmd\">' + " + json.dumps(mermaid_src) + " + '</pre>';"
                  "detail.innerHTML=h;"
                  "['btnCausality','btnRelations','slider'].forEach(function(id){"
                  "  var el=document.getElementById(id); if(el) el.style.display='none'; });"
                  "document.getElementById('chapLabel').textContent='（降级模式）';")
    html = (_HTML_TEMPLATE.replace("__TITLE__", book_title)
            .replace("__MAXCH__", str(max_ch))
            .replace("__VENDOR__", vendor)
            .replace("__DATA__", data)
            .replace("__SCRIPT__", script))
    return html


def vendor_js_text(root):
    """读 vendor cytoscape（tools/vendor/cytoscape.min.js）；缺失返回 None（调用方降级）。"""
    p = os.path.join(root, "tools", "vendor", "cytoscape.min.js")
    if os.path.exists(p) and os.path.getsize(p) > 10000:
        with open(p, encoding="utf-8") as f:
            return f.read()
    return None
