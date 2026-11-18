"""Движок документов: render(booking) -> {url, path, id}; delete(result)."""
import re
from typing import Protocol

from ..booking import fmt_date
from ..config import Config

BLANK = "________"


class DocumentEngine(Protocol):
    def render(self, booking: dict) -> dict: ...
    def delete(self, result: dict) -> None: ...


def placeholders(cfg: Config, b: dict) -> dict:
    """Значения для {{КЛЮЧ}} в шаблоне. Пустое значение -> прочерк-линия."""
    f, doc = b.get("fields") or {}, b.get("doc") or {}
    v = {}
    for fld in cfg.request.fields:  # поля заявки; даты в виде ДД.ММ.ГГГГ
        x = f.get(fld.key)
        v[fld.key.upper()] = fmt_date(x) if fld.type == "date" and x else x
    v.update({"BOOKING_ID": b.get("id"), "DATE": b.get("today"), "CLIENT_NAME": b.get("client_name"),
              "CLIENT_CONTACT": b.get("contact"), "CLIENT_PHONE": b.get("phone"), "ITEM": b.get("item"),
              "PRICE": _s(b.get("price")), "TOTAL": _s(b.get("total")), "CURRENCY": b.get("currency"),
              "DATE_FROM": b.get("date_from") or v.get("DATE_FROM"), "DATE_TO": b.get("date_to")})
    for k in ("full_name", "number", "nationality", "birth_date"):
        v["DOC_" + k.upper()] = doc.get(k)
    v.update(cfg.documents.constants)
    return {k: (str(x) if x not in (None, "", "-") else BLANK) for k, x in v.items()}


def _s(x) -> str:
    return "" if x is None else (str(int(x)) if float(x) == int(x) else str(x))


def title(cfg: Config, b: dict) -> str:
    """Имя файла/документа по documents.title; недопустимые символы убираем."""
    class D(dict):
        def __missing__(self, k):
            return ""
    t = cfg.documents.title.format_map(D(booking_id=b.get("id"), client_name=b.get("client_name") or "client",
                                         item=b.get("item"), date=b.get("date_from")))
    return re.sub(r'[\\/:*?"<>|]+', "_", t).strip() or str(b.get("id"))
