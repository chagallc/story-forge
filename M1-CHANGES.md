# M1-CHANGES · 章节卡与多线推演（P0 + P1 + P5）

> 执行：ZCode · 分支 `hana/m1-chapter-card`（M1 worktree）· 验收合同：docs/plans/M1-workorder.md（未改动）
> 参照：docs/plans/v2-整合方案.md 裁决一/二 · 硬边界：engine.py 细胞语义零改动，ledger/shadows/Ledger 零改动

## 改了什么

### P0 · 数据层定型

- **story-bible.json 升级 schema v2**（`workbench.py`）
  - 新增顶层字段：`schema_version: 2`、`revision`（每次 `save_bible` 自增的整型计数器）、`compass`（ending_direction / reader_promise / active_long_line_ids）、`shadows: []`（仅占位，结构与语义未动）
  - `arc` 新增 `locked_through`（lock 时推进）、`planned_through`（new 时默认=规划章数）
  - `new` 命令直接产出 v2；`save_bible` 保存前防御性补默认字段（`_ensure_defaults`，幂等）
- **旧格式自动迁移**（`migrate_bible`）
  - `load_bible` 检测到无 `schema_version` 的 bible → 立即迁移并落盘（一次性升级）：补默认字段；`chapters[n].cell` 包装为 `card = {chapter, engine(=cell 去掉 chapter 键), legacy: true}`，`meta.cell` 原样保留
  - 迁移幂等：v2 文件不会二次触发
- **spec 派生化**（`bible_to_spec`）
  - 产物落盘 `workspaces/<book>/build/spec.json`，带 `_generated = {from, bible_revision, generated_at}` 标记；bible 是唯一人工写入口，spec 可随时删除重建
  - 函数签名从 `bible_to_spec(bible)` 改为 `bible_to_spec(book, bible)`（需要 book 定位落盘目录）

### P1 · 章节卡 card.json

- **新增 `src/harness/schema.py`**：`validate_card(card, bible, expected_chapter=None) -> list[str]`（空列表=通过）
  - 工单规定项全部覆盖：必填字段（章节卡 16 项 + engine 细胞字段族 + engine.pressure）、`chapter` 为 int（可选与目标章号比对）、人物必须在 `bible.characters`（pov.character 与 pressure[].char）、`amplitude`/`end_hook`/`pressure.motive` 枚举、`force` 与 `plan/disruption` 同源
  - `end_hook` / `reader_promise.type` 枚举按 `bible.book.language` 切换（zh 四值 / en 四值，见下文「工单未写明的决策」）
  - 同源启发式：zh 取 CJK 二字组+英数词、en 取去停用词词元，要求 force 与 plan∪disruption 词袋有交集
  - 另校验：`base_state_revision` 为 int、`choice.irreversible` 为 bool、`dialogue_budget.min_ratio` 为 0~1 数字、三个 id/developments 字段为字符串数组、`recorded_consequence` 为 null 或字符串
- **card.json 目录结构**：`chapters/chNN/card.json` + `chapters/chNN/drafts/`（lock 成功后创建）
- **章节卡解析权威顺序**（`load_card`）：`card.json`（card_path 存在时，作者可改文件后直接重跑 write）> `meta.card`（内嵌镜像）> 旧 `meta.cell`（legacy 直通）
- **`discuss` 两阶段**（P5 多线推演并入）
  - 阶段一：LLM 产出 3 条轻量分支（工单 schema：id/summary/beats/choice/motive_cost/reader_payoff/risks），落盘 `discussions/chNN.branches.json`，作者输入分支 id 选择；`regen` 可重新生成，`quit` 放弃（分支文件已存档）
  - 阶段二：围绕选中分支深入讨论——原有 REPL 保留（AI 先行、`lock` 结束、`quit` 放弃），讨论记录存 `discussions/chNN.jsonl`
  - bible 章节元数据新增：`branches_path`（workspace 相对路径）、`selected_branch`；状态机新增 `branching`（分支已生成未选择）
