# Story Forge 立项评审意见 · 黑塔

> 视角：代码库模块级分析。所有结论基于对 `reference/ainovel-cli`（401 文件）与 `reference/generative_agents`（persona 全模块）的实际源码阅读，非印象判断。引用均给出具体文件路径。

---

## 一、结论先行

1. **立项成立，架构方向对，但核心假设未经验证且验证成本被低估。** 两个参考库恰好拼出防火墙所需的全部零件：ainovel-cli 提供"确定性协调 + 事实账本 + 事务性提交"，generative_agents 提供"按角色隔离的记忆流 + 已验证无泄漏的对话协议"。
2. **真正瓶颈不是协调成本，是一致性仲裁**：防火墙删掉的恰恰是一致性检查所需的信息。ainovel-cli 的 `check_consistency` 之所以能工作，是因为它把全量伏笔/规则/关系摊给 Writer 自查——防火墙一旦立起，这个机制立即失效，必须换成"持密者仲裁"。**每一次一致性修复都是一个潜在泄漏通道**，这是本架构的内生矛盾，不是工程细节。
3. **"伏笔暗账"在两个参考库中都不存在，必须从零设计。** ainovel-cli 的 `ForeshadowEntry`（`internal/domain/review.go:12`）只有 `ID/Description/PlantedAt/Status/ResolvedAt`——它是**过去时账本**，记录"埋了什么"，不含"何时回收、怎么回收"。未来走向实际存在于 Architect 的大纲（`OutlineEntry.Hook/CoreEvent`）和 `StoryCompass.OpenThreads` 里，而这些恰恰全在 Writer 可见或半可见范围内。
4. **最可能错的假设**（详见问题五）：把"提前泄底"归因于信息共享而非模型行为倾向。若泄底是 RLHF 训练出的"闭合倾向"，防火墙挡不住 Writer 自发编造的暗示。**因此 MVP 必须是三臂对照，不是两臂**——否则验证的是"多 agent 分工有用"，而不是"防火墙有用"。
5. 防火墙落地选型：**工具层静态可见性配置**最干净。落点明确：ainovel-cli 的 `internal/agents/build.go` 已经按 agent 组装不同工具集，只差把共享的单例工具换成按调用方身份定制的实例。

---

## 二、逐题回答

### 问题 1：真正的瓶颈在哪里？

排序（置信度从高到低）：**一致性仲裁 > token 成本 > 协调成本 > 涌现**。

| 候选瓶颈 | 判断 | 依据 |
|---|---|---|
| 一致性仲裁 | **是真瓶颈** | ainovel-cli 的 `check_consistency.go:70` 直接返回 `LoadActiveForeshadow()` 全量活跃伏笔给 Writer 自查——防火墙世界里这个工具不能存在。信息不对称与一致性检查天然冲突：持密者（事件 agent）必须兼任仲裁者，而仲裁结果传导回 Writer 时（"第 3 章这段描写与暗账冲突，请改"）本身就可能泄漏暗账内容 |
| token 成本 | 高风险，量级 5-10× | generative_agents 的 `agent_chat_v2`（converse.py）每句对话 = 1 次关系总结 + 1 次检索 + 1 次生成 + poignancy 评分，一场对手戏 8 轮上限 ≈ 30+ 次调用；加上事件 agent、叙述者、读者模拟器，单章成本是单体写作的数倍。ainovel-cli 单章已是几十次调用 |
| 协调成本 | 不是瓶颈 | ainovel-cli 的 `flow/router.go` 用纯函数查表路由解决了这个问题，且是零 LLM 开销。照抄即可 |
| 涌现不出情节 | 不是主要风险 | 只要有事件 agent 强制注入钩子（正负向命运之手），情节不会断。真正的风险反而是**涌现出太多情节**：角色 agent 自由对话会产生叙事噪声，需要叙述者强力裁剪 |

