# M2-CHANGES · 正史提交 / 角色认知 / 上下文投影 / 豁免状态（P2 + P3 + P4 + P6）

> 执行：ZCode · 分支 `hana/m2-canon-state`（M2 worktree）· 验收合同：docs/plans/M2-workorder.md（未改动）
> 基线：M1 已合入 main（a3fea2d → b2cb434）。硬边界沿用：engine.py 细胞语义、Ledger 类（含 shadows）零改动；不 merge/不 push/不改 main；stdlib only。

## 改了什么

### P2 · canon/drafts 分家 + STATE_DELTA + commit

- **新增 `src/harness/state.py`（reducer）**：`StoryState` 持有 `workspaces/<书>/state/story-state.json`
  （`{revision, as_of_chapter, characters:{id:{knowledge:{knows,unknown_to_them,false_beliefs}, location, injuries, inventory, relationships}}, facts:{}, hooks:{}, timeline:[], exemptions:[]}`）
  - `validate_delta(delta, draft_text, knowledge_rules=None) -> list[str]`：delta 结构、`base_state_revision == state.revision`（不匹配给明确错误）、op 白名单（`OP_SPECS` 显式注册：learn / set_location / set_inventory / advance_hook / add_relationship / set_false_belief）、必填字段、**evidence 必须是正文子串**、**learn 与 never_learn 冲突硬拒绝**（never_learn 规则由调用方从 bible 人物卡传入，state 层保持零耦合）
  - `commit_delta`：全部通过后先备份 `story-state.json.bak-{revision}`（首次提交也留初始态备份），应用 ops、`revision += 1`、`as_of_chapter` 推进、timeline 记录，临时文件 + `os.replace` 原子落盘
  - 豁免 API（P6）：`add_exemption`（指纹 `sha1(rule|chapter|entity|source_text_hash)[:16]`）、`active_exemptions`（正文 hash 变化即失效）、`filter_flags`（lint 汇报过滤，规则名按短名匹配，`style.分节碎` 与 `分节碎` 等价）
- **write 改造**：正文 → `drafts/v{NNN}.md`（版本递增）+ `v{NNN}.lint.json`（flags/checks/evidence + `source_text_sha1`，豁免指纹绑定此 hash）+ `v{NNN}.delta.json`（状态变更提案）
  - delta 由**单独一次 LLM 调用**从正文提炼（不污染 writer 正文纯度）；op 预清洗：name→id 改写、非白名单/缺字段/evidence 非子串的 op **丢弃并逐条警告**；`base_state_revision` 由代码写入（=写时 state.revision）
  - 状态机：`branching → discussed → locked → drafted → committed`（M1 的 `written` 迁移为 `drafted`）
  - **前文只读 canon**（正史截断核心）：`prev_canon_texts()` 只取第 1~N-1 章 `canon.md`；迁移期无 canon 才回退最新 draft/旧 chNN.md 并显式标注来源
- **新增 `commit` 命令**：`python workbench.py commit <书名> <章号> [--revised <文件>]`
  1. 读最新 draft + 对应 delta → `validate_delta`（`--revised` 时 evidence 同时针对修订版）
  2. 有违规：打印清单退出码 1（作者手工修 delta.json 后重跑）
  3. 无违规：打印 ops 清单与提炼句 → 作者 `y` 确认 → 写 `chapters/chNN/canon.md` → `commit_delta` 原子推进 → card 的 `recorded_consequence` 回填（自动提炼或作者输入）→ 状态 `committed`
  4. 重复 commit 同一 delta 会因 revision 不匹配被拒（幂等保护）

### P3 · 人物卡四分区

- `bible.characters[]` 升级（migrate v2→v3 自动补默认）：`id` / `anchors` / `voice.forbidden` / `voice.mes_example` / `knowledge_rules{learn:[{fact_id,when}], never_learn:[fact_id]}` / `lorebook[{fact_id, keywords, content_ref}]`
- **name→id 全线迁移**：`_migrate_to_v3` 按序生成 `char_{NN}`；meta.card 与 **card.json 文件**（文件权威）里的 `pov.character` / `pressure[].char` 改写为 id；`lock` 产出前再归一一次（LLM 填了名字自动纠正）；delta 的 `character_id/a/b` 在 write 预清洗时改写；`validate_card` 以 id 为主、name 兼容接受
- 动机栈对 writer 仍全量可见（决策 0003 不变）；`char` 命令交互式输入新字段（锚点/禁说/对话样本/learn/never_learn/lorebook），id 自动生成
- writer 上下文补「人物 id 对照」行（两种模式都注入），避免引擎指令里的 id 与人物列表的名字对不上

### P4 · HOT/WARM/COLD 投影

