# M2 工单 · 正史提交 / 角色认知 / 上下文投影 / 豁免状态

> 验收合同由 Hana 提供。执行方：ZCode。本工单是唯一验收标准，执行方不得自行修改。
> 蓝图：docs/plans/v2-整合方案.md（朱雀方案 M2 = P2+P3+P4+P6）
> 基线：M1 已合入 main（章节卡 card.json + schema.py + write 硬门禁 + drafts 目录已存在）

## 目标

把「AI 稿直接变成正史」截断：write 只产草稿与状态变更提案，人工 commit 才推进正史；人物获得显式知识边界（Learn/Never-Learn）；写作上下文按 HOT/WARM/COLD 投影裁剪；lint 误报可持久化豁免。

## 边界（硬性，沿用 M1）

1. `src/harness/engine.py` 细胞语义、`Ledger` 类（含 shadows）零改动
2. 不 merge、不 push、不改 main
3. Python 标准库 only
4. `python tools/workbench-smoke.py` 每个阶段必须通过（脚本随本工单适配）
5. 兼容 M1 格式工作区（smoke-wb 含 card.json 的旧数据必须可迁移续写）
6. `models.local.json` 已复制到本 worktree 的 `config/`（不入库）；如缺失从主仓库 `story-forge/config/models.local.json` 复制

## P2 · canon/drafts 分家 + STATE_DELTA + commit

### 目录结构（在 M1 的 chNN/ 上扩展）

```
chapters/chNN/
  card.json
  drafts/v001.md / v001.delta.json / v001.lint.json
  canon.md            ← commit 后生成，人工定稿
  revisions/          ← canon 修改历史（M3 用，本阶段只建目录约定）
```

### write 改造

- 产出 `drafts/v{NNN}.md`（版本号递增，不覆盖旧草稿）+ `drafts/v{NNN}.delta.json`（状态变更提案）+ `drafts/v{NNN}.lint.json`（lint 结果存档）
- 章节状态机：`branching → discussed → locked → drafted → committed`
- **写第 N 章时前文只读第 1~N-1 章的 canon.md**，绝不读任何 drafts（正史截断的核心）

### STATE_DELTA（delta.json schema）

```json
{
  "chapter": 2,
  "draft": "v001",
  "base_state_revision": 5,
  "ops": [
    {"op": "learn", "character_id": "char_lu_xiaoman", "fact_id": "F1_HOOK", "evidence": "正文原文引用句"},
    {"op": "set_location", "character_id": "char_lu_xiaoman", "value": "九门典当行", "evidence": "…"},
    {"op": "advance_hook", "hook_id": "F1", "action": "plant", "evidence": "…"},
    {"op": "set_inventory", "character_id": "…", "value": "…", "evidence": "…"},
    {"op": "add_relationship", "a": "…", "b": "…", "type": "…", "evidence": "…"}
  ]
}
```

- op 白名单：`learn / set_location / set_inventory / advance_hook / add_relationship / set_false_belief`（实现时可增补，但必须在 state.py 中显式注册）
- 每个op 必带 `evidence`（正文原文子串）；LLM 产 delta 后由代码校验 evidence 确实是正文子串，否则该 op 丢弃并警告

### 新增 src/harness/state.py

- `StoryState` 类：加载/保存 `state/story-state.json`（`{revision, as_of_chapter, characters:{id:{knowledge:{knows,unknown_to_them,false_beliefs}, location, injuries, inventory, relationships}}, facts:{}, hooks:{}, timeline:[], exemptions:[]}`）
- `apply_delta(delta, draft_text) -> list[str]`：校验 `base_state_revision == state.revision`（不匹配返回错误）、op 白名单、evidence 是 draft_text 子串、`learn` 与 `never_learn` 冲突硬拒绝；返回违规清单
- `commit_delta(delta)`：全部通过后原子推进（临时文件 + `os.replace`），`revision += 1`，提交前备份 `state/story-state.json.bak-{revision}`
- `recorded_consequence` 回填：commit 时将本章 card 的该字段从 null 填为正文实际结局一句（从 delta 的 advance_hook/set_* 提炼或人工输入）

### 新增 commit 命令

`python workbench.py commit <书名> <章号>`

1. 读最新 draft + delta → `apply_delta` 校验
2. 有违规：打印清单退出（作者可手工修 delta.json 后重跑）
3. 无违规：打印将推进的状态变更清单 → 作者 `y` 确认 → `canon.md` 写入 draft 全文（或作者指定的修订版路径）→ `commit_delta` 原子推进 → card 的 `recorded_consequence` 回填 → 章节状态 `committed`
4. `--revised <文件>` 参数：作者改过稿后用修订版作为 canon 内容（delta 的 evidence 校验同时针对修订版）

