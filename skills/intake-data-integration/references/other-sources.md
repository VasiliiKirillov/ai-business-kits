# Другие источники данных: Excel, 1C, amoCRM, Bitrix24, Notion, Airtable, своя БД

Если данные не в Google Sheets, пишем адаптер, реализующий `DataSource`, и подключаем его модулем в конфиге.

## Как исследовать

1. Выясни у владельца:
   - Какая система, версия, облачная или на своем сервере?
   - Какой тип авторизации: ключ API, OAuth, логин-пароль, вебхук?
   - Есть ли лимиты запросов?
   - Где лежат позиции и цены (какая таблица, справочник, сущность)?
   - Как представлена бронь: заказ, сделка, запись, строка в таблице? Какие поля обязательны?
   - Как узнать, что позиция занята на даты?
   - Можно ли создать тестовую запись и удалить ее?
2. Найди в интернете текущую документацию API этой системы. Не полагайся на память: интерфейсы меняются. Если API нет или он закрыт, предложи варианты:
   - прямой API, если есть;
   - регулярный экспорт (CSV, Excel) и загрузка адаптером из файла;
   - синхронизация в Google Sheets, а бот работает с таблицей;
   - оставить бот на локальном источнике, а брони отправлять менеджеру и вручную заносить.
3. Предложи варианты владельцу простыми словами с плюсами и минусами, получи выбор.
4. Сначала только чтение: `catalog()`, `check_availability()`, `list_bookings()`. Проверь на реальных данных. Только после явного одобрения включай `reserve()`, `save_booking()` и `cancel_booking()`.

## Скелет адаптера

Положи файл рядом с ботом, например `~/intake-bot/mysource.py`, и в конфиге укажи `data.source: "mysource:MySource"`.

```python
"""Свой источник данных. Логику занятости и альтернатив берем готовой из AvailabilityMixin,
адаптер только читает и пишет данные во внешней системе."""
import os

import httpx

from intake.config import Config, Item
from intake.data.base import AvailabilityMixin, CANCELLED


class MySource(AvailabilityMixin):
    def __init__(self, cfg: Config):
        self.cfg = cfg                                   # имя self.cfg обязательно: его читает AvailabilityMixin
        self.http = httpx.Client(base_url=os.environ["MYSYS_URL"], timeout=15,
                                 headers={"Authorization": f"Bearer {os.environ['MYSYS_TOKEN']}"})  # секреты только из .env

    def catalog(self) -> list[Item]:
        """Позиции и точные цены. Сначала только чтение. Кэшируй на 60 с, если API медленный или с лимитами."""
        rows = self.http.get("/items").json()
        return [Item(name=r["name"], price=r["price"], stock=r.get("stock", 1), category=r.get("category"))
                for r in rows]

    def list_bookings(self) -> list[dict]:
        """Брони в формате, который понимает AvailabilityMixin:
        {"id", "item" (название позиции), "start", "end" (ISO: 2030-12-01 или 2030-12-01T14:00),
         "status" ("подтверждена" занимает место), "data": {"quantity": 1}}  (ключ = pricing.quantity_field)"""
        return [{"id": r["id"], "item": r["item"], "start": r["start"], "end": r["end"],
                 "status": r["status"], "data": {"quantity": r.get("qty", 1)}}
                for r in self.http.get("/bookings").json()]

    def next_booking_id(self) -> str:
        """Номер брони до записи (он попадает в документ)."""
        return f"BK-{len(self.list_bookings()) + 1:04d}"

    def save_booking(self, booking: dict) -> str:
        """Запись. Включай только после согласия владельца. booking: id, item, start, end, client_name,
        contact, phone, total, currency, fields (все поля заявки), document (ссылка или путь)."""
        r = self.http.post("/bookings", json={k: booking[k] for k in
                                              ("id", "item", "start", "end", "client_name", "phone", "total")})
        r.raise_for_status()
        return booking["id"]

    def cancel_booking(self, booking_id: str) -> None:
        self.http.patch(f"/bookings/{booking_id}", json={"status": CANCELLED}).raise_for_status()
```

`check_availability` и `reserve` дает `AvailabilityMixin`: он сам считает пересечения интервалов, вместимость
(`stock` или общий пул из `availability.capacity`), часы работы и альтернативы. Если во внешней системе своя
логика занятости, переопредели `check_availability(req) -> Availability | None` и `reserve(req) -> str | None`.

Эталон: `template/intake/data/local.py` (локальный источник, 25 строк) и `template/intake/data/google_sheets.py`.

## Особенности по системам

- **Excel-файл:** проще всего загрузить в Google Sheets и работать через `google_sheets`. Или читать файл `openpyxl` из общей папки (только чтение).
- **1C:** обычно HTTP-сервисы или OData, доступ настраивает администратор 1C. Уточни версию и включен ли интерфейс.
- **amoCRM, Bitrix24:** REST API с OAuth или вебхуками. Бронь удобно представить сделкой с полями. Смотри актуальные лимиты запросов.
- **Notion, Airtable:** REST API с ключом. Каталог и брони как две базы. Следи за лимитом запросов, кэшируй каталог.
- **Своя БД:** подключайся только на чтение, лучше через отдельного пользователя БД с ограниченными правами.

## Правила

- Секреты только в `.env`, адаптер читает их из окружения.
- Ошибки адаптера не должны ронять бота: бросай исключение с понятным текстом, ядро сообщит менеджеру "не смог ...".
- Цены без округления и догадок.
- Напиши минимальный тест: проверь `catalog()`, затем тестовую бронь и ее отмену.
