"""Фото позиций: папка photos/ (или PHOTOS_DIR), файл <ключ>.jpg. Нет файла - бот обходится без фото."""
import os
import re
from pathlib import Path
from typing import Optional

from .config import ROOT

EXT = ("jpg", "jpeg", "png", "webp")


def folder() -> Path:
    p = Path(os.getenv("PHOTOS_DIR") or "photos")
    return p if p.is_absolute() else ROOT / p


RU = dict(zip("абвгдеезийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
               "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
RU.update({"\u0451": "e", "ж": "zh"})


def key(name: str) -> str:
    """'Honda PCX 160' -> 'hondapcx160', 'Маникюр классический' -> 'manikyurklassicheskiy'"""
    s = "".join(RU.get(ch, ch) for ch in (name or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


def find(name: str) -> Optional[Path]:
    k = key(name)
    if not k:
        return None
    for e in EXT:
        p = folder() / f"{k}.{e}"
        if p.is_file():
            return p
    return None