- **新增 `src/harness/context.py`**：`build_context(bible, state, spec, chapter, config) -> {hot, warm, cold}`
  - HOT：章节卡合约块（目标/阻力/选择/代价/读者承诺/结尾/对话密度/允许与禁止）+ `build_engine_directive`（细胞语义复用，engine.py 零改动）+ 出场人物（pov+pressure 引用）动机栈+声口卡（mes_example 取 1 条）+动态状态（state）+ `Ledger.directive_for` + 前一章 canon 末 300 字 + id↔name 对照
  - WARM：最近 2 章 canon 摘要（各 200 字，确定性首尾截取，零 token）、未闭合 hook（ledger 未到期 + state.hooks 非 payoff）、弧锚点、出场人物关系
  - COLD：只返回**清单**（bible/shadow 条数/未到期 reveal_plan 条数），不携带任何内容；模块内不存在把 COLD 拼进 writer 上下文的路径
- **开关**：`bible.book.context_projection`（默认 false）。false=写路径走 M1 的 `build_writer_messages("E",…)`（全文历史 + 完整暗账，行为等价 M1，前文来源已切 canon 优先）；true=system + hot+warm 拼装。`SafeLedger`（空暗账兜底，M1 的 `_LedgerSafe`）收编进 context.py 供两条路径共用

### P6 · 豁免即状态

- 新命令 `exempt <书名> <章号> <规则> <理由>`：读该章最新 `vNNN.lint.json`，规则按短名匹配 flags，登记 `state.exemptions[]`（指纹绑定 lint 时的正文 hash）
- write 的 lint 汇报过滤已豁免项并注明「N 项已豁免」；正文改动（hash 变化）后豁免自动失效，finding 重新出现
- `style_lint.py` 零改动（豁免过滤在 state/workbench 层做）

### tools/workbench-smoke.py（M2 版）

主流程真实 LLM（投影关）：new(v3) → char(v3 seed) → discuss → lock（断言卡里 pov/pressure 已是 id）→ write（断言三件套 + lint hash 绑定 + 不产 canon）→ commit（断言 canon=draft 全文、revision=1、.bak-0 存在、recorded_consequence 回填、learn 推进 knowledge）→ 重复 commit 被拒（revision 不匹配）。

离线段（FakeClient 假客户端，零 LLM）：
- 投影开：写 ch2 上下文**不含 ch1 drafts**（draft 追加 DRAFT-ONLY-MARKER，canon 不受影响）、前章 canon 尾部进 HOT、WARM 有摘要/未闭合钩子/锚点、无 E 臂全文暗账、无 COLD、无 shadows、章节卡合约与对话密度进 HOT
- 投影关：M1 E 臂形态（`完整的伏笔设定`+`已完成的章节`），前文仍是 canon（不含草稿独有内容）、never_learn 冲突写阶段提前警告（不丢弃）
- delta 预清洗：name→id、非白名单 op 丢弃、evidence 非子串丢弃、`base_state_revision` 取自代码
- **commit ch2（验收 #5 的确定性覆盖）**：`state.revision` 推进到 2、`characters.char_01.knowledge.knows` 含 F1_HOOK、`location` 回填、`.bak-1` 存在
- 豁免生命周期：确定性短段正文触发「分节碎」→ exempt 成功 → filter 后不再报 → 正文改动后自动失效
- state.py 4 组负样本（revision 不匹配 / 非白名单 / 非子串 / never_learn 硬拒绝）各自给出明确错误
- 投影单元断言：shadows 内容与 COLD 块绝不进 hot+warm

迁移段：
- **smoke-wb-m1copy**（按 M1 提交态程序化构造的 M1 格式副本，可重复跑）：status 不报错并迁移 v2→v3（id 生成、card.json 文件改写、written→drafted、投影默认关）→ write 续写出 v002（跨迁移版本递增）+ delta/lint → commit 建正史（canon + state revision=1 + 备份）
- **smoke-wb-legacy**（v1 cell 格式）：status 迁移（cell 原样保留、包装卡 id 化）→ 细胞指令逐字等价 → write 直通（fake client）出三件套 → commit（无卡跳过 recorded_consequence 回填，state 推进）

## 为什么（设计要点）

- state 是唯一动态状态权威，只有 `state.py` 改它；workbench 只调 validate/commit/exempt API
- delta 与正文分离生成：writer prompt 不变（正文纯度不降），delta 用独立调用提炼后再做 evidence 子串校验
- 前文来源 canon 优先、draft 仅作迁移期回退并标注：工单「只读 canon」与验收 3「M1 数据迁移续写」的交集成（见决策 1）

## 工单未写明、由执行方裁决的决策

