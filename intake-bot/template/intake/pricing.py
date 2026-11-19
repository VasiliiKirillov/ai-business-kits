"""Цены и итог считает код, не модель. Режимы: per_day, per_unit, fixed + скидки по длительности."""
import re
from typing import Optional

from .catalog import Catalog, _n
from .config import Config, Item


def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def duration(cfg: Config, f: dict) -> Optional[float]:
    k = cfg.pricing.duration_field
    return _num(f.get(k)) if k else None


def quantity(cfg: Config, f: dict) -> int:
    k = cfg.pricing.quantity_field
    return int(_num(f.get(k)) or 1) if k else 1


def dur_word(cfg: Config, n) -> str:
    n = int(n)
    w = cfg.pricing.duration_words
    if 11 <= n % 100 <= 14:
        return w[2]
    return w[0] if n % 10 == 1 else w[1] if n % 10 in (2, 3, 4) else w[2]


def calc(cfg: Config, item: Optional[Item], f: dict) -> Optional[dict]:
    """-> {total, formula, discount} или None, если цену назвать нельзя (нет позиции/цены/длительности)."""
    p = cfg.pricing
    if not item or item.price is None:
        return None
    price, q, d = float(item.price), quantity(cfg, f), duration(cfg, f)
    if p.mode == "per_day":
        if not d:
            return None
        base, formula = price * d * q, f"{_n(price)} x {_n(d)}" + (f" x {q}" if q > 1 else "")
    elif p.mode == "per_unit":
        base, formula = price * q, f"{_n(price)}" + (f" x {q}" if q > 1 else "")
    else:
        base, formula = price, f"{_n(price)}"
    pct = max([x.percent for x in p.discounts if d and d >= x.min_duration], default=0)
    total = base * (100 - pct) / 100
    step = max(p.rounding, 1)
    total = int(total / step + 0.5) * step
    cur = cfg.business.currency
    return {"total": total, "discount": pct,
            "formula": f"{formula} = {total} {cur}".strip() + (f" (скидка {_n(pct)}%)" if pct else "")}


def price_phrase(cfg: Config, item: Item, f: dict) -> str:
    """'450 бат в день, на 3 дня выйдет 1350 бат (скидка ...)'"""
    cur = cfg.business.currency
    s = f"{_n(item.price)} {cur} {cfg.catalog.price_unit}".replace("  ", " ").strip()
    c = calc(cfg, item, f)
    if c:
        d, q = duration(cfg, f), quantity(cfg, f)
        if cfg.pricing.mode == "per_day":
            s += f", на {_n(d)} {dur_word(cfg, d)} выйдет {c['total']} {cur}"
        elif q > 1:
            s += f", за {q} выйдет {c['total']} {cur}"
        if c["discount"]:
            s += f" (скидка {_n(c['discount'])}%)"
    return s


def price_status(cfg: Config, catalog: Catalog, text: str, f: dict) -> Optional[str]:
    """Статус для чата сразу после того, как клиент назвал позицию. None - нечего сказать."""
    ms = catalog.match(text)
    if not ms or ms[0][0].price is None:
        return None
    if ms[0][1] == "category":
        lst = ", ".join(f"{i.name} - {_n(i.price)}" for i, _ in ms if i.price is not None)
        return f"Назови цены позиций этой категории ({catalog.price_unit_text()}): {lst}"
    return f"Скажи цену: {ms[0][0].name} - {price_phrase(cfg, ms[0][0], f)}"


def clean_words(cfg: Config, text: str) -> str:
    """'3 дн.' -> '3 дня' для текста клиенту (в карточке остается коротко)."""
    return re.sub(r"(\d+) дн\.", lambda m: f"{m.group(1)} {dur_word(cfg, m.group(1))}", text)
