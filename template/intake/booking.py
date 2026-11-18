"""Бронь: интервал занятости и словарь для документов и источника данных."""
from datetime import date, datetime, timedelta
from typing import Optional

from .catalog import Catalog
from .config import Config, Item, today
from . import pricing


def parse_dt(date_s, time_s=None) -> Optional[datetime]:
    try:
        d = date.fromisoformat(str(date_s)[:10])
        t = datetime.strptime(str(time_s)[:5], "%H:%M").time() if time_s else datetime.min.time()
        return datetime.combine(d, t)
    except (TypeError, ValueError):
        return None


def iso(s) -> Optional[datetime]:
    """'2030-12-05T14:00' или '2030-12-05' -> datetime."""
    try:
        return datetime.fromisoformat(str(s)[:16])
    except ValueError:
        return None


def interval(cfg: Config, f: dict, item: Optional[Item]) -> Optional[tuple[datetime, datetime]]:
    """Что занимает бронь: days -> [дата, дата+дни), slots -> [дата+время, +duration_min)."""
    a = cfg.availability
    if a.mode == "none":
        return None
    if a.mode == "days":
        start = parse_dt(f.get(a.date_field))
        try:
            return (start, start + timedelta(days=int(f.get(a.duration_field)))) if start else None
        except (TypeError, ValueError):
            return None
    start = parse_dt(f.get(a.date_field), f.get(a.time_field))
    if not start:
        return None
    mins = (item.duration_min if item else None) or (a.hours.step_min if a.hours else 60)
    return start, start + timedelta(minutes=mins)


def fmt_date(s) -> str:
    d = parse_dt(s)
    return d.strftime("%d.%m.%Y") if d else str(s or "")


def real_phone(f: dict) -> str:
    p = str(f.get("phone") or "").strip()
    return "" if p in ("", "-") else p


def phone_of(cfg: Config, f: dict) -> str:
    k = next((x.key for x in cfg.request.fields if x.type == "phone"), None)
    p = str(f.get(k) or "").strip() if k else ""
    return "" if p in ("", "-") else p


def build(cfg: Config, catalog: Catalog, data: dict, booking_id: str, unit: Optional[str] = None) -> dict:
    """data - данные лида из базы (fields, name, contact, ...) -> словарь брони."""
    f = dict(data.get("fields") or {})
    doc = f.pop("doc", None) or {}
    item = catalog.by_name(unit or "") or catalog.named(f.get(cfg.item_key) or "") if cfg.item_key else None
    iv = interval(cfg, f, item)
    a = cfg.availability
    start = iv[0].isoformat(timespec="minutes") if iv else str(f.get(a.date_field) or "")
    end = iv[1].isoformat(timespec="minutes") if iv else ""
    c = pricing.calc(cfg, item, f)
    name = doc.get("full_name") or data.get("name") or ""
    d_from = fmt_date(start) + (f" {start[11:16]}" if a.mode == "slots" and iv else "")
    return {"id": booking_id, "item": (item.name if item else None) or f.get(cfg.item_key) or "", "unit": unit,
            "start": start, "end": end, "date_from": d_from, "date_to": fmt_date(end) if a.mode == "days" else "",
            "client_name": name, "contact": data.get("contact") or "", "phone": phone_of(cfg, f),
            "price": item.price if item else None, "total": c["total"] if c else None, "currency": cfg.business.currency,
            "fields": f, "doc": doc, "status": "подтверждена", "document": "", "today": fmt_date(today(cfg).isoformat())}
