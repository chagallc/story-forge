"""极简 OpenAI 兼容客户端：stdlib only，带预算护栏与 token 台账。

另含 CodexClient：ChatGPT Codex OAuth 通道（Responses API + SSE），
token 动态读 ~/.hanako/auth.json（由 Hana 维护刷新）。
"""
import json
import os
import time
import urllib.request
import uuid


class CodexClient:
    """ChatGPT Codex OAuth 推理客户端（Responses API + SSE）。

    token 从 ~/.hanako/auth.json 动态读取（Hana 负责刷新），永不落盘过期。
    """

    ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

    def __init__(self, cfg: dict, usage_log: str):
        self.model = cfg["model"]
        self.max_tokens = cfg.get("max_tokens", 4096)
        self.temperature = cfg.get("temperature", 1)
        self.budget = cfg.get("budget", 500_000)
        self.usage_log = usage_log
        self.total_tokens = 0
        # chatgpt.com 国内必须代理：默认 127.0.0.1:7897，可用 cfg["proxy"] 覆盖
        proxy = cfg.get("proxy", "http://127.0.0.1:7897")
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": proxy, "http": proxy}))

    def _auth(self):
        auth_path = os.path.expanduser("~/.hanako/auth.json")
        with open(auth_path, encoding="utf-8") as f:
            a = json.load(f)["openai-codex"]
        return a["access"], a.get("accountId")

    def chat(self, messages, *, tag="", temperature=None, max_tokens=None):
        token, acct = self._auth()
        # messages (chat format) -> responses input
        inp = []
        for m in messages:
            if m["role"] == "system":
                inp.append({"role": "user", "content": [{"type": "input_text", "text": m["content"]}]})
            else:
                inp.append({"role": m["role"], "content": [{"type": "input_text", "text": m["content"]}]})
        body = {
            "model": self.model,
            "instructions": "",
            "input": inp,
            "max_output_tokens": max_tokens or self.max_tokens,
            "stream": True,
            "store": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": acct,
            "OpenAI-Beta": "responses=experimental",
            "session_id": str(uuid.uuid4()),
            "originator": "codex_cli_rs",
            "Accept": "text/event-stream",
        }
        req = urllib.request.Request(self.ENDPOINT, data=json.dumps(body).encode("utf-8"), headers=headers)
        last_err, texts, usage = None, [], {}
        for attempt in range(3):
            try:
                with self.opener.open(req, timeout=600) as resp:
                    for raw in resp:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            evt = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if evt.get("type") == "response.output_text.delta":
                            texts.append(evt.get("delta", ""))
                        elif evt.get("type") == "response.completed":
                            ro = evt.get("response", {})
                            usage = ro.get("usage", {})
                            # 只在 delta 为空时才用 completed 的完整文本（防重复）
                            if not texts:
                                for item in ro.get("output", []):
                                    if item.get("type") == "message":
                                        for c in item.get("content", []):
                                            texts.append(c.get("text", ""))
                            break
                if texts:
                    break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(3 * (attempt + 1))
        text = "".join(texts).strip()
        if not text:
            raise RuntimeError(f"Codex call failed after retries ({tag}): {last_err}")
        self.total_tokens += usage.get("total_tokens", 0)
        with open(self.usage_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tag": tag, "model": self.model, "usage": usage}, ensure_ascii=False) + "\n")
        if self.total_tokens > self.budget:
            raise BudgetExceeded(f"token budget {self.budget} exceeded ({self.total_tokens})")
        return text


class BudgetExceeded(RuntimeError):
    pass


class LLMClient:
    def __init__(self, cfg: dict, usage_log: str):
        self.base = cfg["base_url"].rstrip("/")
        # key 直传（models.local.json）优先，向后兼容环境变量方式
        if cfg.get("api_key"):
            self.key = cfg["api_key"]
        else:
            self.key = os.environ[cfg["api_key_env"]]
        self.model = cfg["model"]
        self.temperature = cfg.get("temperature", 0.7)
        self.max_tokens = cfg.get("max_tokens", 4096)
        self.budget = cfg.get("budget", 500_000)
        self.extra_body = cfg.get("extra_body", {})
        self.usage_log = usage_log
        self.total_tokens = 0
        # 默认绕过系统代理（本机代理开关不定，国内端点直连即可）；配置 use_system_proxy=true 才走代理
        if cfg.get("use_system_proxy"):
            self.opener = urllib.request.build_opener()
        else:
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def chat(self, messages, *, tag="", temperature=None, max_tokens=None):
        budget_tokens = max_tokens or self.max_tokens
        text = ""
        data = None
        last_err = None
        # 推理模型会把 max_tokens 花在思考上导致正文为空：空则加倍重试
        for attempt in range(3):
            body = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature if temperature is None else temperature,
                "max_tokens": budget_tokens,
            }
            body.update(self.extra_body)
            req = urllib.request.Request(
                self.base + "/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with self.opener.open(req, timeout=300) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(3 * (attempt + 1))
                continue
            text = (data["choices"][0]["message"].get("content") or "").strip()
            if text:
                break
            budget_tokens *= 2
            time.sleep(2)
        if data is None:
            raise RuntimeError(f"LLM call failed after retries ({tag}): {last_err}")
        if not text:
            raise RuntimeError(f"LLM returned empty content after retries ({tag})")
        usage = data.get("usage", {})
        self.total_tokens += usage.get("total_tokens", 0)
        with open(self.usage_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tag": tag, "model": self.model, "usage": usage}, ensure_ascii=False) + "\n")
        if self.total_tokens > self.budget:
            raise BudgetExceeded(f"token budget {self.budget} exceeded ({self.total_tokens})")
        return text