1. **前文来源的迁移期回退**：投影关/开都优先读 canon.md；该章无 canon（M1 迁移期）回退最新 draft/旧 chNN.md 并在上下文里标注「迁移回退」。投影开的严格 canon-only 适用于有 canon 的章。理由：验收 3 要求 M1 数据能续写，而迁移期没有 canon。
2. **delta 单独调用提炼**：write 内第二次 LLM 调用（tag `delta-chNN`）从成稿提炼 ops，不要求 writer 顺带输出 JSON。
3. **never_learn 规则的传入方式**：`validate_delta` 接受 `knowledge_rules` 参数（workbench 从 bible 人物卡组装），state.py 不直接读 bible——reducer 保持零耦合、可独立测试。
4. **写阶段 never_learn 只警告不丢弃**：硬拒绝的唯一权威在 `validate_delta`（commit 时）；写阶段提前打印警告，delta 原样保留，避免两处裁决不一致。
5. **op 语义细节**：`set_inventory` value 为 str 时追加（去重）、为 list 时整体置换；`advance_hook.action` 接受任意非空串（plant/develop/payoff 为约定值）存入 `hooks[id].status` 并保留 history；`add_relationship` 存在 a 的 `relationships[b]` 下。
6. **首次 commit 也留备份**：state 文件尚不存在时，把初始态写入 `.bak-0`，保证「commit 后备份存在」无条件成立。
7. **豁免的正文 hash 基准**：绑定 lint 存档里的 `source_text_sha1`（lint 时的正文），有效性比对用「该章当前文本」（最新 draft 优先、无 draft 用 canon）；正文一改即失效。lint 存档保存全量 flags，过滤只发生在汇报层。
8. **豁免规则匹配**：按「短名」匹配（最后一个 `.` 之后的部分，大小写不敏感），`style.分节碎` 与 flag `分节碎` 等价；规则不在 flags 时报错并列出现有 flags。
9. **M1 卡的 id 迁移波及 card.json 文件**：文件权威原则下，迁移同时改写 card.json（legacy cell 的包装卡也统一 id 化，但 `meta.cell` 深拷贝后原样保留——修掉了浅拷贝共享嵌套引用的隐患，cell 是 v1 行为路径）。
10. **`written → drafted` 状态改名**：M1 的 written 语义（草稿已产）在 M2 归入 drafted；★ 标记让位给 committed（正史），drafted 用 ▧。
11. **E 臂在投影关模式保留 `full_text()`**：工单 P4 硬约束说 full_text 仅供臂 A/B 实验与作者规划，但验收 2 要求投影关「行为与 M1 等价」（M1 写路径含 full_text）。取舍：投影关保持 M1 行为不动，投影开严格不用 full_text。已按「工单未覆盖处」记录，供 Hana 裁决是否在 M3 收紧。
12. **smoke 的离线策略**：需要真实生成的部分（讨论/锁卡/两书写作共 6 次调用）跑真实 LLM；状态机/校验/投影/豁免等确定性逻辑全部用 FakeClient + seed 离线覆盖（含验收 5 的确定性 state 推进断言）。

## 怎么测的

1. `python tools/workbench-smoke.py` 端到端：**58/58 项断言全绿**（真实 LLM 6 次 + FakeClient 离线段；脚本按 M1 提交态程序化构造迁移副本，可重复跑）
2. 模块级离线单测（临时脚本，不入库）：state 四组负样本 + commit/备份 + 豁免失效 + 迁移链（v1→v3、v2→v3 含 card.json 文件改写）+ build_context（HOT/WARM 内容、COLD/shadows 隔离）+ SafeLedger
3. 验收标准逐条：

| 验收标准 | 结果 |
|---|---|
| 1. smoke 适配端到端 + 指定断言清单 | ✅（见上 smoke 描述） |
| 2. 投影双模式都通过（false=M1 等价） | ✅（主流程=关；ch2 假客户端双模式对照） |
| 3. M1 格式工作区迁移续写不报错 | ✅（smoke-wb-m1copy：迁移+续写+commit） |
| 4. state.py 4 组负样本明确错误 | ✅ |
| 5. 手动验证 commit 后 state 推进 | ✅（smoke 内 commit ch1/ch2 后断言 revision/knowledge/location/备份） |
| 6. git 干净提交 M2 分支 + M2-CHANGES.md | ✅（见本提交） |

## 未做 / 后续里程碑

- revisions/ 只建目录约定，修订历史与 revise 命令 → M3（P7+P8）
- `unknown_to_them`/`injuries` 字段已入骨架但尚无对应 op（工单白名单未列）；如需 `set_injury`/`forget` 等 op，在 `state.OP_SPECS` 显式注册即可
- HOT/WARM 摘要为确定性截取（零 token）；更高质量的摘要可挂 M3 修订资产
