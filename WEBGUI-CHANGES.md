# WEBGUI-CHANGES · 写作工作台本地 Web 界面（v1）

> 执行：ZCode · 分支 `hana/webgui`（WebGUI worktree）· 验收合同：docs/plans/WebGUI-workorder.md（未改动）
> 基线：main（M2 + 多书并行 + books 命令）。与 M3A 正交，本单不做图谱页。不 merge / 不 push / 不动 main。
> 技术栈（定死）：Python `http.server`（ThreadingHTTPServer）+ 单文件 vanilla JS（零第三方依赖、零构建、完全离线）；默认仅监听 `127.0.0.1:17890`。

## 改了什么

### 新增 `workbench-web.py`（后端，约 500 行）

- **路由**：`GET /`（服务 webgui.html）+ `/api/*`；其余一律 404。错误约定：非 2xx 时 body 为
  `{"error": "...", "detail": [违规清单（可选）]}`，前端 toast/行内展示
- **路径安全（三层）**：
  1. 段级校验：`safe_book`（白名单正则 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` + Windows 保留设备名
     con/prn/aux/nul/com¹⁻⁹/lpt¹⁻⁹ 拒绝 + 目录必须存在）、`safe_char_id`（`char_\d+`）、
     `safe_chapter`（1~999 整数）、`safe_segment`（拒绝空段/`.`/`..`/unquote 后内嵌 `/` `\` `\0`）
  2. 越界一律 400（不尝试任何文件访问）；不存在的书 404
  3. 所有文件定位仍走 workbench.py 既有的 `ws_dir/card_file/…` 组合（book 名已过白名单，拼不出
     workspaces/ 外路径）；穿越样本实测 `../main`、`%2e%2e/main`、`..%5Cmain`、char/章号段带
     `..%2f`、body 注入 `"name": "../evil"`、保留名 `con` 全部被拒（见 tools/webgui-smoke.py 第 2 节）
- **workspace 级互斥**：进程内 per-book `threading.Lock`（`WS_LOCKS`），同一本书的 POST 操作
  串行、不同书可并发（ThreadingHTTPServer + daemon threads）
- **write 三段式**（唯一在 LLM 调用期间放互斥的端点）：
  `write_prepare`（互斥内：门禁 + 取 `.write-lock-chNN` 文件锁 + 组装上下文）→
  `write_prose`（互斥外：正文 LLM）→ `write_finalize_draft`（互斥内：lint + 落草稿 + 释放文件锁）→
  `write_delta_core`（互斥外 LLM + 互斥内落盘）。同章二连发时第二发在 prepare 阶段撞文件锁 → **423**；
  不同章并发写串行进互斥区，bible 无丢失更新（finalize 前重读 bible）
- **错误→状态码**：路径/参数非法 400；资源不存在 404；重名建书 409；门禁/校验/写锁拒绝 409
  （写锁占用单独映射 **423 LOCKED**）；章节卡生成三连败 422；LLM 调用失败 502；未预期异常 500（不带栈）
- `GET /api/book/<name>` 输出工作台所需全量：书摘要 + 每章状态/卡/分支/讨论 turns/drafts 三件套
  清单 + canon + 人物完整卡（动机栈/声口/知识规则）+ state 动态状态（knowledge/location/inventory）
- 写报告 `drafts/vNNN.report.json`（Web 层新增，CLI 不产）：lint 汇报 / 丢弃 op / never_learn
  警告 / kept ops——草稿历史里可回看「遗漏警告」
- `--port N` 端口覆盖（仅 webgui-smoke 隔离用；默认恒为 17890）

### 新增 `webgui.html`（前端，单文件 ~1200 行，hash 路由五屏）

1. **书架 `#/`**：所有 workspace 卡片（书名/标题/语言/模型/已写+已锁双进度条/活跃写锁徽标）+
   「新建书」表单模态（全部 workorder 字段）；点卡片进工作台