## P3 · 人物卡四分区

`bible.characters[]` 升级（migrate 兼容 M1 旧卡：缺字段补默认）：

```json
{
  "id": "char_lu_xiaoman",
  "name": "陆小满",
  "card": "…",
  "anchors": ["不可变人格锚点，1-3 条"],
  "want": "…", "need": "…", "wound": "…", "value": "…", "fear": "…", "contradiction": "…",
  "voice": {"catchphrases": [], "speech_habits": [], "forbidden": [], "sample_line": "…", "mes_example": ["3-5 条完整对话样本"]},
  "knowledge_rules": {
    "learn": [{"fact_id": "F1_HOOK", "when": "亲自看见怀表刻痕"}],
    "never_learn": ["F1_REVEAL"]
  },
  "lorebook": [{"fact_id": "F1_HOOK", "keywords": ["怀表", "刻痕"], "content_ref": "ledger:F1.hook"}]
}
```

- `id` 为稳定引用键；`pressure[].char`、`pov.character`、delta 的 `character_id` 全部迁移为 id（迁移时自动生成 `char_{拼音或序号}`）；name 保留为显示名
- 动机栈仍对 writer **全量可见**（决策 0003 不变）——知识区限制的是事实，不是作者了解人物内心的权利
- `char` 命令适配新字段（mes_example / anchors / knowledge_rules 的交互式输入）

## P4 · HOT/WARM/COLD 投影

新增 `src/harness/context.py`：

- `build_context(bible, state, spec, chapter, config) -> dict`（返回 hot/warm/cold 三层文本块）
- **HOT**（writer 必注入）：本章 card（engine 细胞+dialogue_budget+allowed/prohibited）、出场人物动机栈+声口卡（mes_example 取 1 条）+动态状态、`Ledger.directive_for(chapter)`、前一章 canon 摘要（末 300 字）
- **WARM**（writer 注入摘要）：最近 2 章 canon 摘要（各 200 字）、未闭合 hook 列表、弧锚点、相关人物关系
- **COLD**（默认不注入）：完整 bible、全部旧正文、shadow、未到期 reveal_plan——只能被显式检索授权
- 硬约束：`shadows` 永不进任何 writer 投影；reader 只读 canon；`Ledger.full_text()` 仅供臂 A/B 实验与作者规划
- **开关**：`bible.book.context_projection = true|false`（默认 false = M1 全文历史行为不变；true 时 writer 上下文用投影）。smoke 两种模式都要覆盖

## P6 · 豁免即状态

- `state.exemptions[]`：`{"id": "EX001", "rule": "style.分节碎|continuity.location|…", "fingerprint": "sha1(rule+chapter+entity+source_text_hash)[:16]", "scope": {"chapter": 4, "character_id": "…"}, "source_text_hash": "…", "reason": "…", "created_by": "author"}`
- 新命令 `python workbench.py exempt <书名> <章号> <规则> <理由>`：对指定章节最近 lint 的 finding 建豁免（fingerprint 绑定正文 hash；正文变化后豁免自动失效——`lint_chapter` 结果比对时跳过已豁免 finding）
- `lint` 汇报时过滤已豁免项并注明「N 项已豁免」

## 验收标准（全部满足才算完成）

1. `python tools/workbench-smoke.py` 适配后端到端通过，新增断言至少覆盖：draft 版本递增、delta 白名单外 op 被拒、无 evidence op 被拒、never_learn 冲突硬拒绝、commit 后 state.revision 推进且备份存在、写 ch2 时上下文不含 ch1 的 drafts（投影可测）、豁免后 lint 不再报该项、正文改动后豁免失效
2. 投影开关两种模式 smoke 都通过（false=行为与 M1 等价）
3. M1 格式工作区（smoke-wb 旧数据副本）迁移续写不报错
4. `state.py` 负样本：base_state_revision 不匹配 / 非白名单 op / evidence 非子串 / never_learn 冲突，各自给出明确错误
5. 手动验证：对 smoke-wb 跑 `commit` 后 `state/story-state.json` 的 revision 与 characters.knowledge 正确推进
6. `git status` 干净，全部提交在 M2 分支，附 M2-CHANGES.md（决策记录格式同 M1-CHANGES.md）

## 提示

- `tools/workbench-smoke.py` 是你上一次写的（M1 版），本次在其上扩展；LLM 调用的测试沿用 seed 文件模式（不依赖真实 API 的部分用 seed，需要真实生成的部分标注）
- `config/models.local.json` 已就位
- 遇到工单未覆盖的决策：自行裁决 + 记入 M2-CHANGES.md「工单未写明的决策」节（格式同 M1）