- **`lock` 生成完整章节卡**
  - 素材 = 讨论记录 + 选中分支（无讨论记录也可仅凭分支 lock，反之亦然）
  - LLM 输出严格 JSON → `validate_card` 校验 → 不过则把违规清单反馈 LLM 重试（最多 2 次）→ 通过后打印全卡，作者 `y` 确认才落盘 card.json
  - 落盘同时：bible 章节元数据写 `status=locked / card_path / card`，**移除旧 `cell` 键**；`arc.locked_through` 推进；弧线锚点按 `card.engine.arc_label` 回填（沿用 v1 行为）
  - `base_state_revision` 由代码写入（= 锁定时 bible.revision），不采信 LLM 输出
  - 对已锁定章节重跑 lock 需二次确认（覆盖 card.json）
- **`write` 硬门禁**
  - 无章节卡（`load_card` 返回 None）或 `validate_card` 有违规 → 打印违规清单并以退出码 1 拒绝落笔
  - 例外：旧格式 `meta.cell` 直通（见「决策 2」），打印提示行，行为与 v1 等价
  - 正文产出到 `chapters/chNN/drafts/vNNN.md`（v001 起，重写自动递增版本号）；不再写 `chapters/chNN.md`
  - 前文读取（`latest_text`）：优先该章最新 draft，回退旧格式 `chNN.md`（兼容旧 workspace 续写）
  - lint、金丝雀检查、E 臂管线全部沿用
- **`status`**：新状态 `branching`（◦）入板；显示 `compass`（非空时）、locked/planned/revision 进度行；章节行显示 card.engine 摘要，legacy 章节标注 `(旧cell)`

### tools/workbench-smoke.py（适配版）

- 主流程改为 `new(schema v2 管道喂入) → char(手工 JSON seed) → discuss(seed 分支文件 → 选 A → REPL) → lock(y 确认) → write → status`，每步断言；分支 seed 采用 `discussions/chNN.branches.json` 格式（工单指定，不再 seed 旧 discussion）
- 新增断言：v2 字段齐全、card.json 过 validate_card、meta 无 cell、locked_through/锚点回填、build/spec.json 带 _generated、旧路径 chNN.md 不再产出
- 新增 **write 硬门禁负样本**：坏卡（错枚举）与无卡章节（从未 lock 的第 2 章）两种情况必须以退出码 1 拒绝且不新增 draft（不耗 token）；另断言 card.json 缺失时 `load_card` 回退 `meta.card` 镜像
- 新增 **迁移兼容段**（`workspaces/smoke-wb-legacy`）：旧格式 bible → status 不报错且自动迁移落盘 → `meta.cell` 包装为 card.engine → 迁移前后 `build_engine_directive` 输出逐字等价 → write 直通产出 drafts/v001.md
- 新增 **schema 负样本 5 组**（验收 #3）：缺字段 / amplitude 错枚举 / end_hook 错枚举 / 未知人物（含错 motive）/ force 不同源，逐组断言给出明确违规信息
- 汇总 PASS/FAIL 计数，任一失败退出码 1；子进程统一 `PYTHONIOENCODING/PYTHONUTF8=utf-8`（Windows 管道中文兼容）
- smoke 每次清空重建 `workspaces/smoke-wb`（v1 版保留旧状态跳过 seed，card 流程需要确定性起点）；新格式不再产出 `chapters/ch01.md`，该跟踪文件在本分支删除，产物移至 `drafts/v001.md`

## 为什么（设计要点）

- 细胞语义零改动：`card.engine` 经 `cell_of()` 透传给 `spec.engine.cells`（仅补 `chapter` 键，engine.py 的 `cell_for` 契约），新旧细胞指令逐字等价（smoke 有断言）
- card.json 是作者确认后的文件权威；`meta.card` 是 bible 内镜像。不一致时以文件为准，作者改完 card.json 重跑 write 即生效
- 写入路径与 v1 的差别只在「卡」这一层：讨论多线（分支）只写 `discussions/`，不动 canon/state/ledger（本里程碑无后三者）

## 工单未写明、由执行方裁决的决策