2. **书工作台 `#/book/<name>`**：三栏（AI_NovelGenerator 式）——左：章节列表（
   ◦branching/◇discussed/◆locked/▨drafted/★committed 状态标记 + 人物列表 +「＋新人物」「＋讨论新章」
   按钮）；中：选中章节详情（章节卡摘要/草稿三件套/遗漏与丢弃警告/最新稿只读查看）或全书概览
   （compass/弧线/暗账/state）；右：人物卡详情（七字段动机栈 + 锚点 + 声口卡 + state 动态状态）
   。中栏内联「落笔」（确认→loading→刷新）与「提交正史」（ops 预览模态→确认）
3. **人物卡编辑 `#/book/<name>/char/<id>`**（`new` 为新建）：四分区表单——恒定区（name/card/
   anchors 逗号分隔/mes_example 多行）；动机区（want/need/wound/value/fear/contradiction）；
   声口卡（catchphrases/speech_habits/forbidden 逗号分隔 + sample_line）；知识规则（learn 条目表
   fact_id+when 可增删行、never_learn、lorebook 条目表 fact_id+keywords+content_ref 可增删行）。
   保存走后端校验（name 必填 / id 格式 / id 存在性），违规行内展示
4. **章节讨论与锁定 `#/book/<name>/chapter/<n>`**：阶段一 3 条分支卡片（summary/beats/choice/
   motive_cost/reader_payoff/risks + 选择此方向 + 重新生成）；阶段二 chat 式多轮（作者/编剧气泡、
   回车发送、编剧思考中占位）；「锁定章节卡」→ 确认弹窗 → 后端生成 → **全字段确认表单模态**
   （骨架/选择与承诺/边界与预算/引擎 四组，逐项可改，pressure 用 `char | motive | force | cost`
   行编辑）→ 确认落盘 card.json。锁定后：落笔（二次确认 → loading → drafts 列表 + 最新稿 +
   lint + 遗漏警告）、提交正史（ops 预览 + 二次确认 + recorded_consequence 提炼句展示）
5. **正史阅读 `#/book/<name>/canon`**：已提交章节连续视图（章标题 + 状态徽标 + arc_label +
   「drafts 历史（N）」链接 + 正文衬线排版）

- **体验底线**：全程无 `alert()`（toast + 行内错误 + 自定义模态）；LLM 动作全屏 loading 覆盖层
  （注明非流式可能需几分钟）+ 按钮内联 spinner；中文 UI；所有动态内容经 `esc()` 转义（防 XSS）；
  深浅文学纸主题（CSS 变量），无任何外部资源引用
- 前端不存任何 key（LLM 配置只在服务端 `config/models.local.json`，接口不下发）

### 重构 `workbench.py`（CLI 零变化，抽 `_core` 供 Web 复用）

- 新增 `Refused` 异常（msg + violations）与 `_log_collector`（log 列表或直接 print）
- `create_book_core`（← cmd_new）/ `save_character_core`（← cmd_char add，name 必填、id 自动
  生成或整体更新）/ `ensure_branches` + `select_branch_core` + `_discussion_opener` +
  `archive_discussion`（← cmd_discuss）/ `lock_materials` + `generate_chapter_card_core` +
  `confirm_chapter_card_core`（← cmd_lock）/ `write_gate` + `write_prepare` + `write_prose` +
  `write_finalize_draft` + `write_delta_core` + `write_chapter_core`（← cmd_write）/
  `commit_preview` + `commit_execute`（← cmd_commit）/ `exempt_core`（← cmd_exempt）/
  `books_overview`（← cmd_books）
- cmd_* 函数全部改为薄壳：交互 `input()`/打印序列/退出码逐字保留（含「硬门禁拒绝」「不匹配」
  「跳过 recorded_consequence」「豁免已登记」等 smoke 断言文本）