补充一个任务书没问但更尖锐的：**重写传播**。小说必然返工。ainovel-cli 为此专门设计了 `RestoreOwnPlants`（`domain/review.go:30`，重写时补回本章种下的伏笔 plant，防止链断裂）和 `revision/projector.go` 的全量事实重放。而 generative_agents 没有任何重写路径——**角色记忆不会忘记已被改写掉的正史**。"角色记着一段被删掉的剧情"是防火墙架构特有的新问题，需要一个"正典 diff 广播者"（只能由事件 agent 担任）。

### 问题 2：信息防火墙怎么落地最干净？

**结论：工具层权限过滤 + 静态配置起步，导演 agent 动态裁定作为二期。**

三条路线对比：

| 路线 | 评价 |
|---|---|
| 静态可见性配置（工具层） | ✅ 首选。可测试（见问题 4 的金丝雀测试）、可审计（每次拒绝读取留日志）、零额外 LLM 开销。ainovel-cli 已有现成插入点 |
| 导演 agent 动态裁定 | 二期再上。导演本身是 LLM = 新的泄漏面 + 不确定源 + 每次裁定都是成本。动态裁定规则（"这个钩子现在可以给 Writer 了吗"）完全可以先写成确定性谓词 |
| 上下文层过滤（组装 prompt 时裁剪） | ❌ 最差。信息已经流进同一个进程/上下文组装器，泄漏面无法收敛，且 `novel_context` 这种大杂烩工具会越改越乱 |

具体落地路径（借 ainovel-cli 的骨架）：

1. **给工具加调用方身份**。现状：`internal/agents/build.go:119` 所有 worker 共享同一个 `contextTool` 单例，`Execute(ctx, args)` 签名里没有调用者概念——这是防火墙最大的结构性障碍。改法：`BuildWorkers` 里按 agent 实例化各自的 `ContextTool`，构造时注入 `VisibilityScope`（可读分区白名单）。
2. **账本拆双视图**。`store/world.go` 的 `LoadActiveForeshadow()` 拆成：`LoadDueHooks(chapter)`（事件 agent 视角投影：本章可埋钩子的"表象描述+情绪基调+显著性"，不含回收时机与走向）与 `LoadLedger()`（仅事件 agent 可调）。写入侧同理：`UpdateForeshadow` 的 `plant` 权限从 Writer 手里收走到事件 agent。
3. **角色记忆按 generative_agents 模式天然隔离**（见问题 3），对话层已经验证过无泄漏。
4. **审计线**：所有跨防火墙数据流必须经过显式投影函数，投影函数清单即防火墙的"创作对象"——这与 README"防火墙规则是真正的创作对象"的定位一致。

### 问题 3（重点）：哪些模块原样借鉴，哪些必须改造？

#### ainovel-cli —— 原样借鉴

| 模块 | 路径 | 借什么 |
|---|---|---|
| 纯函数路由 | `internal/flow/router.go` + `flow/state.go` | `Route(State) *Instruction` 模式：所有路由事实显式声明在 State、路由内禁止读 Store、查表优先+语义兜底。这是多 agent 协调的零成本解，直接照抄结构 |
| 引擎死循环防护 | `internal/host/engine.go`（`trackDeadlock`/`handleWorkerError`） | 同指令 3 次咨询仲裁、5 次熔断 + 同键先重试一次再升级的模式。多 agent 冲突时必然用到；`precheck` 的"写作目标未展开→确定性改派 architect"模式可直接改造成"事件 agent 尚未下发钩子→不许 Writer 自由发挥"，这是**防火墙版的正向死锁预防** |
| 伏笔账本数据结构与状态机 | `internal/domain/review.go:11-25` + `internal/store/world.go`（`UpdateForeshadow`） | plant/advance/resolve 三态 + 未知 ID 拒绝 + `RestoreOwnPlants` 重写保护。语义完备，直接搬 |
| 章节提交 Saga | `internal/tools/commit_chapter.go` + `store/signals.go`（PendingCommit） | 冻结载荷、崩溃重放、阶段推进的事务模式。多 agent 并发写事实时这个模式从"优雅"升级为"必需" |
| 指南针滚动规划 | `internal/domain/story.go`（`StoryCompass`/`VolumeOutline.Final`/`FinaleVolume`） | 不预设全书骨架、卷边界时更新方向、"收官事实可从数据推导无需撤销工具"的设计哲学。这是长篇不断膨胀问题的正解 |
| per-agent 工具装配 + 终态即停 | `internal/agents/build.go`（工具集分装、`StopAfterTools: commit_chapter`、StopGuard） | 防火墙的插入点就在这里；StopGuard 模式保证 Writer 不能带着半成品逃逸 |
| 上下文压缩档案 | `internal/agents/context_manager.go` + `agents/ctxpack/` | ToolResultMicrocompact + 角色差异化压缩档案（novel_context 结果可清理、写工具结果保留）——防火墙世界的上下文更长（各 agent 视角不同），压缩会更早成为必需 |

