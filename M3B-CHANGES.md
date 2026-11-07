# M3B-CHANGES · 世界设定系统 + 时代素材收集（M3B-G 工单）

> 执行：ZCode · 分支 `hana/m3b-g`（新 worktree story-forge-m3b，基于 main a639327）· 验收合同：docs/plans/M3B-G-workorder.md（未改动）
> 硬边界：零第三方依赖；engine.py / Ledger / state.py 零改动；不 merge / 不 push / 不动 main。

## 改了什么

### 1. bible.world 升级 + schema v4→v5（兼容旧 bible）

- `SCHEMA_VERSION = 5`；新增 `_migrate_to_v5`：**只补空字段**（`time_period`/`era_materials`/`locations`/`rules`），旧 `setting`/`glossary` 原样保留；迁移链 v1→v2→v3→v4→v5 幂等（M1 格式副本实测 v2→v5 一路通过）
- `_ensure_defaults` 保存前防御性补 world 字段（任何保存路径都不会再产出缺字段的 world）
- `create_book_core` 新书 world 直接带全六字段

### 2. 时代素材 CRUD（workbench.py `_core`，CLI/Web 共用）

- `save_material_core`（id 缺省自动 `mat_NNN`；同 id 整体更新；content 必填）/ `remove_material_core` / `save_location_core` + `remove_location_core`（`loc_NNN`）/ `normalize_material`
- `normalize_material`：category 不在 8 项枚举 → 归「其他」且**原词并入 keywords**（保守不外溢）；`chapter_range` 支持 `null`/`"3-6"`/`[3,6]`/`[4,null]`
- 所有写操作 `Refused` 语义与既有 `_core` 一致（CLI 退出码 1 / Web 409+清单）

### 3. 相关性选择 + prompt 注入（核心，验收 #4）

- `select_era_materials(bible, context_text, ch, limit=10)`：① `chapter_range` 不覆盖本章的直接排除；② 素材 `keywords` 与上下文语料子串匹配计分，命中者按分取前 limit 条；③ **无任何命中时回退「全量前 N 条」**（保持确定性顺序，控 token）——工单规则逐条落地
- 上下文语料 `_era_context_text`：章节卡文本字段（time_place/objective/obstacle/choice/ending/…）+ engine 四元组 + pressure force/cost + world.setting/time_period
- `era_injection` 输出工单样例格式：
  ```
  【时代素材（本章可用的真实细节）】
  - [历史事件] 1998年长江全流域特大洪水……
  ```
- **注入点 A（落笔）**：`write_prepare` 在 msgs 组装后（投影开/关两分支汇合处）把块追加到 user prompt **尾部**；job 带出 `era_used`（命中素材 id 清单）→ Web `report.json` 增 `era_materials_used`
- **注入点 B（章节讨论）**：`_discussion_opener` 的 system 追加摘要（≤8 条，标注「不必全用」）——CLI REPL 与 Web 会话共用同一函数，自动双端生效
- **注入点 C（人物共创）**：`codiscuss.codiscuss_messages` system 追加（≤8 条；brief/设定/人物卡为相关性语料；注入失败不阻塞共创）
- 已有素材（≤30 条 id+关键词+摘要）写进 propose prompt 的「不要重复」区

### 4. AI 素材提议（核心，验收 #2）

- `propose_materials_core(book, bible, topic, count)`：**reader 通道**（`client_for(bible, "reader", book)`，与 writer 异构，同 audit/抽取通道约定）；prompt 硬性要求「可直接写进正文的具体细节」，**内嵌工单正例/反例**；topic 必填；候选**不落盘**（source 留空，`chapter_range` 置 null），作者逐条确认后走 `save_material_core(source="AI提议已确认")` 批量写入
- LLM 失败抛异常 → Web dispatch 统一转 502（前端 toast 可重试），**不阻塞**编辑页其它操作（工单技术约束）

### 5. Web：世界设定页 + 七端点

