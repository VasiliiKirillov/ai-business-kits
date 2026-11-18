"""Загрузка business.yaml в pydantic-модели. Ошибки - по-русски, с указанием ключа."""
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

ROOT = Path(__file__).resolve().parent.parent
HELP = "скопируй config/business.example.yaml в config/business.yaml"
META_KEYS = {"type", "name", "contact", "language", "confirmed", "declined_field", "wants_photo", "photo_of"}
DOC_FIELDS = ("full_name", "number", "nationality", "birth_date")


class ConfigError(Exception):
    pass


class M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Business(M):
    name: str
    description: str = ""
    timezone: str = "UTC"
    currency: str = ""
    language: str = "ru"


class Style(M):
    no_emoji: bool = False
    no_exclamation: bool = False
    replace_yo: bool = False
    plain_dashes: bool = False
    lowercase_start: bool = False


class Bot(M):
    persona: str
    tone: str = ""
    address: Literal["auto", "ty", "vy"] = "auto"
    greeting: str = "Здравствуйте! Напишите, что вам нужно."
    tone_examples: list[str] = []
    banned_phrases: list[str] = []
    style: Style = Style()
    facts: list[str] = []
    voice_reply: str = "голосовые пока не понимаю, напишите текстом"


class Field(M):
    key: str
    type: Literal["date", "time", "int", "text", "phone", "email", "item", "choice"]
    label: str = ""
    describe: str = ""      # для разбора текста нейросетью
    ask: str = ""           # что спросить у клиента
    default: Optional[Any] = None
    ask_only_if_unclear: bool = False
    declinable: bool = False
    decline_reason: str = ""
    choices: list[str] = []

    @model_validator(mode="after")
    def _fill(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.key):
            raise ValueError(f"ключ поля '{self.key}': только строчные латинские буквы, цифры и _")
        if self.key in META_KEYS or self.key.endswith("_unclear") or self.key.startswith("doc_"):
            raise ValueError(f"ключ поля '{self.key}' зарезервирован, выбери другой")
        if self.type == "choice" and not self.choices:
            raise ValueError(f"поле '{self.key}': для type choice нужен список choices")
        if self.ask_only_if_unclear and self.default is None:
            raise ValueError(f"поле '{self.key}': для ask_only_if_unclear нужен default")
        if self.declinable and not self.decline_reason:
            raise ValueError(f"поле '{self.key}': для declinable нужен decline_reason")
        self.label = self.label or self.key
        self.describe = self.describe or self.label
        self.ask = self.ask or self.label
        return self


class IdentityDoc(M):
    enabled: bool = False
    name: str = "документ"
    reason: str = ""
    fields: list[Literal["full_name", "number", "nationality", "birth_date"]] = list(DOC_FIELDS)
    accept_photo: bool = True


class Request(M):
    noun: str = "заявка"
    item_noun: str = "позиция"
    fields: list[Field]
    identity_document: IdentityDoc = IdentityDoc()
    parse_hints: list[str] = []


class Category(M):
    name: str
    aliases: list[str] = []


class Item(M):
    name: str
    aliases: list[str] = []
    category: Optional[str] = None
    price: Optional[float] = None
    stock: int = 1
    duration_min: Optional[int] = None
    details: Optional[str] = None


class Catalog(M):
    price_unit: str = ""
    categories: list[Category] = []
    items: list[Item] = []


class Discount(M):
    min_duration: float
    percent: float


class Pricing(M):
    mode: Literal["per_day", "per_unit", "fixed"] = "per_unit"
    duration_field: Optional[str] = None
    quantity_field: Optional[str] = None
    discounts: list[Discount] = []
    rounding: int = 1
    duration_words: list[str] = ["день", "дня", "дней"]   # 1 / 2-4 / 5+


class Hours(M):
    open: str
    close: str
    step_min: int = 30


class Availability(M):
    mode: Literal["none", "days", "slots"] = "none"
    date_field: Optional[str] = None
    duration_field: Optional[str] = None
    time_field: Optional[str] = None
    capacity: Union[int, Literal["per_item"]] = "per_item"
    hours: Optional[Hours] = None
    alternatives: int = 2


class Manager(M):
    confirm_button: str = "Подтвердить"
    own_button: str = "Отвечу сам"
    after_confirm_client: str = "Менеджер подтвердил. Напиши клиенту подтверждение и что дальше"
    handoff_text: str = "передал менеджеру, он проверит и подтвердит"


class GoogleSheets(M):
    catalog_tab: str = "Catalog"
    bookings_tab: str = "Bookings"