#### ainovel-cli —— 必须按防火墙思路改造

| 模块 | 路径 | 为什么要改 | 怎么改 |
|---|---|---|---|
| 上下文工具 | `internal/tools/novel_context.go` + `novel_context_builders.go` | **最大泄漏面**。单例工具无调用方概念；`buildChapterContext`（builders.go:358→571）把全量活跃伏笔塞进 Writer 的 episodic_memory；`check_consistency.go:70` 再次全量摊牌；`next_chapter_outline`（builders.go:466-468）把下一章大纲（含 Architect 规划的 hook/core_event，即未来走向）直接给 Writer | 按 agent 实例化 + VisibilityScope；伏笔改投影视图；下一章预告改为事件 agent 签发的"钩子指令"，而不是大纲原文 |
| 一致性检查 | `internal/tools/check_consistency.go` | 它的哲学是"给全量数据让 LLM 自查"，与防火墙互斥 | 拆成两层：机械规则检查（`internal/rules/` 的 lint 思路，可保留给 Writer）+ 持密仲裁（事件 agent 对照暗账审 prose，只回传"改哪、往哪个方向改"，不回传为什么） |
| Writer 自主埋伏笔 | `assets/prompts/writer.md`（执行协议）+ `commit_chapter` 的 `foreshadow_updates` 参数 | 现在 Writer 是伏笔的**作者**（自己决定 plant 什么）；Story Forge 要反转成 Writer 是伏笔的**执行者**。这个所有权反转是整个项目的核心创新点，也是最大的改造量 | `foreshadow_updates` 的 plant 权限移交事件 agent；Writer 提交后由事件 agent 验证"钩子确实埋了"（prose 中检索钩子要素） |
| 仲裁者 | `internal/arbiter/`（intervention.go/failure.go） | 现职责是用户干预分诊，无信息隔离概念 | 保留审计落盘（DecisionRecord）和事实包模式，但 Story Forge 的"导演"职责先不实现为 LLM——见问题 2 |

#### generative_agents —— 原样借鉴（算法与协议，代码当参考实现）