- `_write_json` 改原子写（tmp + os.replace）：Web 并发 GET 不读半截文件；CLI 输出与产物不变
- 写锁获取改 `os.open(O_CREAT|O_EXCL)` 原子创建：Web 双发场景无 TOCTOU 窗口；新锁拒绝/过期锁
  清除重建语义与旧版逐字一致（消息文本不变）
- `write_delta_core` / `commit_execute` 落盘前重读 bible：Web 层同书并发时无丢失更新（CLI 单进程
  行为不变）
- 讨论会话新文件 `discussions/chNN.session.json`（仅 Web 层写）：CLI REPL 不产生此文件，CLI 产物
  目录布局不变；Web 端无会话文件时可从已归档 `chNN.jsonl` 只读恢复讨论记录

### 新增 `tools/webgui-smoke.py`（验收 #2/#4/#5）

启动真实服务进程（`--port 17891`，默认 17890 留给人工冒烟），urllib/http.client 直打：

1. 启动断言：`/api/books` 可达 + stdout 声明绑定 127.0.0.1 + `GET /` 返回五屏前端单文件且
   **零外部引用**（无 `https?://` 外链 / 无 CDN 关键词）
2. **路径穿越样本**（http.client 原始请求行，绕开 urllib 的客户端归一化，保证服务端真实收到）：
   `../main`、`%2e%2e/main`、`..%5Cmain`、char 段 `..%2f..%2f..`、`../../../workbench.py`、
   书名段内嵌穿越、`..`、盘符路径——全部 400/404 且 body 含 error；建书坏名 body 注入 ×8
   （含 `../evil`、保留名 `con`、空名、80 字符）全 400
3. **全链路（真实 LLM）**：建书 → 重名 409 → 建人物（空名/不存在 id 被拒 → 回读一致 → 更新生效）
   → 章节列表 → 讨论三阶段（start 3 分支 → select 坏 id 409 → select A → chat 真实一轮 →
   空消息/未知动作被拒）→ lock 生成（坏卡确认返回 ≥2 条违规清单且不落盘；讨论归档 jsonl）→
   确认落盘 card.json（pov 归一 id）→ **write 并发二连发**（第一发进写锁区后第二发 423「写入进程」
   ；第一发成功产三件套）→ commit 预览（ops 清单+提炼句）→ 确认（never_learn 冲突自动修 delta
   重跑，同 CLI smoke 的 flaky 防护）→ canon 落盘 + state revision=1 + .bak-0 → 重复 commit 409
   违规清单 → `GET /canon` 第 1 章正文 → 书摘要人物动态状态可见 → exempt 负样本（无 finding 409、
   缺 rule 400）

## 验收对照

| 工单条目 | 结果 |
|---|---|
| #1 CLI 零回归 | `python tools/workbench-smoke.py` 重构前后各跑一次：基线 58/58、重构后 57/57 全过（项数差为 1 项条件检查——「delta learn 已推进 state.knowledge」仅当该轮 LLM 的 delta 恰好含 learn op 才计入，非回归；两次均零 FAIL、退出码 0） |
| #2 API 层测试 | `tools/webgui-smoke.py` 实跑 **57/57 全过**：建书→建人物→章列表→讨论三阶段→锁卡（坏卡拒+违规清单）→write→commit→canon 全链路断言 + 路径穿越样本 ×8 + 建书坏名注入 ×8 全拒 |
| #3 前端功能冒烟 | 执行方已用无头浏览器逐屏核验：五屏可达、书架/工作台/人物卡/章节/正史数据渲染正确（含章节卡摘要、草稿三件套、讨论存档、动态状态）；交互链路（分支选择→chat→锁定表单→落笔→提交）已由 webgui-smoke 以同构 API 请求走通——**按工单要求，带截图的手动浏览器验收仍由 Hana/月华执行确认** |
| #4 安全 | 仅 127.0.0.1 绑定（硬编码，smoke 断言启动声明）；穿越样本被拒；前端零 key 零外链（smoke 断言） |
| #5 并发 | 同章 write 真实二连发实测：第一发进入 LLM 阶段（写锁文件出现）后第二发 **423**「另一个写入进程」；第一发完成后三件套落盘、锁释放 |
| #6 提交 | git 提交在本分支（workspaces/ 冒烟产物随仓库惯例一并入库），git status 干净 |

