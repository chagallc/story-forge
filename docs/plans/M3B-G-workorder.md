# M3B-G 工单 · 世界设定系统 + 时代素材收集

> 验收合同由 Hana 提供。执行方：ZCode。不得自行修改。
> 基线：main（M1+M2+M3A+WebGUI 全部合入）

## 目标

给工作台增加「世界设定」系统：每本书可以收集和管理对应时代/场景可用的素材（真实历史事件、地理、物品、风俗、流行文化等），这些素材在章节讨论时自动注入 AI 的上下文，让 AI 编剧提议和落笔时能调用真实的时代细节。

以《大水将至》为例：1998 年武汉的夏天——抗洪前线动态、长江水位、电视新闻、街上跑的车、放的电影、学生书包里的文具、街口小卖部卖的零食……这些细节让 AI 写出的正文有真实质感而非泛化的"90年代感"。

## 数据结构

`workspaces/<书>/story-bible.json` 的 `world` 字段升级：

```json
{
  "world": {
    "setting": "（保留现有一句话设定）",
    "glossary": [],
    "time_period": "1998年夏，武汉",
    "era_materials": [
      {
        "id": "mat_001",
        "category": "历史事件",
        "keywords": ["抗洪", "长江水位", "防汛"],
        "content": "1998年长江全流域特大洪水，武汉关8月1日超警戒水位……",
        "source": "手动添加 | AI提议已确认",
        "chapter_range": null
      },
      {
        "id": "mat_002",
        "category": "流行文化",
        "keywords": ["电影", "录像厅"],
        "content": "《泰坦尼克号》1998年4月在中国上映，大街小巷都在放主题曲……",
        "source": "",
        "chapter_range": null
      }
    ],
    "locations": [
      {"id": "loc_001", "name": "九门典当行街", "description": "……", "notes": ""}
    ],
    "rules": []
  }
}
```

category 枚举（可扩展）：`历史事件 / 地理环境 / 流行文化 / 生活细节 / 物品道具 / 人物背景素材 / 规则与禁忌 / 其他`

## 功能

### 1. 世界设定管理页（Web + CLI）

- `workspaces/<书>/world/` 目录不再需要（素材全在 bible.world.era_materials 里）
- Web：书工作台顶栏加「🌍 世界设定」按钮 → 世界设定页（左侧分类列表 + 右侧条目编辑表单 + 「＋ 添加素材」+ 「✎ AI 提议素材」按钮）
- CLI：`wb world <书名> list` / `wb world <书名> add` / `wb world <书名> remove <id>`

### 2. AI 素材提议（核心）

`POST /api/book/<name>/world/propose` {topic: "1998年夏天的日常生活", count: 10}

- LLM（reader 通道，异构）基于书的 genre/language/time_period/topic 生成素材建议
- 返回候选列表，作者逐条确认/修改/拒绝 → 确认的批量写入 era_materials
- prompt 要点：按 category 分类输出，每条包含 keywords 数组（用于讨论/落笔时的相关性匹配），内容要求具体到可以直接写进正文

### 3. 章节讨论/落笔时自动注入（核心）

- `write_prepare` / `discuss` 组装上下文时，从 era_materials 中按本章 card.keywords（或 arc_label）匹配相关素材，注入 prompt 尾部：

```
【时代素材（本章可用的真实细节）】
- [历史事件] 1998年长江全流域特大洪水……
- [生活细节] 学生用的文具是英雄牌钢笔和阵风牌书包……
```

- 不做关键词匹配时（章节卡无 keywords），按 arc_label 前缀匹配或全量注入前 10 条（控制 token）

### 4. 讨论板集成

- 人物共创和章节讨论的 system prompt 中追加 era_materials 摘要（按相关度取 5-10 条），让 AI 编剧提议人物和剧情时自然融入时代细节

## 技术约束

- 零第三方依赖（stdlib only）
- 不改 engine.py / Ledger / state.py
- 兼容旧 bible（无 era_materials 字段时自动补空数组，migrate 链 v4→v5）
- `world/propose` 的 LLM 调用失败不阻塞（返回错误给前端）

## 验收标准

1. smoke 适配后通过
2. `POST /world/propose` 用《大水将至》测试：{topic: "1998年武汉夏天 中学生的日常生活", count: 10} → 返回 ≥8 条具体素材（非泛化的"90年代"）
3. era_materials 写入后 `GET /book/<name>` 可见
4. write 时投影 prompt 包含 era_materials 摘要（投影开/关均有效）
5. 旧 bible 兼容（无 era_materials 不报错）
6. `git status` 干净 + WEBGUI-CHANGES.md 或 M3B-CHANGES.md

## 提示

- era_materials 的 propose prompt 是关键：要求 LLM 输出「可以直接写进正文的具体细节」而非「背景说明」。正例：「巷口小卖部冰柜里只有盐水和绿豆两个品种，白砂糖的贵五毛」；反例：「90年代中国物质相对匮乏」。审核标准：每条素材单独拿出来可以作为一句正文插入而不违和。
- 先用《大水将至》测试，确认素材质量后再通用化