class Data(M):
    source: str = "local"   # local | google_sheets | "пакет.модуль:Класс"
    google_sheets: GoogleSheets = GoogleSheets()


class Documents(M):
    engine: Literal["none", "docx", "google_docs"] = "none"
    docx_template: str = "templates/contract.docx"
    output_dir: str = "output"
    title: str = "Документ {booking_id} - {client_name}"
    constants: dict[str, str] = {}


class Config(M):
    business: Business
    bot: Bot
    request: Request
    catalog: Catalog = Catalog()
    pricing: Pricing = Pricing()
    availability: Availability = Availability()
    manager: Manager = Manager()
    data: Data = Data()
    documents: Documents = Documents()

    @property
    def item_key(self) -> Optional[str]:
        return next((f.key for f in self.request.fields if f.type == "item"), None)

    @property
    def keys(self) -> list[str]:
        return [f.key for f in self.request.fields]

    def field(self, key: str) -> Field:
        return next(f for f in self.request.fields if f.key == key)

    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else ROOT / p

    @model_validator(mode="after")
    def _check(self):
        keys = self.keys
        for k in {k for k in keys if keys.count(k) > 1}:
            raise ValueError(f"request.fields: ключ '{k}' повторяется")
        items = [f for f in self.request.fields if f.type == "item"]
        if len(items) > 1 or (self.catalog.items and not items):
            raise ValueError("request.fields: нужно ровно одно поле с type item, если в каталоге есть позиции")

        def ref(section, name, key):
            if key is not None and key not in keys:
                raise ValueError(f"{section}.{name}: поля '{key}' нет в request.fields")
        p, a = self.pricing, self.availability
        ref("pricing", "duration_field", p.duration_field)
        ref("pricing", "quantity_field", p.quantity_field)
        if p.mode == "per_day" and not p.duration_field:
            raise ValueError("pricing.duration_field: для mode per_day нужно поле длительности")
        if len(p.duration_words) != 3:
            raise ValueError("pricing.duration_words: нужно ровно 3 слова (1 / 2-4 / 5 и больше)")
        for n in ("date_field", "duration_field", "time_field"):
            ref("availability", n, getattr(a, n))
        if a.mode != "none":
            if not self.item_key:
                raise ValueError("availability: для проверки занятости нужно поле с type item")
            if not a.date_field:
                raise ValueError("availability.date_field: укажи поле с датой")
        if a.mode == "days" and not a.duration_field:
            raise ValueError("availability.duration_field: для mode days нужно поле длительности")
        if a.mode == "slots" and not a.time_field:
            raise ValueError("availability.time_field: для mode slots нужно поле со временем")
        if a.hours:
            for t in (a.hours.open, a.hours.close):
                try:
                    datetime.strptime(t, "%H:%M")
                except ValueError:
                    raise ValueError(f"availability.hours: время '{t}' должно быть в формате HH:MM")
        cats = {c.name for c in self.catalog.categories}
        for it in self.catalog.items:
            if it.category and cats and it.category not in cats:
                raise ValueError(f"catalog.items: у '{it.name}' категория '{it.category}' не описана в categories")
            if a.mode == "slots" and not it.duration_min and not a.hours:
                raise ValueError(f"catalog.items: у '{it.name}' нужен duration_min (или availability.hours)")
        idc = self.request.identity_document
        if idc.enabled and not idc.fields:
            raise ValueError("request.identity_document.fields: список не может быть пустым")
        return self


def _fmt_errors(e: ValidationError) -> str:
    out = []
    for er in e.errors():
        where = ".".join(str(x) for x in er["loc"] if x != "function-after[_check(), Config]")
        msg = {"extra_forbidden": "неизвестное поле (опечатка?)", "missing": "обязательное поле не заполнено"}.get(
            er["type"], er["msg"].removeprefix("Value error, "))
        out.append(f"- {where + ': ' if where else ''}{msg}")
    return "\n".join(out)


def load(path: Optional[str] = None) -> Config:
    """path: явный путь, иначе env BUSINESS_CONFIG, иначе config/business.yaml."""
    path = path or os.getenv("BUSINESS_CONFIG") or "config/business.yaml"
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = ROOT / p
    if not p.exists():
        raise ConfigError(f"Не найден конфиг {path}: {HELP}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{p}: не читается yaml: {e}")
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"{p}: ошибки в конфиге:\n{_fmt_errors(e)}")


def today(cfg: Config) -> date:
    """Сегодняшняя дата в часовом поясе бизнеса."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(cfg.business.timezone)).date()
    except Exception:
        return date.today()