## 工单未写明的决策

1. **并发双保险的实现口径**：工单同时要求「同一 workspace 单线程」与「同章 write 二连发第二发被
   锁拒绝」——二者叠加解读为：进程内 per-book 互斥覆盖除 write 两段 LLM 调用外的全部区间；
   write 的长 LLM 区间放互斥、由 `.write-lock-chNN` 文件锁兜底同章互斥（跨进程同样有效）。
   这样真实二连发即可复现「第二发被拒」，且不同章节的写不会互相覆盖 bible（落盘前重读）。
2. **423 语义**：写锁占用单独映射 HTTP 423（Locked）而非 409，便于前端与「校验不过」区分展示。
3. **讨论会话文件**：Web 的 chat 式多轮需要跨请求持久化 LLM msgs（CLI REPL 在内存里），
   新增 `discussions/chNN.session.json`；归档 jsonl 仍按 CLI 同一函数产出，CLI 目录布局不受影响。
4. **lock 的 Web 流程拆两步**：`POST lock`（生成，不落盘）→ 作者在确认表单可逐项改 →
   `POST lock {confirm:true, card}`（校验+落盘）。CLI 的 y/N 确认与 Web 的表单确认走同一个
   `confirm_chapter_card_core`。生成时顺手归档讨论（status=discussed），落盘才置 locked。
5. **写报告 vNNN.report.json**：dropped ops / never_learn 警告此前只打印在 CLI stdout，Web 需要
   在 drafts 历史里回看「遗漏警告」，故 Web 层写报告文件（CLI 不产、不读，零影响）。
6. **`_write_json` 原子化**：为 Web 并发 GET 的读取一致性（不读半截 JSON）而做；CLI 输出/产物
   逐字节不变。
7. **Windows 保留设备名拒绝**（con/prn/aux/nul/com1-9/lpt1-9）：探测时发现 `con` 能被白名单
   放行并成功建目录，Windows 上后续读写行为不可靠，故加拒绝；CLI `new` 未加（维持原样，
   CLI 用户手工负责）。
8. **`--port` 覆盖**：默认恒 17890；smoke 用 17891 隔离，避免与人工冒烟实例抢端口。
9. **LLM 失败时的写锁清理**：CLI 语义是异常时锁残留、1 小时自然过期；Web 层收紧为「草稿未落盘
   就释放锁」，避免一次 LLM 失败锁死该章一小时（finalized 后绝不触碰锁文件，防误删并发者的锁）。
10. **CLI discuss regen 路径多打一行**「阶段一：生成 3 条轻量剧情分支 ...」提示（行为不变）；
    `commit --revised` 指向不存在文件时旧版是裸 traceback，现改为干净的 Refused 提示退出码 1。
    两处均不在 smoke 断言路径上。
11. **越界章号（如 /chapter/99）**：按合法整数处理，返回空章状态（只读无副作用），不做 404。
12. **前端单文件拆两份**：`workbench-web.py`（后端）+ `webgui.html`（前端，仍为单文件零构建），
    服务端只从固定路径读取；比把 1200 行 HTML 塞进 Python 字符串更可维护。

## 已知边界（v1 不做）

- 非流式 LLM：讨论/落笔/commit 期间前端全屏 loading，无中途取消
- 无鉴权（仅回环，工单明示）；无 HTTPS；无多用户
- ledger/compass/arc 的编辑仍走 story-bible.json 手工维护（工单未要求 Web 编辑暗账）
- 图谱页不在本单（M3A 合入 main 后 v1.1 加跳转链接）