1. **card.json 文件权威**：card_path 指向的文件存在时优先于 bible 内嵌 meta.card。理由：作者手工修卡后无需同步 bible。
2. **旧格式 write 直通**：带 `meta.cell` 的章节跳过章节卡校验（打印提示）。理由：工单同时要求「硬门禁」与「旧格式 write 行为等价」，二者只能这样共存；新 lock 会移除 cell，彻底转入校验路径。
3. **`revision` 语义**：bible 每次保存自增；`base_state_revision` = lock 时刻的 revision。理由：M2 commit 校验需要可比对的单调基线，M1 先落地计数。
4. **en 书枚举**：`end_hook` 在 en 书用 new-information|dilemma|about-to-act|quiet-close（与 v1 lock prompt 及 engine.py `HOOK_KEYS_EN` 一致）；`reader_promise.type` 用 info|emotion|event|visual。zh 书维持工单中文枚举。
5. **`recorded_consequence` M1 恒为 null**：蓝图定义其由正文提交（commit，M2）回填，M1 不做半吊子填充。
6. **分支数量与 ids**：固定 3 条（工单「默认产出 3 条」），id 由 LLM 给出、代码兜底规范为 A/B/C；`_normalize_branches` 对缺失字段做防御性补全，避免讨论环节崩溃。
7. **同源启发式的词袋**：zh 用二字组（无分词依赖，stdlib only），宁松勿紧——巧合重叠只会放宽，不会误杀合规卡。
8. **smoke-wb 产物照旧入库**：沿用仓库既有实践（v1 即跟踪 smoke 产物），最终 smoke 通过后的状态随本分支提交。
9. **空暗账兜底（`_LedgerSafe`）**：`Ledger.directive_for` 对空 entries 会 `max()` 空序列崩溃（v1 起就存在，`new` 建的书默认 `ledger: []`，验收流程 #4 的「new → write」必踩）。Ledger 类不许动，故在 workbench 侧用子类兜底：entries 为空时返回「无特殊指令」行，非空时行为与 Ledger 完全一致（防火墙语义不变——空账本无底牌可泄）。
10. **smoke 主书 seed 暗账**：与 v1 smoke 一致给 smoke-wb seed F1 暗账条目（lock 提示的 allowed/active_hook_ids 由此而来），保证走的是非空 Ledger 主路径；空账本路径由 `_LedgerSafe` 兜底。

## 怎么测的

1. `python tools/workbench-smoke.py` 端到端通过：**37/37 项断言全绿**（含上述全部断言；LLM 章节卡一次过验）
2. discuss 阶段一真实生成路径（smoke 用 seed 分支文件，此路径另行手动验证）：无分支文件的章节跑 `discuss` → LLM 产出 3 条分支（id/summary/beats×5/choice/motive_cost/reader_payoff/risks 字段齐全）→ 落盘 branches 文件、状态 `branching` → `quit` 后分支文件保留可重选
3. 离线单测（临时脚本，不入库）：`validate_card` 对合法卡零违规 + 7 组非法卡（含缺 pressure、chapter 非 int）逐一给出明确违规；迁移/文件权威/透传等价/revision 递增/迁移幂等
4. 验收标准逐条核对（工单 1~5）：见下

| 验收标准 | 结果 |
|---|---|
| 1. smoke 适配 card 流程端到端通过 | ✅（分支 seed 格式 + 全流程 37/37 断言） |
| 2. 旧格式 meta.cell 的 bible 跑 status/write 不报错且行为等价 | ✅（smoke 迁移段：自动迁移 + 细胞指令逐字等价 + write 直通） |
| 3. schema.py 对 5 组非法 card 给出明确违规信息 | ✅（smoke schema 负样本段：缺字段/错枚举×2/未知人物/不同源） |
| 4. 新建测试书走完 new → char(手工JSON seed) → discuss(选分支) → lock → write | ✅（smoke 主流程即该流程） |
| 5. git status 干净，提交到 M1 分支 | ✅（见本提交） |

## 未做 / 后续里程碑

- commit / canon / STATE_DELTA / recorded_consequence 回填 → M2（P2+P3+P4+P6）
- 滚动规划（planned_through 目前仅在建书时固定）→ M3（P7）
