"""get_provider(): выбор нейросети по env LLM_PROVIDER."""
import os
from typing import Optional

from .base import Provider

NAMES = ("anthropic", "openai", "deepseek", "openrouter", "ollama", "custom", "mock")


def get_provider(name: Optional[str] = None, cfg=None) -> Provider:
    name = (name or os.getenv("LLM_PROVIDER") or "").strip().lower()
    if name not in NAMES:
        raise RuntimeError(f"LLM_PROVIDER='{name}': выбери один из {', '.join(NAMES)}")
    if name == "mock":
        from .mock import MockProvider
        return MockProvider(cfg)
    if name == "anthropic":
        from .anthropic import Anthropic
        return Anthropic()
    from .openai_compat import OpenAICompat
    return OpenAICompat(name)


def get_vision(main: Provider) -> Provider:
    """Провайдер для чтения фото: VISION_PROVIDER или основной."""
    v = os.getenv("VISION_PROVIDER")
    return get_provider(v) if v else main
