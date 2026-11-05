# M3A-CHANGES · 滚动连载 + 最小故事图谱（P7s + P-G1 + P-G2）

> 执行：ZCode · 分支 `hana/m3a-rolling-graph`（M3A worktree）· 验收合同：docs/plans/M3A-workorder.md（未改动）
> 范围裁定遵守：只做 M3A；修订传播（M3B）/弧级反思记忆/完整四视图冻结未碰（`revisions/` 仍只建目录约定）。
> 硬边界沿用：engine.py / Ledger / state.py 既有语义零改动（state.py 本阶段零改动，未加只读方法——图谱直接以只读方式加载 state JSON，无需新入口）。

## 改了什么

### P7s · 滚动规划

- **bible schema v4**（migrate 链 v1→v2→v3→v4，幂等）：
  - `arc.volumes[]`：初始化 V1 active `[1, min(total,12)]`，后续每 12 章 skeleton 顺延（`_ensure_volumes` 支持增量扩展：已有卷覆盖不到 planned/total 时自动追加 skeleton 卷）
  - `arc.compass`：工单 v4 结构要求 compass 入 arc；顶层 `bible.compass` 保持权威（M1/M2 代码与既有数据都读它），每次保存刷新镜像进 arc.compass
  - `planned_through` 语义重定义为「细纲前沿」：迁移时一次性收敛到滚动纪律（`planned - locked ≤ 8`，M1/M2 旧书 planned=total 的一次性收缩）
- **新增 `plan <书名> [--extend N]`**：
  - 条件：`planned == locked`（规划耗尽）或显式 `--extend N`；写超前于规划（locked > planned）时从正史前沿之后展开
  - 流程：committed 章节 canon 摘要（最近 6 章给尾部 200 字，更早只给弧线标签）+ compass + 未闭合钩子（ledger 未回收 + state.hooks 非 payoff）+ 弧位置 → **主力 writer 模型**提议锚点 JSON（arc_label/amplitude/一句话方向）→ 作者逐条确认（y / 直接口述修改方向 / s 跳过）
  - 纪律：`planned - locked ≤ 8` 双重防线——提议批量截断 + 确认后过滤越界锚点（即使 LLM 多给也进不了 arc）
  - 卷边界：规划越过卷尾自动追加 skeleton 卷，新规划落入的 skeleton 卷转 active
  - 锚点落盘格式：`f"{arc_label}@第{ch}章（{amplitude}）｜{direction}"`（字符串，与 lock 的锚点格式兼容，bible_summary/status 直接可显示）

### P-G1 · ChapterFact 抽取管线

- **新增 `src/harness/graph.py`**（纯函数层，LLM client 由调用方注入，本模块零网络）：
  - `build_extraction_prompt`：实体词典注入（人物 id/name 对照 + world.glossary + 暗账 id 白名单）
  - `normalize_fact`：evidence **必须是 canon 子串**（代码校验，非子串的 event/state_change 丢弃并逐条警告）；事件 id 补齐 `ev_chNN_NN`；participants/target 的 name→id 归一（未知引用原样保留）；未知 kind 丢弃（injury 等保留但不参与遗漏检测）；hooks_touched 限定已知暗账 id
  - `detect_omissions` / `save_omissions`：`state_changes_observed` 与该章 `delta.ops` 按（op 类型, 人物, fact_id/value）对照 → 缺失项写 `graph/chNN.omissions.json`（含 suggested_op 待审补丁建议，文件头注明绝不自动改正史）
- **facts 不可变 append-only**：首版 `graph/facts/chNN.fact.json`，重抽产 `chNN.fact.vN.json`（永不覆盖旧文件），`graph/index.json` 登记版本序列 + latest 指针；index 损坏视为空可重建，单章 facts JSON 损坏只影响该章重放
- **commit 挂钩**：`commit` 成功（canon 落盘 + state 推进）后自动触发抽取；任何异常只打印 `[graph] 警告…不阻塞 commit`。抽取客户端：**reader 通道（qwen3.8-flash，与 writer GLM 异构）**，`bible.book.extraction_model` 可覆盖模型名
- `commit` 同时推进 `arc.locked_through = max(locked, ch)`（M3A 起 commit 即锁定事件，旧格式直通章同样适用——滚动规划判界的基准）

### P-G2 · 最小地图

