"""Динамическая модель Lead: что нейросеть обязана вернуть. Строится из конфига."""
from typing import Literal, Optional

from pydantic import Field, create_model

from .config import Config

DOC_DESC = {"full_name": "полное имя как в документе", "number": "номер документа (не телефон)",
            "nationality": "гражданство по-английски: Russia, Germany", "birth_date": "дата рождения YYYY-MM-DD"}
TYPE_DESC = {"date": "YYYY-MM-DD", "time": "HH:MM, 24 часа"}


def build_lead_model(cfg: Config):
    declinable = [f.key for f in cfg.request.fields if f.declinable]
    fields: dict = {
        "type": (Literal["request", "question", "complaint", "spam"], ...),
        "name": (Optional[str], None),
        "contact": (Optional[str], None),
        "language": (str, Field("ru", description="код языка последнего сообщения клиента: ru, en, ...")),
        "confirmed": (bool, Field(False, description="клиент в ПОСЛЕДНЕМ сообщении явно согласился с итогом")),
        "declined_field": (Optional[str], Field(
            None, description="ключ поля, которое клиент в ПОСЛЕДНЕМ сообщении отказался давать; из: " + ", ".join(declinable))),
        "wants_photo": (bool, Field(False, description="клиент в ПОСЛЕДНЕМ сообщении просит фото позиции")),
        "photo_of": (Optional[str], Field(None, description="позиция, фото которой просит клиент, если назвал")),
    }
    for f in cfg.request.fields:
        desc = f.describe + (f" ({TYPE_DESC[f.type]})" if f.type in TYPE_DESC else "")
        if f.type == "choice":
            desc += ": " + " | ".join(f.choices)
        fields[f.key] = (Optional[int] if f.type == "int" else Optional[str], Field(None, description=desc))
        if f.ask_only_if_unclear:
            fields[f.key + "_unclear"] = (bool, Field(False, description=f"клиент назвал {f.label} неясно, нужно уточнить"))
    idc = cfg.request.identity_document
    if idc.enabled:
        for k in idc.fields:
            fields["doc_" + k] = (Optional[str], Field(None, description=f"{idc.name}: {DOC_DESC[k]}"))
    return create_model("Lead", **fields)
