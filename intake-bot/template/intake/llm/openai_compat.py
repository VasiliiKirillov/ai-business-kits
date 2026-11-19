"""Любой API в формате /chat/completions: openai, deepseek, openrouter, ollama, custom."""
import os

import httpx

from .base import Provider, proxy

PRESETS = {  # base_url, модель по умолчанию (проверь актуальные имена у провайдера)
    "openai": ("https://api.openai.com/v1", "gpt-5-mini"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-5-mini"),
    "ollama": ("http://localhost:11434/v1", "llama3.1"),
    "custom": ("", ""),
}


class OpenAICompat(Provider):
    def __init__(self, name: str):
        self.name = name
        self.base_url, self.model = PRESETS[name]
        self.vision = name in ("openai", "openrouter")

    async def complete(self, system, messages, json=False, image=None, purpose="parse"):
        msgs = [dict(m) for m in messages]
        if image:
            msgs[-1]["content"] = [{"type": "image_url", "image_url": {"url": f"data:{image[0]};base64,{image[1]}"}},
                                   {"type": "text", "text": msgs[-1]["content"]}]
        body = {"model": self.model_for(purpose, self.model, self.model),
                "messages": [{"role": "system", "content": system}] + msgs}
        if self.name == "openai":
            body["max_completion_tokens"] = 4000
        else:
            body["max_tokens"] = 4000
            body["temperature"] = 0
        if json:
            body["response_format"] = {"type": "json_object"}
        base = (os.getenv("LLM_BASE_URL") or self.base_url).rstrip("/")
        headers = {"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'none')}"}
        async with httpx.AsyncClient(proxy=proxy(), timeout=120) as c:
            r = await c.post(f"{base}/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        j = r.json()
        u = j.get("usage") or {}
        return j["choices"][0]["message"]["content"], {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}
