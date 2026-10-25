# 写作引擎部署指南（跨机器复制）

> 适用：把 story-forge 实验台复制到另一台电脑上运行。
> 前提：目标机器能访问某个 OpenAI 兼容端点（DeepSeek 官方 API 在中国大陆可直连，无需代理）。

## 1. 引擎的组成（哪些东西必须带走）

```
story-forge/
├── src/harness/          ← 引擎本体（6 个 .py 文件，Python 标准库实现，零第三方依赖）
├── experiments/
│   ├── exp001/           ← 示例：spec.json + config.json（可当模板复制）
│   └── exp002/           ← 引擎模式示例
├── docs/                 ← 设计文档（不含引擎也能跑，但建议带上）
├── 台账.md / README.md
└── .gitignore            ← reference/ 已忽略，参考仓库不需要带走
```

**不需要**：`reference/` 目录（两个参考仓库共数百 MB，已被 gitignore，引擎运行完全不依赖）；`experiments/*/runs/`（历史运行产物，可不带）。

## 2. 环境要求

- Python **3.10 或更高**（engine.py 使用 `dict | None` 语法）
- 无需 pip install 任何包（urllib + json + os 即全部）
- 操作系统不限（Windows / macOS / Linux 均可）

验证：`python --version` ≥ 3.10；`python -c "import urllib.request, json"` 不报错。

## 3. 转移方式（三选一）

| 方式 | 命令/操作 | 适用 |
|---|---|---|
| git clone | 在目标机 `git clone <仓库地址>`（GitHub 需代理或镜像 `ghfast.top`，见台账环境备忘） | 目标机有网 |
| git bundle（离线） | 源机：`git bundle create story-forge.bundle --all`；目标机：`git clone story-forge.bundle story-forge` | U 盘/内网 |
| 直接拷贝 | 复制整个目录（跳过 reference/ 和 runs/），目标机 `git init` 不需要 | 一次性快照 |

## 4. 目标机配置（一次性）

1. **API Key**：设置环境变量（PowerShell 示例）：
   ```powershell
   [Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "sk-xxx", "User")
   ```
   重开终端生效。Key 不进 git，只进环境变量。
2. **模型配置**：编辑 `experiments/<exp>/config.json`。writer/reader 各自可指向**任何 OpenAI 兼容端点**：
   - DeepSeek 官方：`https://api.deepseek.com`
   - 月之暗面：`https://api.moonshot.cn/v1`
   - 智谱：`https://open.bigmodel.cn/api/paas/v4`
   - 本地模型：Ollama/LM Studio/vLLM 的 OpenAI 兼容端口（此时 key 任意填）
   - OpenRouter（需代理）：`https://openrouter.ai/api/v1`
   改 `api_key_env` 指向你设置的环境变量名，`model` 改成该端点的模型 ID。
3. **代理注意**：引擎默认绕过系统代理直连（llm.py 中 ProxyHandler({})）。若端点需要走代理，在该 client 配置里加 `"use_system_proxy": true`。

## 5. 运行

```bash
cd story-forge
# 烟雾测试（2 章验证管线）
python -m src.harness.run --arm E --run 0 --exp exp002 --smoke
# 正式运行（A/B/C/E 臂，E = 引擎模式）
python -m src.harness.run --arm E --run 1 --exp exp002
# 分析（金丝雀/软泄漏/曲线聚合）
python -m src.harness.analyze exp002/E1
```

新实验：复制一份 `experiments/exp002/` 改名，替换 `spec.json`（故事规格：premise/characters/ledger/engine），config 可继承 exp001 的。

## 6. 已知坑（台账环境备忘的机器无关版）

- Windows 下 git 会提示 LF→CRLF 警告，无害
- 断点续跑：中断后直接重跑同一命令，已写章节从磁盘恢复，不重复烧 token
- 预算护栏：config 里 `budget` 为单 run 单角色硬上限（token），超限即停
- 同一 run 目录不要并行跑两个进程（usage.jsonl 会交错）
- GLM 盲读者（subagent 方式）依赖 HanaAgent 平台，跨机部署时这层需要人工替代：找一个人（或另一个 chat 会话）按 `reader-external/checkpoint-N.json` 的格式渐进盲读即可，schema 在 docs/story-engine-spec.md
