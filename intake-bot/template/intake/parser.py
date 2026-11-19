"""Нейросеть только понимает текст и отдает JSON. Валидация и повтор - код."""
import re
import time

from pydantic import ValidationError

from .catalog import Catalog
from .config import Config, today
from .llm.base import Provider
from .prompts import parser_system
from .schema import build_lead_model


def extract_json(text: str) -> str:
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


async def parse(provider: Provider, cfg: Config, catalog: Catalog, transcript: str, client: str = "",
                awaiting_confirm: bool = False, model=None) -> dict:
    """transcript - ВСЯ переписка по текущему обращению. -> {lead, first_try_ok, seconds, tokens, error}"""
    Lead = model or build_lead_model(cfg)
    system, t0, tokens, err = parser_system(cfg, catalog, today(cfg)), time.monotonic(), {"in": 0, "out": 0}, None
    text = transcript
    if awaiting_confirm:
        text = f"[Бот показал клиенту итог]\n{text}"
    if client:
        text = f"[Клиент пишет из мессенджера: {client}]\n{text}"
    user = text
    for attempt in (1, 2):
        try:
            raw, usage = await provider.complete(system, [{"role": "user", "content": user}], json=True, purpose="parse")
            tokens["in"] += usage["in"]
            tokens["out"] += usage["out"]
            lead = Lead.model_validate_json(extract_json(raw))
            return {"lead": lead, "first_try_ok": attempt == 1, "seconds": time.monotonic() - t0, "tokens": tokens, "error": None}
        except (ValidationError, ValueError) as e:
            err = str(e)[:300]
            user = f"{text}\n\n(Прошлый ответ не прошел проверку схемы: {err}. Верни корректный JSON.)"
        except Exception as e:  # сеть, 5xx
            err = f"{type(e).__name__}: {e}"[:300]
    return {"lead": None, "first_try_ok": False, "seconds": time.monotonic() - t0, "tokens": tokens, "error": err}