| 模块 | 路径 | 借什么 |
|---|---|---|
| 记忆检索打分 | `persona/cognitive_modules/retrieve.py`（`new_retrieve`/`extract_recency`/`extract_importance`/`extract_relevance`/`normalize_dict_floats`） | 时效×重要×相关的完整实现约 100 行，可直接移植：recency 用 0.995 指数衰减按 last_accessed 排序、importance 用 poignancy、relevance 用焦点句 embedding 余弦，各维度归一化后加权（gw=[0.5,3,2]）。**注意 recency 是访问衰减不是创建衰减**——被检索命中的记忆更"鲜活"，这个细节对角色塑造很关键 |
| 记忆流数据结构 | `persona/memory_structures/associative_memory.py`（`ConceptNode`） | type（event/thought/chat）+ s-p-o 三元组 + poignancy + filling（证据节点 ID 列表）+ depth（反思深度）。**per-persona 独立存储**（`persona.py:__init__` 每个角色从自己的 bootstrap_memory 目录加载）——天然防火墙，零改造 |
| 反思机制 | `persona/cognitive_modules/reflect.py` | 累计重要性超阈值触发 → 从最近事件生成焦点 → 检索 → 生成带证据的洞察 → 以 thought 节点入库（depth = max(证据 depth)+1）。**角色错误信念的免费来源**：角色只对自己感知过的东西反思，没感知到的真相永远不会出现在它的洞察里 |
| 对话协议 | `persona/cognitive_modules/converse.py`（`agent_chat_v2`） | **已验证的天然防火墙**：逐句生成，每句从说话者自己的记忆流检索（focal = 关系总结 + 对方在做什么 + 最近 4 句对话），prompt 里只有自己的 ISS、自己的记忆、双方公开的对话记录、对方名字——**对方私有记忆不进 prompt**（已核对 `run_gpt_prompt.py:2821` 的 `create_prompt_input`）。角色 sub agent 博弈产生对白，这个轮转骨架直接可用 |

#### generative_agents —— 必须重写

| 模块 | 路径 | 为什么 |
|---|---|---|
| 全部物理世界耦合 | `plan.py`（wake_up_hour/每小时日程/sector/arena/game_object）、`memory_structures/spatial_memory.py`、`maze.py`/`path_finder.py` | 小镇的物理沙盘对小说无意义。角色"计划"要从小时级日程改成场景级意图（本场景目标/策略/底线），这部分要从零设计 |
| 认知主循环 | `persona.py`（`move`: perceive→retrieve→plan→reflect→execute 每 tick 跑一遍） | 模拟器节奏（约每 10 秒游戏时间一步）不适用叙事节奏。角色认知应由场景事件驱动，且 reflect 触发（重要性累计）对小说节奏太频繁，需重新标定 |
| 提示词层 | `persona/prompt_template/gpt_structure.py` + `run_gpt_prompt.py` | GPT-3.5 时代单发补全 + 静默 fail_safe（失败返回 "..." 继续跑）。fail_safe 掩盖错误在研究里可接受，在创作管线里是灾难——必须换现代工具调用 + 显式失败 |
| 持久化 | `associative_memory.py`（`save`/`load`） | 全量 JSON dump、embedding 集中一个 dict、检索 O(N) 全扫。25 个 agent × 数天没问题；一部小说几十个具名角色 × 数百章事件量会钝化。至少要加事件时间线索引 |
| 对话终止与窗口 | `converse.py`（硬编码 8 轮上限、last 4 句窗口、chatting_with_buffer=800） | 闲聊级参数。戏剧对话需要：场景目标注入（谁想要什么）、压力升级机制、终止条件语义化（目标达成/破裂/僵持），8 轮窗口对一场摊牌戏太窄 |

### 问题 4：最小可行原型长什么样？

**验证目标只有一个：防火墙能否降低提前泄底率——且要能把"防火墙的贡献"与"多 agent 分工本身的贡献"分离。**

