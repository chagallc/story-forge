# WebGUI 工单 · 写作工作台 Web 界面（v1）

> 验收合同由 Hana 提供。执行方：ZCode。本工单是唯一验收标准，执行方不得自行修改。
> 基线：main（M2 + 多书并行 + books 命令）。与 M3A worktree（story-forge-m3a）正交，等它合入 main 后加地图链接即可，本工单不做图谱页。

## 目标

给现有 CLI 工作台（workbench.py）配一个本地 Web 界面：浏览器里管理多书、编辑人物卡、跑章节讨论、落笔与提交。**单用户、仅本机、零第三方依赖。**

## 技术栈（定死，不得更换）

- 后端：Python 标准库 `http.server`（ThreadingHTTPServer）+ `json`——复用 workbench.py / src/harness 的现有函数
- 前端：单文件 HTML + vanilla JS + 内联 CSS（无构建、无框架、无 CDN 依赖——完全离线可用）
- 监听：`127.0.0.1:17890`（仅回环地址，禁止 0.0.0.0）
- 启动：`python workbench-web.py`（新文件，不动 workbench.py 的 CLI 入口）

## 架构要求

1. **逻辑层复用**：workbench.py 的核心逻辑（load_bible/save_bible/client_for/load_card/validate_card/bible_to_spec/前文组装/lock/write/commit 的流程）抽成可调用函数供 CLI 与 Web 共用。允许小规模重构（把命令函数拆出 `_core` 函数），但 CLI 行为零变化（smoke 必须继续通过）
2. **LLM 调用非流式**（v1）：讨论/落笔期间前端显示 loading 态；后端单线程处理同一 workspace 的请求（workspace 级锁复用 write-lock 机制），不同 workspace 可并发
3. **写操作确认**：write / lock / commit 在前端有二次确认弹窗；commit 额外显示将推进的 state ops 清单
4. **安全**：不做鉴权（仅回环）；所有写操作走后端函数（前端不直接碰文件）；路径参数不得越出 workspaces/（防路径穿越）

## 页面结构（五屏）

### 屏 1 · 书架（`/`）
- 所有 workspace 的卡片列表（复用 books 逻辑）：书名/标题/语言/模型/已写/已锁/规划进度条/活跃写锁
- 「新建书」表单：书名/标题/类型/语言（zh|en）/平台/logline/世界观/弧线模板/规划章数
- 点卡片进入屏 2

### 屏 2 · 书工作台（`/book/<name>`）
三栏布局（参照 AI_NovelGenerator：左规划树/中主区/右面板）：
- 左栏：章节列表（状态标记 ◦branching/◇discussed/◆locked/▨drafted/★committed）+ 人物列表 + 「+ 新人物」「+ 讨论新章」「plan 滚动展开」（若已实现）按钮
- 中栏：当前选中章节的详情/讨论面板/正文查看
- 右栏：人物卡详情 + 动机栈可视化（七字段 + 声口卡）+ 动态状态（state 里的 knowledge/location/inventory）

### 屏 3 · 人物卡编辑（`/book/<name>/char/<id>`）
- 表单分区（对应四分区）：恒定区（name/card/anchors/mes_example 多行文本）/ 动机区（want/need/wound/value/fear/contradiction）/ 声口卡（catchphrases 逗号分隔/speech_habits/forbidden/sample_line）/ 知识规则（learn 条目表：fact_id+when；never_learn 列表；lorebook 条目表：fact_id+keywords+content_ref）
- 保存调后端校验（id 唯一、必填 name）

### 屏 4 · 章节讨论与锁定（`/book/<name>/chapter/<n>`）
- 讨论面板（chat 样式）：阶段一显示 3 条候选分支卡片（summary/beats/choice/motive_cost/reader_payoff/risks），每张卡「选择此方向」按钮；阶段二 chat 式多轮（作者输入 → AI 编剧回复），输入框 + 「锁定章节卡」按钮
- 锁定流程：后端生成章节卡 → 显示卡片全字段表单（**作者可逐项修改**）→ 确认后落盘 card.json
- 「落笔」按钮（二次确认）→ loading → 完成后显示 drafts 列表与最新稿正文（只读查看 + lint 结果 + 遗漏警告如有）
- 「提交正史」按钮（二次确认 + 显示 ops 清单）→ commit → 状态变 committed

### 屏 5 · 正史阅读（`/book/<name>/canon`）
- 已提交章节连续阅读视图（canon.md 拼接，按章分节标题）
- 每章显示状态徽标与「查看 drafts 历史」链接

## API 端点（建议，可微调）

```
GET  /api/books                     多书列表（books 逻辑）
POST /api/books                     建书
GET  /api/book/<name>               bible 摘要（章节状态/人物列表/compass）
GET  /api/book/<name>/char/<id>     人物卡全量
POST /api/book/<name>/char          新建/保存人物卡
GET  /api/book/<name>/chapter/<n>   章节元数据 + card + drafts 列表 + canon 正文
POST /api/book/<name>/discuss/<n>   {message} → AI 编剧回复（含分支生成阶段）
POST /api/book/<name>/lock/<n>      {card} → 校验 + 落盘（返回违规清单或成功）
POST /api/book/<name>/write/<n>     落笔（复用 write 锁机制）
POST /api/book/<name>/commit/<n>    {confirmed: true, revised_path?} → 提交正史
POST /api/book/<name>/exempt/<n>    {rule, reason}
GET  /api/book/<name>/canon         正史全文
```

错误约定：非 200 时 body 为 `{"error": "..."}`，前端 toast 显示。

## 验收标准（全部满足才算完成）

1. **CLI 零回归**：`python tools/workbench-smoke.py` 通过（重构后 CLI 行为零变化）
2. **API 层测试**：新增 `tools/webgui-smoke.py`（urllib 直打 API）：建书 → 建人物 → 拿章节列表 → 锁卡（含坏卡被拒返回违规清单）→ write（mock 或真实）→ commit → canon 读取，全链路断言；含路径穿越攻击样本（`name=../main` 被拒）
3. **前端功能冒烟**：五个屏全部可达、表单可提交、讨论面板可对话（真实 LLM 一轮）、lock 显示卡片表单、write loading 后显示 drafts、commit 二次确认后状态变 committed——手动浏览器验收（Hana 或月华执行，附截图）
4. **安全**：仅监听 127.0.0.1；路径穿越样本被拒；前端不存任何 key
5. **并发**：同章 write 请求二连发，第二个被锁拒绝（复用 write-lock）
6. `git status` 干净，提交在 WebGUI 分支，附 WEBGUI-CHANGES.md（含「工单未写明的决策」节）

## 提示

- workbench.py 的 `client_for/load_card/validate_card/build_context/StoryState` 等直接 import 复用；命令函数里的 `input()` 交互逻辑不要复用（那是 CLI 专属），Web 层按 API 语义重新编排
- 讨论面板的后端实现可参考 cmd_discuss 的 msgs 组装（system + 书况摘要 + turns 追加），把 REPL 的 input() 换成 HTTP 请求体
- 前端体验底线：不用alert() 做错误提示（用 toast/行内）；按钮 loading 态；中文 UI
- Cytoscape/图谱页不在本工单（M3A 合入后 v1.1 加链接跳 map.html）
