# M3A 工单 · 滚动连载 + 最小故事图谱

> 验收合同由 Hana 提供。执行方：ZCode。本工单是唯一验收标准，执行方不得自行修改。
> 范围裁定（Morgan 评议 + 月华拍板）：**只做 M3A**——滚动连载 + 最小图谱。修订传播（M3B）、弧级反思记忆、完整四视图工作台全部冻结，等英文真实连载 20-30 章数据后再议。
> 基线：M1+M2 已合入 main（章节卡/canon-commit/state reducer/投影开关/豁免）。

## 目标

1. 12 章规划写满后可**滚动展开**下一批章节锚点（人机协作：AI 提议、作者确认）
2. canon commit 后自动抽取**章级事实（ChapterFact）**，与 STATE_DELTA 对照做**遗漏检测**
3. 生成**最小地图**：本地 HTML 双视图（剧情因果 + 人物关系），数据为派生投影，绝不做第二正史

## 边界（硬性）

1. `engine.py` / `Ledger` / `state.py` 的既有语义零改动（可在 state.py 增加只读访问方法）
2. 图谱**不得直接修改** `state/story-state.json`——遗漏只能产出警告与待审补丁文件，正史仍由现有 commit 流程推进
3. 不 merge、不 push、不改 main；Python 标准库 only（前端 vendor JS 文件除外，见 P-map）
4. `python tools/workbench-smoke.py` 每阶段必须通过（适配扩展）
5. 模型分工：事实抽取用 **qwen3.8-flash**（与 writer 异构，避免 GLM 自己证明自己）；弧级锚点提议用主力 writer 模型；英文书抽取模型在 bible.book.extraction_model 可覆盖

## P7s · 滚动规划（缩范围版）

`bible.arc` 升级（migrate 兼容）：

```json
{
  "template": "…", "anchors": [...],
  "locked_through": 12, "planned_through": 12,
  "compass": {"ending_direction": "…", "reader_promise": "…", "active_long_line_ids": []},
  "volumes": [{"id": "V1", "status": "active", "chapters": [1, 12]}, {"id": "V2", "status": "skeleton", "chapters": [13, 24]}]
}
```

新增命令 `python workbench.py plan <书名>`：

- 条件：`planned_through == locked_through`（规划耗尽）或作者显式 `--extend N`
- 流程：汇总 canon 摘要（committed 章节）+ compass + 未闭合 hook + 当前弧位置 → LLM 提议下一批锚点（默认 4 章：arc_label/amplitude 摘要/一句话方向）→ 作者逐条确认或修改 → 写入 `arc.anchors` 并推进 `planned_through`
- `planned_through - locked_through ≤ 8`（滚动纪律：不为远处写细纲）
- volumes[] 在规划越过卷边界时自动追加 skeleton 卷

## P-G1 · ChapterFact 抽取管线

新增 `src/harness/graph.py`：

**ChapterFact schema**（`workspaces/<书>/graph/facts/chNN.fact.json`，不可变 append-only）：

```json
{
  "chapter": 2,
  "canon_revision": 5,
  "extractor_model": "qwen3.8-flash",
  "extracted_at": "ISO8601",
  "events": [
    {"id": "ev_002_01", "description": "陆小满发现怀表停在失踪那晚的时刻",
     "participants": ["char_lu_xiaoman"], "location": "九门典当行",
     "modality": "actual", "evidence": "正文原文子串",
     "caused_by": ["ev_001_02"]}
  ],
  "state_changes_observed": [
    {"character_id": "char_lu_xiaoman", "kind": "location", "value": "九门典当行", "evidence": "…"}
  ],
  "hooks_touched": [{"hook_id": "F1", "action": "plant"}],
  "unresolved_questions": ["泉lock 刻痕是谁刻的"]
}
```

- 抽取时机：`commit` 成功后自动触发（失败不阻塞 commit，只打印警告——图谱是派生层）
- **遗漏检测**：抽取后与该章 `delta.json` 对照——`state_changes_observed` 中存在而 `delta.ops` 无对应 op 的项 → 输出遗漏警告 + 写 `graph/chNN.omissions.json`（待审补丁建议，**不自动改正史**）
- 抽取 prompt 注入实体词典（bible 人物 id/name + 世界观 glossary）以稳定 id 引用；evidence 必须是 canon 子串（代码校验，非子串的 event 丢弃并警告）
- facts 文件不可变：重抽产生新文件并在 `graph/index.json` 登记版本

## P-G2 · 最小地图

新增命令 `python workbench.py map <书名>`：

- 从 `graph/facts/*.json` 重放生成 `graph/graph.json`（nodes + edges，见下方类型）
- 生成 `graph/map.html`：本地网页，Cytoscape.js（vendor JS 一次性下载存 `tools/vendor/cytoscape.min.js`，离线可用；无法下载时降级输出 Mermaid 静态图）
- 两个切换视图：
  1. **剧情因果**：Chapter → Event 节点，`CAUSES` 边连事件，悬停显示 evidence
  2. **人物关系**：Character 节点，`RELATES_TO` 边（带 valid_from 章），按章节滑块过滤有效关系
- 章节滑块过滤 + 点击节点显示 evidence 原文
- 图数据从 facts 重放（不持久化图状态）；`--as-of N` 参数可生成第 N 章时刻的地图

图节点/边类型（第一版子集，克制）：Character、Chapter、Event、Location；边：`PARTICIPATES_IN(role)`、`OCCURS_AT`、`CAUSES`、`RELATES_TO(type, valid_from, valid_to)`、`KNOWS(fact, from_chapter)`。其余类型（Item/Faction/ArcReflection/TRANSFERS_ITEM 等）**明确不进 M3A**。

## 验收标准（全部满足才算完成）

1. `python tools/workbench-smoke.py` 适配后通过，新增断言：commit 后 facts 文件生成且 evidence 为 canon 子串；构造「正文有状态变化但 delta 缺失」用例断言遗漏警告出现；map 产物（graph.json + map.html）存在且 nodes/edges 非空；滚动规划后 planned_through 推进且锚点入 arc
2. 12 章规模回归：smoke-wb 写满 12 章（FakeClient 离线）后 plan 展开 13-16 章不报错
3. 图谱隔离：graph/ 目录损坏（删 facts）后 commit/write/status 全部不受影响（重抽即可恢复）
4. 双书并行：两个 workspace 各自 map/plan 互不干扰
5. M1/M2 工作区迁移兼容（smoke-wb-legacy 可 map 可 plan）
6. `git status` 干净，全部提交在 M3A 分支，附 M3A-CHANGES.md（含「工单未写明的决策」节）

## 提示

- smoke 是你前两轮写的（M2 版），本次扩展；FakeClient 离线策略沿用
- Cytoscape.js 下载：`https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js`（若网络不可用，直接做 Mermaid 降级版并在 CHANGES 说明）
- 遇到工单未覆盖的决策：自行裁决 + 记入 M3A-CHANGES.md