- 新增 **`map <书名> [--as-of N]`**：从 facts 重放（`replay_graph`，不持久化图状态）→ `graph/graph.json` + `graph/map.html`
- 节点四类：Character / Chapter / Event / Location；边五类：`PARTICIPATES_IN(role)`、`OCCURS_AT`、`CAUSES`（跨章 event id 引用）、`RELATES_TO(type, valid_from, valid_to)`（valid_to 由同对同型关系的后续重定义自动解析）、`KNOWS(fact, from_chapter)`。Item/Faction/ArcReflection/TRANSFERS_ITEM 明确未进
- `map.html`：**vendor Cytoscape 内联**（`tools/vendor/cytoscape.min.js` 已下载入库存放，373KB，渲染时读入内联成单文件、完全离线）；双视图切换（剧情因果 / 人物关系）、章节滑块过滤（事件按 chapter ≤ N，关系按 valid_from ≤ N < valid_to）、点击节点/边显示 evidence 原文
- **Mermaid 降级**：vendor JS 缺失时输出零依赖静态页（Mermaid 源码 + 说明），graph.json 照常产出
- `--as-of N`：只重放第 1~N 章，生成历史时刻地图

### tools/workbench-smoke.py（M3A 版）

- 主流程真实 LLM 断言新增：commit 后 `ch01.fact.json` 生成、fact 结构齐全（chapter/canon_revision/extractor_model）、**全部 evidence 为 canon 子串**、index 登记；commit ch2 后 facts 生成
- **12 章离线回归（验收 #2）**：`seed_12ch_book` 程序化建书（12 张合法卡）+ FakeClient 每章 3 个假回复（正文/delta/事实）跑满 12 章 write+commit → locked_through=12 → plan 展开 13-16（FakeClient 锚点回复 + 管道确认）→ planned 8→16、锚点入 arc、V2 卷激活、纪律窗口 4/8
- **遗漏检测用例（验收 #1）**：ch7 事实观察到 knowledge 变化而 delta 无 learn op → 警告 + `ch07.omissions.json`（suggested_op 结构断言）+ **state.knowledge 确认未被污染**（不自动改正史）
- **evidence 校验用例**：ch3 事实含伪造 evidence 事件 → 丢弃 + 警告出现在输出
- **facts 不可变**：重抽 ch1 → v2 文件、首版逐字不变、index latest 指针
- **图谱隔离（验收 #3）**：删整个 graph/ → status 正常、map 空图重建、ch12 重写+commit 正常且重抽恢复 facts
- **双书并行（验收 #4）**：BOOK12 与 smoke-wb 各自 map（标题隔离断言）+ 规划互不干扰（planned 16 vs 8）
- **legacy 可 map 可 plan（验收 #5）**：v1 迁移后 map 出图；`plan --extend 4` 被纪律截断为 1 章（planned 9）成功
- `--as-of 6` 重放断言；RELATES_TO/KNOWS 边的最小夹具单元断言
- 修掉 M2 版遗留 bug：flaky 防护分支里 `drafts_dir(BOOK, 1)` 未定义（NameError 隐患，改为 `wb.drafts_dir`）

## 为什么（设计要点）

- 图谱是纯派生层：graph.py 不 import state.py、不写 state；遗漏产出建议文件，正史仍只由 commit 流程推进
- 抽取与 delta 对照的意义：qwen（异构模型）从正文独立观察一遍状态变化，GLM writer 自报的 delta 漏登时由「待审补丁」提醒作者——模型互查而非自动合并
- facts append-only + index latest：正文/canon 修订后重抽不毁历史版本，M3B 修订传播可直接 diff 版本

## 工单未写明、由执行方裁决的决策