- 端点（均在 workspace 互斥锁内；路径参数走既有 `safe_book`/`safe_segment` 白名单）：
  ```
  GET  /api/book/<name>/world                world 全量
  POST /api/book/<name>/world/meta           {time_period?, setting?}
  POST /api/book/<name>/world/material       {entry} 新增/更新
  POST /api/book/<name>/world/material/remove {id}
  POST /api/book/<name>/world/propose        {topic, count} → 候选（不落盘）
  POST /api/book/<name>/world/confirm        {materials:[...]} 批量确认（source=AI提议已确认）
  POST /api/book/<name>/world/location(/remove)  地点 CRUD
  ```
- 前端 `#/book/<name>/world`（屏 6）：时代/设定行内编辑；左栏分类过滤 + 素材列表 + 地点列表；右侧条目编辑表单（分类下拉/关键词/内容/章节范围/来源只读）；「＋ 添加素材」「✎ AI 提议素材」——propose 弹窗按条勾选采纳、**逐条可改分类/关键词/内容**后批量确认；全程 toast/行内错误，无 alert
- 书工作台顶栏新增「🌍 世界设定」入口

### 6. CLI world 命令（工单功能 1）

```
python workbench.py world <书名> list                    # 时代/素材（id/分类/关键词/范围/来源）/地点
python workbench.py world <书名> add                     # 交互式：分类→关键词→内容→章节范围→来源
python workbench.py world <书名> remove <id>
python workbench.py world <书名> set <time_period|setting> <值>
```

### 7. 顺手修复的 main 遗留问题（合并遗留，非本工单引入但阻塞验收）

1. **`write_chapter_core` 引用未定义 `bible`（NameError）**：4cf4ff7 挂 audit 时写成 `run_audit(book, bible, ch, text) if bible is not None else None`——CLI/Web 共用核心每次落笔必崩。基线实测：main 上 `tools/workbench-smoke.py` 在段 2 第一次离线 `cmd_write` 即崩溃退出码 1。修复为 `run_audit(book, job["bible"], ch, text)`（audit 现在真正挂上 write，失败仍不阻塞）
2. **合并遗留重复定义**：`REVISE_PROMPT` / `audit_summary` / `run_fact_extraction` 各有两份（内容相同，后者覆盖前者），删去第二份；docstring 重复的 `books` 行删去
3. **webgui.html 合并残留**：`btn-gonewchar` 被链式赋值串到 codiscuss 导航（「＋ 新人物」点开的是共创板）、codiscuss 路由/handler 重复行——修正（新人物 → char/new；工作台顶栏四按钮 + 新增 🌍 各归各位）
4. **codiscuss.py 缺 `import re`**（`extract_characters_from_discussion` 里 `re.search` 必 NameError）——补上
5. smoke 适配说明：离线 FakeClient 回复按位消费，audit 现在会真实消耗一次调用——段 2/5/8/9 的离线写把 `wb.run_audit` 打点为 no-op（与 `client_for` 同法存/还原），并**新增 audit 正样本段**（第 3 次 LLM 回复为审核 JSON → 断言 `write_chapter_core` 返回 `audit.issues` 被解析）

## smoke 适配与新增断言

### tools/workbench-smoke.py（93 项 → 120 项，实跑 120/120 退出码 0）

- 段 1：schema 断言 v4→v5 + world 六字段默认齐全
- 段 2：种子 3 条素材（命中用/回退对照/range 排除对照），投影**开/关**各自断言「时代素材块注入 prompt 尾部 + 命中项在 + 有命中时不回退全量 + range 不覆盖不注入」（验收 #4 双模式）
- 段 4/5：迁移断言 v2→v5 / v1→v5（world 字段补齐 + 原 setting 保留）
- 新段 13（离线，零 LLM）：v4→v5 迁移单元 + 幂等；CRUD（新增/空 content 拒/同 id 更新/删除/删不存在拒/range 两种解析）；`select_era_materials`（命中按分/无命中回退/range 排除/空素材）；注入块格式；讨论 system 注入；共创 system 注入；propose 规范化（空 content 丢/枚举外归一/候选不落盘/空 topic 拒）；CLI `world list/add/remove/set` 全子命令；audit 正样本
- 说明：项数 93→120 中含基线各段的条件检查项随 LLM 输出浮动（±1~2），以 FAIL=0 与退出码 0 为准

