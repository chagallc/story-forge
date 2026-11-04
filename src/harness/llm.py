"""极简 OpenAI 兼容客户端：stdlib only，带预算护栏与 token 台账。"""
import json
import os
import time
import urllib.request


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