1. **`arc.compass` 与顶层 `bible.compass` 双写**：工单 v4 的 arc schema 含 compass，但 M1 起顶层 compass 已是权威且既有代码都读它。裁决：顶层权威，arc.compass 为每次保存刷新的镜像（满足工单结构），plan/status 读顶层。M4 若统一可做一次性搬迁。
2. **`planned_through` 语义重定义 + 旧书收敛**：M1 的 planned=total_chapters 与「不为远处写细纲」冲突。裁决：v4 起 planned 是细纲前沿，new 时 =min(total, 8)，旧书迁移时一次性收敛到 locked+8（打印迁移提示）；plan 从 max(planned, locked)+1 展开（兼容「写超前于规划」的作者）。
3. **commit 推进 `locked_through`**：工单 plan 判界用 locked_through，但 M2 里只有 lock 命令推进它——直写/直通章和离线 seed 卡场景永远无法触发 plan。裁决：commit 即锁定事件，commit 后 locked_through=max(locked, ch)。
4. **纪律超限的处置**：截断而非硬拒绝——`--extend N` 超出窗口时批量截断到窗口边界（打印警告），确认阶段再过滤一次越界锚点。理由：作者意图保留最大化，纪律由窗口硬约束保证。
5. **锚点落盘为字符串**：`"{arc_label}@第{ch}章（{amplitude}）｜{direction}"`。理由：arc.anchors 在 M1 起就是字符串数组（lock 回填、bible_summary/status 显示），结构化对象会破坏既有消费者；字符串内嵌全部提议字段不丢信息。
6. **抽取模型路由**：reader 通道（qwen3.8-flash）+ `bible.book.extraction_model` 覆盖模型名（api_style 跟随 reader 通道）。en 书如需 Codex 通道抽取，配 extraction_model 的同时需另配通道（本阶段未做，英文线数据后再议——与冻结范围一致）。
7. **`canon_revision` = commit 后的 state.revision**（而非 bible.revision）：事实版本跟着正史状态版本走，与 delta 的 base_state_revision 同一坐标系。
8. **facts 版本命名**：首版 `chNN.fact.json`、重抽 `chNN.fact.vN.json`（v≥2），index.latest 指针。工单只要求「新文件 + index 登记版本」，此命名让首版路径与工单 schema 示例完全一致。
9. **injury kind 不参与遗漏检测**：delta 白名单没有 set_injury op，对照恒误报；injury 观察保留在 facts 里（信息不丢），等 M3B+ 引入对应 op 再纳入。
10. **relationship 的 target 字段**：工单的 state_changes_observed schema 无 target，关系变化没有对象就无从对照 add_relationship。裁决：kind=relationship 时要求额外 `target` 字段（缺 target 丢弃并警告），属 schema 的显式扩展。
11. **KNOWS 边的落点**：边表里 KNOWS(fact, from_chapter) 没有对应的目标节点类型（四类节点里没有 Fact）。裁决：Character → Chapter 边、fact 字段携带事实 id。第一版子集内最克制的落法；图谱工作台若引入 Fact 节点可平滑迁移。
12. **RELATES_TO 的 valid_to 按 pair 闭合**（type 变更即终结）：同一对人物出现新的关系定义（无论 type 是否变化，如 同盟→决裂）时，旧边 valid_to 止于新边 valid_from 前一章。理由：章节滑块过滤「第 N 章时的有效关系」必须恰好一条，同盟与决裂同时生效是语义错误；type 变更正是关系演进的主场景。
13. **章节与事件的归属不设边**：Chapter↔Event 的从属由 event id（ev_chNN_NN）与 node.chapter 属性表达，不发明 HAS_EVENT 边——边类型严格保持工单五类。
14. **Mermaid 降级的形态**：vendor 缺失时输出零依赖静态页（Mermaid 源码文本 + 说明），不尝试加载 CDN mermaid.js——降级场景即「网络不可用」，任何 CDN 依赖都违背降级初衷。
15. **smoke 双书并行用 BOOK12 与 smoke-wb**：两者一个离线一个含真实产物，恰好验证互不干扰；books 总览命令（08f00c7 已有）不重复断言。
16. **state.py 零改动**：边界允许加只读方法，但图谱重放直接 `json.load` state 文件即可，不需要新入口——保持 reducer 文件不因派生层需求变动。

## 怎么测的

1. `python tools/workbench-smoke.py` 端到端：**92/92 项断言全绿**（真实 LLM 约 8 次 + FakeClient 离线段含 12 章回归；迁移副本程序化构造，可重复跑）
2. 模块级离线单测（临时脚本，不入库）：v4 迁移（clamp/volumes/compass 镜像）、normalize_fact（evidence 子串/未知 kind/relationship target/hooks 白名单）、遗漏对照、append-only+index、重放（as_of/边类型/valid_to）、渲染（vendor 内联 + Mermaid 降级）、plan 交互流（确认/修改/截断/V2 激活/纪律防线）
3. 验收标准逐条：

| 验收标准 | 结果 |
|---|---|
| 1. smoke 适配 + 指定断言（facts 生成/evidence 子串/遗漏警告/map 产物/plan 推进） | ✅ |
| 2. 12 章规模回归（FakeClient 写满 12 章 → plan 13-16） | ✅ |
| 3. 图谱隔离（删 facts 后 commit/write/status 不受影响，重抽恢复） | ✅ |
| 4. 双书并行 map/plan 互不干扰 | ✅ |
| 5. M1/M2 工作区迁移兼容（smoke-wb-legacy 可 map 可 plan） | ✅ |
| 6. git 干净提交 M3A 分支 + M3A-CHANGES.md | ✅（见本提交） |

## 未做 / 冻结（按工单范围裁定）

- M3B：修订传播（revise 命令、canon 修订 diff 回灌）、弧级反思记忆（ArcReflection）、完整四视图工作台——facts 版本化（决策 8）与 valid_to 解析已为其预留接口
- Item/Faction 节点、TRANSFERS_ITEM 边、弧级反思节点：明确不进 M3A
- en 书抽取通道覆盖（extraction_model 只覆盖模型名，api_style 跟随 reader 通道）：等英文真实连载数据后按冻结裁定处理