```
配置：2 个角色 agent（甲持秘密，乙持错误信念）+ 1 事件 agent（持暗账：3 条伏笔，
     计划在第 3/5/7 章回收）+ 1 叙述者 + 1 读者模拟器
规模：8 个短章（每章 500-800 字），一个固定对手戏场景，无卷弧、无 TUI、无修订流

三臂对照（关键设计，两臂无法归因）：
  A 臂：单体基线——一个 agent 拿全部信息连写 8 章（模拟现状）
  B 臂：分工无防火墙——事件/叙述者/角色分开，但叙述者可见全量暗账
  C 臂：分工+防火墙——叙述者只见"本章可埋钩子"投影

度量（两条独立证据线）：
  1. 读者模拟器：每章结束后只读正文，回答"你预测接下来会发生什么"；
     泄漏 = 在回收章之前预测命中暗账 payoff。可再加"你此刻怀疑什么"测暗示强度
  2. 金丝雀测试（非 LLM、确定性）：暗账每条伏笔植入随机生成的不常见标记词
     （如"蓝鬃""七弦琴"），grep 正文中标记词在非回收章的出现。金丝雀出现 = 硬泄漏
  3. 反向指标：钩子执行率（事件 agent 验证计划钩子是否真的埋进了正文）——
     防火墙不能以"钩子埋不进去"为代价

判定：C 臂泄漏率显著低于 A、B 两臂，且钩子执行率不显著低于 B → 假设成立
     C ≈ B → 泄底不是信息问题，是行为问题（问题 5 的假设被证实）→ 转向行为约束路线
     B ≈ A → 多 agent 分工本身无用 → 驳回立项
```

可复用零件（按问题 3 的清单）：路由用 router.go 的模式（10 行状态机足够）、伏笔状态机直接搬、角色记忆流 + new_retrieve 移植、对手戏用 agent_chat_v2 骨架。**不要**在原型里做：卷弧结构、上下文压缩、修订投影——都是长篇问题，不是本假设的问题。

[待验证] 三臂判定的统计功效：8 章 × 3 伏笔的样本量偏小，单次运行噪声大；建议同配置跑 3-5 次取中位数，或把章数加到 12 章、伏笔加到 5 条。

### 问题 5：最可能错的一个假设

**"病根是所有信息在同一上下文里，没有信息隐私"——我认为更可能的病根是模型的行为倾向，不是信息可见性。**

论证：

1. 泄底的机理候选有两个：(a) Writer 看到了伏笔全貌所以忍不住呼应（信息说）；(b) 经过 RLHF 的模型有强烈的"张力闭合"倾向——给它任何未解决要素，它都倾向于提前给读者交代，因为"呼应前文"在训练分布里是被奖励的连贯性（行为说）。两个假说对防火墙的预言不同：信息说预言防火墙有效；行为说预言**Writer 会在看不见暗账的情况下自发放暗示**（自己发明伏笔并自己提前回收，或者对事件 agent 埋的钩子过度渲染）。
2. 间接证据：ainovel-cli 明明已经在做信息分层（Writer 看不到全书大纲、看不到未来弧计划，`novel_context_test.go:294` 明确断言"chapter context must not include the whole outline"），README 仍然把"伏笔忍不住提前暗示"列为要对抗的问题 [待验证：需查 ainovel-cli 实际产出文本的泄底率，我没有运行它，此为推断]。如果只看未来大纲就能导致泄底，ainovel-cli 的 Writer 不该有这个问题——但它可见的活跃伏笔账本本身就是作者视角信息，说明这个库的选择是"用泄漏换一致性"。
3. 可证伪条件：问题 4 的三臂实验直接检验。若 C 臂（防火墙）泄漏率与 B 臂（无防火墙分工）无显著差异，信息说被证伪。若 A 臂单体也不泄漏（选材不敏感），说明泄底本来就是题材/提示词问题，整个立项前提动摇。
4. 连带风险：读者模拟器与 Writer 若同源（同模型家族），泄漏检测器与泄漏者共享盲区——它闻不到自己会犯的错。原型中读者模拟器应换不同家族的模型，或至少用"无类型文学素养"的朴素读者 persona。

---

## 三、额外发现的问题

