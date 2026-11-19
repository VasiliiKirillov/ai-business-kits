"""Claude через обычный HTTP. Только официальный ключ API."""
import os

import httpx

from .base import Provider, proxy


class Anthropic(Provider):
    name = "anthropic"
    vision = True

    async def complete(self, system, messages, json=False, image=None, purpose="parse"):
        msgs = [dict(m) for m in messages]
        if image:  # картинка идет первым блоком в последнем сообщении пользователя
            msgs[-1]["content"] = [{"type": "image", "source": {"type": "base64", "media_type": image[0], "data": image[1]}},
                                   {"type": "text", "text": msgs[-1]["content"]}]
        body = {"model": self.model_for(purpose, "claude-haiku-5-5", "claude-sonnet-5-5"), "max_tokens": 4000,
                "system": system, "messages": msgs}
        if os.getenv("ANTHROPIC_EFFORT"):
            body["output_config"] = {"effort": os.environ["ANTHROPIC_EFFORT"]}
        headers = {"x-api-key": os.environ["LLM_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
        async with httpx.AsyncClient(proxy=proxy(), timeout=90) as c:
            r = await c.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        r.raise_for_status()
        j = r.json()
        if j.get("stop_reason") == "refusal":
            raise RuntimeError("модель отказалась отвечать (refusal)")
        text = next(b["text"] for b in j["content"] if b["type"] == "text")  # thinking-блоки могут идти первыми
        u = j.get("usage") or {}
        return text, {"in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0)}