### tools/webgui-smoke.py（57 项 → 71 项，实跑 71/71 退出码 0）

- 新段 11（世界设定端点）：meta 更新 / GET world / material 新增（id 自动）→ **验收 #3：GET /book 可见 era_materials** → 同 id 更新 → 删除 → 重复删 409 / propose 空 topic 409
- 新段 12（验收 #2）：建 `theflood-smoke`（《大水将至》同参数书：genre/time_period=1998年夏，武汉/logline）→ `POST /world/propose {topic:"1998年武汉夏天 中学生的日常生活", count:10}` → 断言 **≥8 条候选**、每条 content ≥15 字且有分类有关键词（非泛化的粗筛）；样例打印进 smoke 输出；confirm 前 2 条 → `source=AI提议已确认` 落 bible
- **测试基建修复**：服务进程 stdout/stderr 引到 PIPE 后无人消费——save_bible 的 `saved:` 行 + 每请求访问日志把管道缓冲塞满后**服务端 print 阻塞、后续请求全部挂死**（实测卡在重复删除 409 前超时 900s）。加常驻排水线程（保留尾部 500 行供诊断）
- never_learn flaky 防护提前覆盖 commit 预览步骤（本轮 LLM 的 delta 在预览即被拒）

## 验收对照

| 工单条目 | 结果 |
|---|---|
| #1 smoke 适配后通过 | **workbench-smoke 120/120、webgui-smoke 71/71，均退出码 0**（基线 main 本身在段 2 崩溃，已随本单修复） |
| #2 propose 用《大水将至》测试 ≥8 条具体素材 | theflood-smoke 自动断言通过（10 条）；**Hana 真实 `theflood` 工作区副本实测 10/10 条具体素材**（见下文全量摘录，v4→v5 迁移真实触发） |
| #3 era_materials 写入后 GET /book 可见 | webgui-smoke 断言通过 |
| #4 write 投影 prompt 含 era_materials 摘要（投影开/关均有效） | workbench-smoke 段 2 双模式断言（FakeClient 捕获 messages 含注入块） |
| #5 旧 bible 兼容 | v4 手写样本迁移单元断言 + M1 格式副本（v2 起步）全链迁移 v2→v5 实测 + 真实 theflood（v4）迁移实测 |
| #6 git status 干净 + CHANGES | 本文件；真实 theflood 副本测试后已删除，工作树干净 |

## 《大水将至》propose 实测记录（验收 #2）

对 Hana 真实 theflood 工作区副本（只读复制，未触碰原件）实测，reader 通道 qwen3.8-flash，
topic=`1998年武汉夏天 中学生的日常生活`，count=10 → **10 条全部具体可入正文**（候选取样）：

1. [生活细节] 校服/运动服/涤纶 —— 蓝白涤纶校服贴背汗渍、领口搓洗起毛边
2. [物品道具] 风扇/吊扇/教室 —— 铁叶吊扇吱呀作响、叶片积黑灰、风带霉味
3. [流行文化] 磁带/随身听/周杰伦 —— 索尼 Walkman + 盗版《范特西》磁带绞带用铅笔卷
4. [地理环境] 长江/轮渡/汽笛 —— 汉口江滩「汉客」号轮渡汽笛、防汛墙水腥气
5. [生活细节] 冰棒/小卖部/五分钱 —— 巷口「美怡乐」紫雪糕、包装纸汗浸软烂
6. [物品道具] 摄像机/录像带/电池 —— 松下 NV-M7 手持机 + VHS-C 带、取景器雪花点（**与 logline 的"父亲从香港带回的摄像机"直接咬合**）
7. [历史事件] 洪水/新闻/电视 —— 21 寸长虹彩电《新闻联播》九江决口报道混窗外蝉鸣
8. [生活细节] 自行车/链条/油渍 —— 二八大杠后座弹簧断、裤脚蹭链条油印
9. [人物背景素材] 补习班/奥数/家长 —— 陆洁少年宫奥数集训、《奥林匹克数学竞赛教程》翻烂（**人物卡咬合**）
10. [其他] 蚊子/蚊香/夜晚 —— 停电夜「雷达」牌蚊香蓝烟

