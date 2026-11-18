"""Google Sheets: каталог и брони. Вкладки и колонки описаны в README. Нужны google_token.json и SHEET_ID."""
import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

from .. import google_auth
from ..config import Config, Item
from .base import AvailabilityMixin, CANCELLED

CATALOG_COLS = ["name", "category", "price", "stock", "aliases", "details"]
BASE_COLS = ["id", "item", "start", "end", "client", "contact", "phone", "total", "status", "document", "created"]
CACHE_SEC = 60
log = logging.getLogger("intake.sheets")


def safe(v):
    """Текст клиента не должен стать формулой в таблице."""
    s = str(v if v is not None else "")
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def columns(cfg: Config) -> list[str]:
    extra = list(cfg.keys) + (["doc_" + k for k in cfg.request.identity_document.fields] if cfg.request.identity_document.enabled else [])
    return BASE_COLS + [k for k in extra if k not in BASE_COLS]


class GoogleSheetsSource(AvailabilityMixin):
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sid = os.environ["SHEET_ID"]
        self.tabs = cfg.data.google_sheets
        self._cache: tuple = (0.0, [])
        self._lock = threading.Lock()

    def _values(self):
        return google_auth.service("sheets", "v4").spreadsheets().values()

    def catalog(self) -> list[Item]:
        with self._lock:
            if time.time() - self._cache[0] < CACHE_SEC and self._cache[1]:
                return self._cache[1]
        try:
            rows = self._values().get(spreadsheetId=self.sid, range=f"{self.tabs.catalog_tab}!A2:F500").execute().get("values", [])
            base = {i.name.lower(): i for i in self.cfg.catalog.items}
            items = []
            for r in rows:
                r += [""] * (6 - len(r))
                if not r[0]:
                    continue
                old = base.get(str(r[0]).lower())
                items.append(Item(name=str(r[0]), category=r[1] or None, price=_f(r[2]), stock=int(_f(r[3]) or 1),
                                  aliases=[a.strip().lower() for a in str(r[4]).split(",") if a.strip()] or (old.aliases if old else []),
                                  details=r[5] or (old.details if old else None), duration_min=old.duration_min if old else None))
            if items:
                with self._lock:
                    self._cache = (time.time(), items)
                return items
        except Exception as e:
            log.warning("catalog from sheet failed: %s", e)
        return self._cache[1] or list(self.cfg.catalog.items)  # запасной вариант: последний известный или конфиг

    def _rows(self) -> list[list]:
        return self._values().get(spreadsheetId=self.sid, range=f"{self.tabs.bookings_tab}!A:ZZ",
                                  valueRenderOption="FORMATTED_VALUE").execute().get("values", [])

    def list_bookings(self) -> list[dict]:
        rows = self._rows()
        if not rows:
            return []
        head, out = rows[0], []
        for r in rows[1:]:
            r = r + [""] * (len(head) - len(r))
            d = dict(zip(head, r))
            if d.get("id"):
                out.append({**{k: d.get(k, "") for k in BASE_COLS}, "data": {k: v for k, v in d.items() if k not in BASE_COLS}})
        return out

    def next_booking_id(self) -> str:
        nums = [int(b["id"].split("-")[-1]) for b in self.list_bookings() if str(b["id"]).split("-")[-1].isdigit()]
        return f"BK-{(max(nums) if nums else 0) + 1:04d}"

    def save_booking(self, booking: dict) -> str:
        booking.setdefault("id", self.next_booking_id())
        f = {**(booking.get("fields") or {}), **{"doc_" + k: v for k, v in (booking.get("doc") or {}).items()}}
        doc = booking.get("document") or ""
        base = {"id": booking["id"], "item": safe(booking.get("item")), "start": _text(booking.get("start")), "end": _text(booking.get("end")),
                "client": safe(booking.get("client_name")), "contact": safe(booking.get("contact")), "phone": safe(booking.get("phone")),
                "total": booking.get("total") or "", "status": booking.get("status", "подтверждена"),
                "document": f'=HYPERLINK("{doc}","документ")' if doc.startswith("http") else safe(doc),
                "created": datetime.now().strftime("%Y-%m-%d %H:%M")}
        row = [base[c] if c in base else safe(f.get(c)) for c in columns(self.cfg)]
        self._values().append(spreadsheetId=self.sid, range=f"{self.tabs.bookings_tab}!A:A", valueInputOption="USER_ENTERED",
                              insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()
        return booking["id"]

    def cancel_booking(self, booking_id: str) -> None:
        rows = self._rows()
        if not rows:
            return
        col = rows[0].index("status")
        letter = chr(ord("A") + col)
        for i, r in enumerate(rows, 1):
            if r and r[0] == booking_id:
                self._values().update(spreadsheetId=self.sid, range=f"{self.tabs.bookings_tab}!{letter}{i}",
                                      valueInputOption="USER_ENTERED", body={"values": [[CANCELLED]]}).execute()


def _text(v) -> str:
    """Даты пишем строкой ISO ('2030-12-01T14:00'), иначе таблица превратит их в свой формат и чтение сломается."""
    return "'" + str(v) if v else ""


def _f(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
