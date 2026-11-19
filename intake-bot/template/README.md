# Шаблон бота-приемщика заявок

Telegram-бот, который принимает заявки (аренда, запись, заказ): задает недостающие вопросы по одному, проверяет
занятость и точную цену по вашим данным, собирает контакт и (по желанию) документ, показывает итог, а после
согласия клиента шлет карточку в группу менеджеров с кнопкой "Подтвердить". По кнопке бот заполняет документ
из шаблона и записывает бронь в источник данных.

Весь бизнес живет в `config/*.yaml`. В коде нет ничего про байки, маникюр или торты. Промпты собираются из конфига.

## Быстрый старт

Нужен [uv](https://docs.astral.sh/uv/) (нет: `curl -LsSf https://astral.sh/uv/install.sh | sh`). Python 3.11-3.13 подходит, системный `python3` не используется. Если в скопированной папке случайно оказался `.venv`, удали его (`rm -rf .venv`) и создай заново. Все команды запускай как `.venv/bin/python ...`.

```bash
cd template
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp config/business.example.yaml config/business.yaml     # поправь под свой бизнес
cp .env.example .env                                     # впиши BOT_TOKEN, MANAGER_CHAT_ID, LLM_*
.venv/bin/python tools/check_config.py config/business.yaml   # что будет спрашивать бот, цены, промпты
.venv/bin/python tools/make_docx_template.py config/business.yaml   # заготовка договора templates/contract.docx (перезаписывает файл)
.venv/bin/python -m intake --console                     # проверка в терминале с настоящей нейросетью из .env
.venv/bin/python -m intake                               # Telegram-бот
```

Без ключей: `.venv/bin/python -m intake --console --mock` (заглушка вместо нейросети, видно статусы кода).
Свой конфиг: переменная `BUSINESS_CONFIG`. Группа менеджеров: добавьте бота в группу и отправьте там `/id`.

## Тесты (офлайн, без ключей и сети)

```bash
.venv/bin/python tests/run_scenarios.py          # все сценарии, код выхода 1 при провале
.venv/bin/python tests/run_scenarios.py nail     # по подстроке пути
.venv/bin/python tests/run_scenarios.py -q       # печатать диалог только у упавших
```

Сценарии лежат в `tests/scenarios/<имя конфига>/*.yaml`. Шаг: `client` + `parse` (что "вернул" парсер), `photo`,
`manager: confirm | {own: текст}`, `seed` (занять позицию). Проверки: `expect_bot`, `expect_card`, `expect_buttons`,
`expect_manager`, `expect_booking`, `expect_document`, `expect_photo`, `expect_fields` и другие (см. шапку
`tests/run_scenarios.py`). Заглушка возвращает накопленное состояние из `parse`, а в ответ чата отдает "[бот] " + статус,
поэтому тесты проверяют решения кода, а не стиль модели. Даты в сценариях в 2030 году.

## Как устроено

| Файл | Что делает |
|---|---|
| `intake/config.py` | YAML -> pydantic, ошибки по-русски с указанием ключа |
| `intake/schema.py` | динамическая модель Lead из полей конфига |
| `intake/prompts.py` | промпты разбора и чата из конфига |
| `intake/parser.py` | нейросеть -> JSON по ВСЕЙ переписке, валидация, один повтор |
| `intake/chat.py` | нейросеть -> текст клиенту по статусу, чистка по `bot.style` |
| `intake/core.py` | автомат: код решает, что сказать, чат только озвучивает |
| `intake/catalog.py`, `pricing.py` | поиск позиций по синонимам, цены и скидки |
| `intake/data/` | источники: `local` (sqlite), `google_sheets`, свой `пакет.модуль:Класс` |
| `intake/documents/` | `none`, `docx` (python-docx), `google_docs` |
| `intake/messengers/` | `telegram`, `console`; новый канал = класс по `messengers/base.py` |
| `intake/llm/` | `anthropic`, `openai`, `deepseek`, `openrouter`, `ollama`, `custom`, `mock` |
| `tools/` | настройка Google, шаблон договора, проверка конфига, чистка тестовых данных |

Правила автомата (все в `core.py`): один открытый вопрос за раз, проигнорированный вопрос повторяется на 3-й реплике;
тип обращения определяется по первому сообщению; мат в адрес бота не жалоба; парсер видит всю переписку;
статус решает код; карточка менеджеру только после согласия клиента, фото документов уходят в группу прямо перед
ней; проверка занятости с альтернативами и перепроверка при подтверждении; отказ от поля (`declinable`) объясняется
один раз и пропускается; цена называется сразу после названной позиции; фото позиции отправляется один раз.

## Свой источник данных

Класс с конструктором `(cfg)` и методами `catalog()`, `check_availability(req)`, `reserve(req)`, `next_booking_id()`,
`save_booking(booking)`, `cancel_booking(id)`, `list_bookings()` (см. `intake/data/base.py`). Логика занятости уже есть
в `AvailabilityMixin`: достаточно отдавать каталог и брони (`id, item, start, end, status, data`, занимает только статус
"подтверждена"). Подключается в конфиге: `data.source: "пакет.модуль:Класс"`.

## Google Sheets и Google Docs

```bash
uv pip install --python .venv/bin/python -r requirements-google.txt
.venv/bin/python tools/google_auth.py            # один раз, см. шапку файла (вход через ssh -L 8085:localhost:8085)
.venv/bin/python tools/setup_google_sheet.py --upload-template   # печатает SHEET_ID и GOOGLE_DOC_TEMPLATE_ID для .env
```

Вкладка каталога: `name | category | price | stock | aliases | details` (заголовок в первой строке, алиасы через запятую).
Вкладка броней: `id | item | start | end | client | contact | phone | total | status | document | created | <ключи полей>`.
Таблицу создавайте с локалью en_US (формулы через API в других локалях ломаются). Значения пишутся как USER_ENTERED,
текст клиента экранируется, чтобы не стать формулой.

## Плейсхолдеры в шаблоне документа

`{{BOOKING_ID}} {{DATE}} {{CLIENT_NAME}} {{CLIENT_CONTACT}} {{CLIENT_PHONE}} {{ITEM}} {{PRICE}} {{TOTAL}} {{CURRENCY}}
{{DATE_FROM}} {{DATE_TO}}`, каждое поле заявки заглавными (`{{DELIVERY}}`), `{{DOC_FULL_NAME}} {{DOC_NUMBER}}
{{DOC_NATIONALITY}} {{DOC_BIRTH_DATE}}` и ключи из `documents.constants`. Нет значения - `________`.

## Деплой

`deploy/intake-bot.service` - пользовательский systemd-юнит (`WorkingDirectory=%h/intake-bot`). Установка и
`loginctl enable-linger` описаны в скилле [shared/server-setup](../../shared/server-setup/SKILL.md).
