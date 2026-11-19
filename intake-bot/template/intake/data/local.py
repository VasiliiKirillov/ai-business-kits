"""Локальный источник: каталог из YAML, брони в sqlite. Работает без внешней настройки."""

from .. import db
from ..config import Config, Item
from .base import AvailabilityMixin, CANCELLED


class LocalSource(AvailabilityMixin):
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def catalog(self) -> list[Item]:
        return list(self.cfg.catalog.items)

    def next_booking_id(self) -> str:
        return db.next_booking_id()

    def save_booking(self, booking: dict) -> str:
        booking.setdefault("id", db.next_booking_id())
        return db.add_booking(booking)

    def cancel_booking(self, booking_id: str) -> None:
        db.set_booking_status(booking_id, CANCELLED)

    def list_bookings(self) -> list[dict]:
        return db.bookings()
