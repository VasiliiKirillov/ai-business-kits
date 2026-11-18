"""Источник данных: каталог + брони. Общая логика занятости лежит здесь, источники дают только данные."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol

from ..booking import interval, iso
from ..catalog import Catalog, _n
from ..config import Config, Item

CONFIRMED = "подтверждена"
CANCELLED = "отменена"


@dataclass
class Availability:
    ok: bool
    unit: Optional[str] = None                       # что именно бронируем (название позиции)
    alternatives: list[str] = field(default_factory=list)  # уже отформатированы: "Name - 450 бат в день" или "14:30"
    busy_text: str = ""                               # для переписки: "<X> нет в наличии на эти даты"
    drop_key: Optional[str] = None                    # какое поле сбросить у клиента (позиция или время)


class DataSource(Protocol):
    def catalog(self) -> list[Item]: ...
    def check_availability(self, req: dict) -> Optional[Availability]: ...   # None = проверить нельзя -> считаем свободным
    def reserve(self, req: dict) -> Optional[str]: ...                       # перепроверка перед записью; None = занято
    def next_booking_id(self) -> str: ...
    def save_booking(self, booking: dict) -> str: ...
    def cancel_booking(self, booking_id: str) -> None: ...
    def list_bookings(self) -> list[dict]: ...


class AvailabilityMixin:
    """Нужны self.cfg, self.catalog(), self.list_bookings()."""
    cfg: Config

    def check_availability(self, req: dict) -> Optional[Availability]:
        return self._plan(req)

    def reserve(self, req: dict) -> Optional[str]:
        a = self._plan(req)
        if a is None:  # проверить нельзя - не блокируем менеджера
            return str(req.get(self.cfg.item_key) or "-") if self.cfg.item_key else "-"
        return a.unit if a.ok else None

    # --- внутреннее
    def _used(self, bookings, start, end, item: Optional[Item]) -> int:
        """Сколько единиц занято в интервале (по позиции при per_item, иначе во всем пуле)."""
        qk, n = self.cfg.pricing.quantity_field, 0
        for b in bookings:
            if b.get("status") != CONFIRMED:
                continue
            bs, be = iso(b.get("start")), iso(b.get("end"))
            if not bs or not be or not (start < be and bs < end):
                continue
            if item is not None and str(b.get("item", "")).lower() != item.name.lower():
                continue
            n += int(_num((b.get("data") or {}).get(qk)) or 1) if qk else 1
        return n

    def _cap(self, item: Item) -> int:
        c = self.cfg.availability.capacity
        return item.stock if c == "per_item" else int(c)

    def _free(self, bookings, item: Item, start, end, qty: int) -> bool:
        per_item = self.cfg.availability.capacity == "per_item"
        return self._used(bookings, start, end, item if per_item else None) + qty <= self._cap(item)

    def _plan(self, req: dict) -> Optional[Availability]:
        cfg, a = self.cfg, self.cfg.availability
        if a.mode == "none" or not cfg.item_key:
            return None
        cat = Catalog(cfg, self.catalog())
        ms = cat.match(str(req.get(cfg.item_key) or ""))
        if not ms:
            return None
        cand = [i for i, _ in ms]
        named = [i for i, k in ms if k == "item"] or cand
        qk = cfg.pricing.quantity_field
        qty = int(_num(req.get(qk)) or 1) if qk else 1
        bookings = self.list_bookings()
        if a.mode == "days":
            iv = interval(cfg, req, cand[0])
            if not iv:
                return None
            start, end = iv
            for it in cand:
                if self._free(bookings, it, start, end, qty):
                    return Availability(True, it.name)
            first = named[0]
            alts = [i for i in cat.items if i.name not in {n.name for n in named}
                    and self._free(bookings, i, start, end, qty)]
            alts.sort(key=lambda i: i.category != first.category)  # сначала та же категория
            unit = cat.price_unit_text()
            fmt = [f"{i.name} - {_n(i.price)} {unit}" if i.price is not None else i.name for i in alts[:a.alternatives]]
            return Availability(False, None, fmt, f"{first.name} нет в наличии на эти даты", cfg.item_key)
        # slots
        item = cand[0]
        iv = interval(cfg, req, item)
        if not iv:
            return None
        start, end = iv
        dur = end - start
        why = None
        if a.hours:
            op, cl = (datetime.strptime(t, "%H:%M").time() for t in (a.hours.open, a.hours.close))
            if start.time() < op or end > datetime.combine(start.date(), cl):
                why = f"время {start:%H:%M} не подходит (работаем {a.hours.open}-{a.hours.close})"
        if not why and self._free(bookings, item, start, end, qty):
            return Availability(True, item.name)
        # свободные слоты в этот же день, ближайшие к желаемому
        slots = []
        if a.hours:
            t = datetime.combine(start.date(), op)
            while t + dur <= datetime.combine(start.date(), cl):
                if t != start and self._free(bookings, item, t, t + dur, qty):
                    slots.append(t)
                t += timedelta(minutes=a.hours.step_min)
        slots.sort(key=lambda t: abs((t - start).total_seconds()))
        alts = sorted(slots[:a.alternatives])
        return Availability(False, None, [f"{t:%H:%M}" for t in alts], why or f"время {start:%H:%M} занято", a.time_field)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
