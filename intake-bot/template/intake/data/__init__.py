"""get_source(): выбор источника данных по config.data.source."""
import importlib

from ..config import Config


def get_source(cfg: Config):
    s = cfg.data.source
    if s == "local":
        from .local import LocalSource
        return LocalSource(cfg)
    if s == "google_sheets":
        from .google_sheets import GoogleSheetsSource
        return GoogleSheetsSource(cfg)
    if ":" in s:  # свой адаптер: "пакет.модуль:Класс", конструктор принимает cfg
        mod, cls = s.split(":", 1)
        return getattr(importlib.import_module(mod), cls)(cfg)
    raise ValueError(f"data.source='{s}': ожидается local, google_sheets или 'пакет.модуль:Класс'")
