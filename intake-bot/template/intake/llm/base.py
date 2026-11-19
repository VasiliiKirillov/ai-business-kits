"""Интерфейс провайдера нейросети: один метод complete."""
import os
from typing import Optional


class Provider:
    name = "base"
    vision = False  # умеет читать картинки

    async def complete(self, system: str, messages: list[dict], json: bool = False,
                       image: Optional[tuple] = None, purpose: str = "parse") -> tuple[str, dict]:
        """messages: [{"role": "user"|"assistant", "content": str}]; image: (media_type, base64).
        purpose: parse | chat | vision (выбор модели). -> (текст, {"in": N, "out": N})"""
        raise NotImplementedError

    def model_for(self, purpose: str, default_parse: str, default_chat: str) -> str:
        if purpose == "chat":
            return os.getenv("LLM_MODEL_CHAT") or default_chat
        return os.getenv("LLM_MODEL_PARSE") or default_parse


def proxy() -> Optional[str]:
    return os.getenv("LLM_PROXY") or None