候选未落盘（era_materials=0），等作者逐条确认。**质量备注（如实）**：第 3 条《范特西》2001 年 9 月发行，
放进 1998 年是时代错位（应换《心太软》/《对面的女孩看过来》级别的 97-98 热曲）——这正是「AI 只提议、
作者逐条确认」环节存在的意义，propose prompt 已要求「拿不准的宁可不写」但 LLM 仍会偶发史实漂移，
建议确认环节顺手核对年表。另：theflood-smoke（自动化用书）同测试当轮 10 条样例：盐水冰柜白砂糖贵五毛、
《心太软》盗版磁带、汉口江滩防汛沙袋、竹床乘凉、热干面涨到一块五（质量同样在线，见 webgui-smoke 输出）。

## 工单未写明的决策

1. **章卡无 keywords 字段的匹配实现**：工单写「按本章 card.keywords（或 arc_label）匹配」——现行章节卡 schema 没有 keywords 字段。实现为把卡片全部文本字段（objective/obstacle/time_place/engine 四元组/pressure force 等）拼成语料做关键词子串匹配，等价于「语义上的卡级关键词」；arc_label 已含在语料里。
2. **有命中时不回退**：工单只说「无匹配时全量前 10 条」；实现为只要有命中就只注命中项（避免无关素材稀释），无命中才回退全量前 N。
3. **讨论注入进 system、落笔注入进 user prompt 尾部**：工单功能 4 明说 system 追加（讨论），功能 3 说「注入 prompt 尾部」（落笔）——按各自字面落位。
4. **propose 通道**：用 reader 通道（工单明说「异构」）；`bible.book.reader_model` 覆盖继续生效。
5. **confirm 端点**：工单 API 表只列了 propose；「确认后批量写入」需要落盘入口，新增 `/world/confirm`（source 固定「AI提议已确认」）。人工单条编辑走 `/world/material`（source 默认「手动添加」由前端填）。
6. **枚举外 category**：工单说枚举「可扩展」；实现为存层归一「其他」+原词并入 keywords（不外溢枚举），编辑表单用下拉；后续要放开可只改 `normalize_material`。
7. **rules[] 本单只读**：数据结构保留（迁移补空数组、GET 可见），无 CRUD 入口——工单功能清单未提；locations 做了最小 CRUD（页面上已有列表位）。
8. **CLI world `set` 子命令**：工单 CLI 只列 list/add/remove；time_period/setting 的 CLI 编辑入口补为 `world set <key> <值>`（Web 页有，CLI 侧对称）。
9. **注入条数**：落笔 10 条、讨论/共创 8 条（工单「5-10 条」区间内取值）；每条 content 截 200 字符防超长。
10. **main 遗留修复清单**（见「顺手修复」节）：NameError/重复定义/串线按钮/缺 import 均为合并遗留且阻塞本单验收（smoke 必须通过），修复并在 smoke 中固化（audit 正样本段）。
11. **theflood 副本测试不入库**：Hana 的 `workspaces/theflood` 是 main 里未跟踪的 WIP；质量实测用副本（只读复制 + 设置 time_period），测完删除，不提交她的创作数据。自动化回归用 `theflood-smoke`（同参数生成）。
12. **propose 失败语义**：LLM 网络失败（RuntimeError）与输出非 JSON（ValueError）统一映射 502 + 「可重试」文案；topic 缺失 409。前端在弹窗内 toast + 保留输入，不打断管理页其它操作。
13. **webgui-smoke 服务进程 stdout 排水线程**：服务端每请求/每次 save_bible 都写 stdout（stderr 合流），PIPE 无人消费时缓冲塞满 → 服务端 print 阻塞 → 全部后续请求挂死（本轮实测复现）。smoke 加常驻排水线程（保尾部 500 行）；交互使用（终端直跑）不受影响。
