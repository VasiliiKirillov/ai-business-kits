"""Живой ответ клиенту: отдельный текстовый вызов модели. Говорит ровно то, что в статусе."""
import re

from .catalog import Catalog
from .config import Config, today
from .llm.base import Provider
from .prompts import chat_system

EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️]")


def to_messages(history: list[tuple[str, str]]) -> list[dict]:
    """[(client|bot, text)] -> чередующиеся user/assistant, первый user, последний user."""
    msgs: list[dict] = []
    for role, text in history:
        r = "user" if role == "client" else "assistant"
        if msgs and msgs[-1]["role"] == r:
            msgs[-1]["content"] += "\n" + text
        elif msgs or r == "user":
            msgs.append({"role": r, "content": text})
    while msgs and msgs[-1]["role"] != "user":
        msgs.pop()
    return msgs


def clean(cfg: Config, text: str) -> str:
    """Пост-обработка по стилю из конфига."""
    s = cfg.bot.style
    if s.no_emoji:
        text = EMOJI.sub("", text)
    if s.no_exclamation:
        text = text.replace("!", ".")
    if s.replace_yo:
        text = text.replace("\u0451", "\u0435").replace("\u0401", "\u0415")
    if s.plain_dashes:
        text = text.replace("\u2014", "-").replace("\u2013", "-")
    text = re.sub(r"[ \t]+\n", "\n", re.sub(r" {2,}", " ", text)).strip()
    if s.lowercase_start and text and text[0].isupper() and not re.match(r"[A-Za-z]", text):
        text = text[0].lower() + text[1:]
    return text


async def reply(provider: Provider, cfg: Config, catalog: Catalog, history: list[tuple[str, str]], status: str = "") -> str:
    system = chat_system(cfg, catalog, today(cfg), status)
    text, _ = await provider.complete(system, to_messages(history), json=False, purpose="chat")
    return clean(cfg, text)
