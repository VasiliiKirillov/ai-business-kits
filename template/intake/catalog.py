"""Каталог: поиск позиций в тексте клиента по названиям и синонимам, прайс-лист."""
from typing import Optional

from .config import Config, Item


class Catalog:
    def __init__(self, cfg: Config, items: Optional[list[Item]] = None):
        self.cfg = cfg
        self.items = list(items if items is not None else cfg.catalog.items)

    def set_items(self, items: list[Item]):
        if items:
            self.items = list(items)

    def by_name(self, name: str) -> Optional[Item]:
        n = (name or "").strip().lower()
        return next((i for i in self.items if i.name.lower() == n), None)

    def match(self, text: str) -> list[tuple[Item, str]]:
        """-> [(позиция, 'item')] если названа конкретная позиция, [(позиция, 'category')] если только категория, иначе []."""
        s = (text or "").lower()
        if not s:
            return []
        found = []
        for it in self.items:
            pos = [s.find(k) for k in (it.name.lower(), *[a.lower() for a in it.aliases]) if k and k in s]
            if pos:
                found.append((min(pos), it))
        if found:
            return [(it, "item") for _, it in sorted(found, key=lambda x: x[0])]
        for c in self.cfg.catalog.categories:
            if any(k and k in s for k in (c.name.lower(), *[a.lower() for a in c.aliases])):
                return [(it, "category") for it in self.items if it.category == c.name]
        return []

    def named(self, text: str) -> Optional[Item]:
        """Первая конкретно названная позиция или None."""
        return next((it for it, k in self.match(text) if k == "item"), None)

    def price_unit_text(self) -> str:
        c = self.cfg
        return " ".join(x for x in (c.business.currency, c.catalog.price_unit) if x)

    def price_list(self) -> str:
        """Для промпта чата: прайс по категориям."""
        unit = self.price_unit_text()
        groups: dict = {}
        for it in self.items:
            groups.setdefault(it.category or "", []).append(f"{it.name} - {_n(it.price)}" if it.price is not None else it.name)
        parts = [(f"{c}: " if c else "") + ", ".join(v) for c, v in groups.items()]
        return "; ".join(parts) + (f" ({unit})" if unit and any(i.price is not None for i in self.items) else "")


def _n(x) -> str:
    return str(int(x)) if x is not None and float(x) == int(x) else str(x)