1. **伏笔归属反转是全项目最大的隐性改造量。** 现有两个库的哲学都是"执行者拥有事实写入权"（ainovel 的 Writer 自己报 foreshadow_updates；generative_agents 的角色自己往记忆流写节点）。Story Forge 要改成"持密者拥有、执行者申报"。这不是改几个文件，是改数据流方向：`commit_chapter` 的事实 schema 要按所有权拆分——叙述者申报发生了什么（时间线/关系/状态），事件 agent 申报钩子合规性。台账.md 的"待决问题 2"（角色私有认知与全局 Store 如何共存）的答案应当是：**没有全局 Store，只有投影集合**——每个 agent 看到的"世界"都是事件 agent 维护的真相的某个投影，ainovel 式单一 Store 是反模式。
2. **`next_chapter_outline` 的教训值得写进设计原则。** ainovel-cli 把下一章大纲给 Writer 是深思熟虑的功能（帮它设计章末钩子），但在 Story Forge 的语义下这是泄漏。这说明"给多少未来"是连续谱不是开关，防火墙的粒度要细到字段级：下一章的"情绪走向"可以给，"核心事件"不能给。设计投影时按字段逐一裁定，不要按文件。
3. **generative_agents 的反思机制是错误信念的发动机，但也是错误信念的坟墓。** 角色只能反思自己感知过的东西——这天然维持信息不对称（优点）；但一旦真相揭示，没有任何机制帮角色"重构"信念体系，旧洞察节点还在记忆流里和新事实竞争检索位。小说需要"信念翻转"场景（震惊、否认、崩溃、接受），这要求对旧 thought 节点做 poignancy 重标或抑制——两个库都没有这个机制，属于全新设计点。
4. **成本护栏要从第一天就有。** 问题 1 的 5-10× 成本估计意味着一次 8 章原型实验可能烧掉相当于单 agent 写 80 章的 token。ainovel-cli 的 `host/budget.go`（BudgetSentinel，预算止损优先于一切推进）值得在原型第一周就搬过去，哪怕只做硬上限。
5. **eval 基建可以直接抄思路。** ainovel-cli 有完整的 `internal/eval/`（case/runner/grade/report 分层），三臂实验的运行器和报告器照这个骨架搭，省一周工作。
6. **技术栈建议：Python。** 理由不是语言偏好：防火墙原型的核心复杂度在 LLM 调用编排和 embedding 检索（generative_agents 是 Python，可直接移植 retrieve/reflect/memory 三件套）；ainovel-cli 借的是**模式**（router/saga/状态机），模式跨语言迁移成本≈重写一遍的 1/3，而算法代码原样移植成本≈0。Go 的价值（类型安全、并发）在 8 章原型里用不上。[待验证：若月华团队有强 Go 偏好，反例是 ainovel-cli 的 agentcore 依赖链，复用其 subagent.Runner 可能比移植更快]

---

## 四、置信度自评

| 结论 | 置信度 | 依据 |
|---|---|---|
| 模块级分析（问题 3 的借鉴/改造清单） | **高（0.9）** | 全部基于源码逐文件阅读，关键断言（novel_context 无调用方概念、伏笔账本无未来字段、agent_chat_v2 无跨记忆泄漏、next_chapter_outline 存在）均有具体行号支撑 |
| 瓶颈排序（一致性仲裁第一） | 中高（0.7） | 逻辑推演自代码结构，但未经运行验证；协调成本的乐观估计建立在照抄 router 模式的前提上 |
| 三臂实验设计必要性 | 高（0.85） | 归因逻辑是实验设计问题，不依赖领域假设 |
| "最可能错的假设是行为说而非信息说" | **中（0.55）** | 这是我方直觉 + 间接证据的推测，恰恰是需要 MVP 回答的问题；给出 0.55 是为了表明它值得赌一个项目去验证，而不是我已经信了它 |
| 成本 5-10× 估计 | 中低（0.5） | 从 agent_chat_v2 调用链推算，未实测；对话轮数、检索频率的实际分布可能显著不同 |
| 技术栈选 Python | 中（0.6） | 移植成本论证较硬，但团队因素未知 |

**一句话总评**：这个项目最值钱的资产不是架构图，而是"防火墙规则按字段粒度裁定 + 金丝雀泄漏测试"这两件方法论——即使防火墙假设最终被证伪，它们也会以"最小披露写作"的形式活在任何多 agent 写作系统里。
