# 风格守门 · 中文 AI 腔负面清单（style guard / zh）

> 来源：lieflat-less-ai-tone 520万字人机对照实证（9条通用信号）、Humanizer-zh、anti-vibe-writing、stop-slop 的中文规则提炼。
> 用法：写作 agent 的 system prompt 注入「简版」，analyze 阶段的 style_lint.py 执行「全量版」。
> 原则（agent-novel 二分法）：风格信号只观察、不神秘化；事实与指令错误才拦截。

## 简版（注入写作 prompt，≤200字）

1. 禁用「不是A，而是B」式对仗（人机差异最强的句式，δ+0.88）
2. 禁用模板句：「值得注意的是」「从某种意义上说」「仿佛在诉说」「空气仿佛凝固」「不知过了多久」
3. 允许自然重复用词；刻意每个词都不一样反而不像人写的
4. 句长要有波动：短句三五个字和长句二三十字混着来，不要句句差不多长
5. 少用破折号与冒号总结腔（「X：Y」式收束）
6. 段落不要都碎成两三行；该一整段讲完的就一整段

## 全量（style_lint.py 检查项）

| # | 信号 | 检测方式 | 阈值（观察级） |
|---|---|---|---|
| 1 | 对仗句式 | 正则「不是[^。]{1,12}[，,]而是」 | 每章 ≥2 命中 |
| 2 | 模板句 | 黑名单词表命中 | 每千字 ≥1 |
| 3 | 词汇回避 | 词汇多样性与篇幅比值过高 | 观察值 |
| 4 | 句长方差 | 句长标准差 / 均值（CV） | CV < 0.5 |
| 5 | 分节碎 | 平均段落字数 < 60 且段落 > 20 | 触发 |
| 6 | 冒号总结腔 | 「[一-龥]{2,6}[：:]」每千字频次 | 每千字 ≥3 |
| 7 | 破折号密度 | 「——」每千字 | 每千字 ≥2 |
| 8 | 欧化腔 | 句首「被/使得/作为/对于」频次 | 每千字 ≥2 |
| 9 | 假深刻独词句 | ≤4字的独立段落占比 | > 15% |

## 黑名单词表（模板句）

值得注意的是 / 从某种意义上说 / 仿佛在诉说 / 空气仿佛凝固 / 不知过了多久 / 时光仿佛静止 / 眼神里闪过一丝 / 嘴角勾起一抹 / 声音不大却清晰 / 空气中弥漫着 / 一股无形的压力 / 说不清道不明 / 某种难以言喻 / 无声的呐喊 / 内心深处

---

# Style Guard · English AI-flavor blacklist (en)

> Sources: blader/humanizer (64.5k), stop-slop (18.6k), slop-forensics methodology, adapted for webnovel serialization prose.
> Usage: EN brief injects into WRITER_SYSTEM_EN; EN lint section in style_lint.py checks the full list.

## Brief (writer prompt, EN)

1. Ban "not just X, but Y" / "it wasn't X; it was Y" constructions (the English twin of the strongest zh signal)
2. Ban slop vocabulary: delve, tapestry, testament to, embark, navigate (metaphorical), shimmer, dance/symphony/whisper (metaphorical), myriad, intricate, palpable, unspoken, ethereal, breathtaking
3. Ban stock beats: "let out a breath she didn't know she was holding", "little did they know", "something shifted", "the air was thick with", "eyes gleamed with + abstract noun"
4. Vary sentence length aggressively; fragments are fine in action beats
5. Em-dashes ≤ 1 per chapter; no tricolon closers ("X, Y, and Z" as final beat)
6. Concrete nouns and specific verbs over intensifiers; no summarizing endings

## Full lint items (en)

| # | Signal | Detection | Threshold (observe) |
|---|---|---|---|
| 1 | not-just-but | regex `not (just|merely|only) [^.]{1,40},? (but|rather)` + `wasn't just` | ≥2/chapter |
| 2 | slop words | blacklist density | ≥1 per 500 words |
| 3 | stock beats | phrase blacklist (let out a breath / little did / something shifted / air thick with) | any hit |
| 4 | sentence-length CV | std/mean of sentence lengths | < 0.45 |
| 5 | em-dash density | `—` per 500 words | ≥2 |
| 6 | tricolon closer | final sentence matches `\w+, \w+, and \w+` pattern | hit |
| 7 | participial tail | `, (signaling|marking|bringing|heralding|promising) ` | ≥2/chapter |
| 8 | -ly adverb density | `\b\w+ly\b` per 500 words | ≥8 (webnovel prose tolerates some) |

## EN blacklist (slop words)

delve / tapestry / testament / embark / navigate / shimmer / myriad / intricate / palpable / ethereal / mesmerizing / captivating / enthralling / breathtaking / awe-inspiring / symphony / kaleidoscope / unspoken / palpable / relentless(abstract) / profound(abstract) / gaze(verb) / breath hitches / heart hammers / blood runs cold

## EN blacklist (stock beats)

let out a breath (she|he|they) didn't know (she|he|they) was holding / little did (she|he|they|I) know / something shifted / the air was thick with / eyes (gleamed|glinted|darkened) with / a mixture of ... crossed (his|her) face / and then, everything changed / the weight of (the world|their words) / time seemed to slow
