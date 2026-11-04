# M1 工单 · 章节卡与多线推演（story-forge 工作台 v2 第一阶段）

> 验收合同由 Hana（Hanako）提供。执行方：ZCode。本工单是唯一验收标准，执行方不得自行修改。
> 蓝图：docs/plans/v2-整合方案.md（朱雀方案 M1 = P0+P1+P5）

## 目标

把工作台的 `lock` 从「生成旧 cell」升级为「生成并确认章节卡 card.json」（cell 原样嵌入 `card.engine`），讨论环节默认产出 3 条轻量剧情分支供作者选择，`write` 加章节卡硬门禁，spec 派生化定型三层文件权威。

## 边界（硬性）

1. **不修改** `src/harness/engine.py` 的细胞语义（四元组/pressure/B 拍）——`card.engine` 直接透传给 `spec.engine.cells`
2. **不碰** `ledger`/`shadows` 结构与 `Ledger` 类
3. **不 merge、不 push、不 rebase main**——所有提交只在 M1 worktree 分支上
4. 兼容旧格式：`bible.chapters[n].cell`（旧 cell）必须继续可读（自动包装为 card.engine）
5. Python 标准库 only（与 harness 一致，零第三方依赖）
6. 每步完成后跑 `python tools/workbench-smoke.py` 必须通过

## P0 · 数据层定型

`story-bible.json` 升级 schema v2：

```json
{
  "schema_version": 2,
  "revision": 7,
  "book": {...不变...},
  "opening_contract": {...不变...},
  "characters": [...不变...],
  "world": {...},
  "compass": {"ending_direction": "", "reader_promise": "", "active_long_line_ids": []},
  "arc": {...不变..., "locked_through": 0, "planned_through": 12},
  "ledger": [...],
  "shadows": [],
  "chapters": {
    "1": {"status": "locked", "card_path": "chapters/ch01/card.json"}
  }
}
```

- 加载旧版（无 schema_version）时自动迁移：补默认字段、`meta.cell` 包装为 card
- 新增 `build/` 目录：`bible_to_spec()` 的产物落盘 `build/spec.json`，标注 generated 标记；bible 是唯一人工写入口

## P1 · 章节卡 card.json

目录结构：

```
chapters/chNN/
  card.json
  drafts/
```

card.json 字段（完整 schema 见下），`engine` 内嵌现有细胞字段族（原样透传）：

```json
{
  "chapter": 1,
  "chapter_type": "A",
  "base_state_revision": 0,
  "pov": {"character": "陆小满", "tense": "past"},
  "time_place": "当夜，九门典当行",
  "opening_state": "…",
  "objective": "…",
  "obstacle": "…",
  "choice": {"selected": "…", "irreversible": true, "cost": "…"},
  "intended_consequence": "…",
  "recorded_consequence": null,
  "reader_promise": {"type": "信息|情绪|事件|画面", "content": "…"},
  "ending_state": "…",
  "allowed_fact_ids": ["F1_HOOK"],
  "prohibited_developments": ["…"],
  "active_hook_ids": ["F1"],
  "dialogue_budget": {"min_ratio": 0.4},
  "engine": {
    "arc_label": "…", "amplitude": "XL|L|M|S|B",
    "plan": "…", "disruption": "…", "crisis": "…", "improvisation": "…",
    "pressure": [{"char": "…", "motive": "want|need|wound|value|fear|contradiction", "force": "…", "cost": "…"}],
    "end_hook": "新信息型|两难型|即将行动型|轻收束"
  }
}
```

新增 `src/harness/schema.py`：`validate_card(card, bible) -> list[str]`（返回违规清单）校验：必填字段、char 必须在 bible.characters、amplitude/end_hook 枚举、pressure.motive 枚举、force 与 plan/disruption 同源（关键词重叠启发式即可）、chapter int。

工作流改造：

- `discuss`：改为两阶段。阶段一输出 3 条轻量分支（`discussions/chNN.branches.json`）：`[{id:"A", summary, beats:[3-5条], choice, motive_cost, reader_payoff, risks:[]}]`——作者输入分支 id 选择；阶段二针对选中分支深入讨论（原有 REPL 保留）
- `lock`：从讨论记录提炼**完整章节卡**（LLM 输出 JSON，schema.py 校验，作者确认 y 后落盘 card.json；校验不过则把违规清单反馈 LLM 重试最多 2 次）
- `write`：硬门禁——无校验通过的 card.json 拒绝落笔；正文产出到 `chapters/chNN/drafts/v001.md`（不再直接写 chapters/chNN.md）；`bible_to_spec()` 优先读 `meta.card.engine`（旧 `meta.cell` 兼容）

## P5 · 多线推演（并入 P1 的 discuss 改造，见上）

## 验收标准（全部满足才算完成）

1. `python tools/workbench-smoke.py` 适配 card 流程后端到端通过（smoke 脚本需要你一并更新：seed 数据用 branches 文件而非旧 discussion 格式）
2. 旧格式迁移：对含旧 `meta.cell` 的 bible 跑 `status`/`write` 不报错且行为等价
3. `schema.py` 对 5 组非法 card（缺字段/错枚举/未知人物）分别给出明确违规信息
4. 新建测试书走完 new → char(手工JSON seed) → discuss(选分支) → lock → write 全流程
5. `git status` 干净提交到 M1 分支，commit message 描述每个 P 项

## 交付物

- workbench.py / src/harness/schema.py（新增）/ src/harness/config.py（如需）
- tools/workbench-smoke.py（适配版）
- 变更说明：M1-CHANGES.md（改了什么/为什么/怎么测的）
