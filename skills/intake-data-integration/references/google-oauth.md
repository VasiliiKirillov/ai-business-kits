# Google OAuth: пошаговое подключение

Нужно, если данные (таблица) и документы лежат в Google. Делается один раз. Объясняй человеку каждый шаг: "Мы разрешаем нашему боту работать с вашими таблицами и документами, больше ни с чем." Все клики в Google Cloud Console делает человек (или ты через управление браузером, если он разрешил). Интерфейс меняется, поэтому при расхождении найди актуальную инструкцию Google.

## 1. Проект в Cloud Console

1. Открыть https://console.cloud.google.com/ и войти в нужный Google-аккаунт (тот, где будут таблицы).
2. Вверху выбрать проект, "New project", имя например "intake-bot", создать.

## 2. Включить API

В меню "APIs & Services", затем "Library". Найти и нажать Enable для трех API:

- Google Sheets API
- Google Docs API
- Google Drive API

## 3. Экран согласия (OAuth consent screen)

"APIs & Services", затем "OAuth consent screen" (в новом интерфейсе разделы Branding, Audience, Data Access в Google Auth Platform).

**Branding** (обязательно заполнить, иначе публикация не пойдет):

- App name: любое понятное, например название бизнеса
- User support email: почта владельца
- Application home page: адрес сайта бизнеса или любая страница о нем
- Application privacy policy link: ссылка на политику конфиденциальности (может быть простая страница или документ, доступный по ссылке)
- Authorized domains: домен сайта, соответствующий ссылкам выше
- Developer contact email: почта владельца

**Audience:** выбрать External.

**Data Access (Scopes):** добавить
- `https://www.googleapis.com/auth/spreadsheets`
- `https://www.googleapis.com/auth/documents`
- `https://www.googleapis.com/auth/drive.file` (только файлы, которые создал сам бот: шаблон договора загружай через `setup_google_sheet.py --upload-template`, а не создавай руками)

## 4. ВАЖНО: опубликовать в Production

Пока приложение в режиме Testing, refresh-токен действует всего 7 дней, потом бот теряет доступ (`invalid_grant`). Поэтому:

1. Убедись, что Branding заполнен.
2. Перейти в Audience.
3. Нажать "Publish app" и подтвердить. Статус должен стать "In production".

Проверку Google (verification) проходить не нужно для личного использования: приложение останется "unverified", это нормально.

Токен, полученный до публикации, остается семидневным. После публикации обязательно заново запусти `tools/google_auth.py` (шаг 6).

## 5. OAuth-клиент типа Desktop

1. "APIs & Services", затем "Credentials", "Create credentials", "OAuth client ID".
2. Application type: **Desktop app**. Имя любое.
3. Скопировать Client ID и Client secret. Человек сам вписывает их в `.env` на сервере:

```
GOOGLE_OAUTH_CLIENT_ID=<your-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<your-client-secret>
```

(Точные имена переменных смотри в `template/.env.example`.) Не пересылай secret в чат.

## 6. Авторизация через туннель

Скрипт авторизации слушает порт 8085 на сервере, а браузер у владельца на компьютере. Соединяем их туннелем.

1. На компьютере владельца открыть туннель (окно оставить открытым):

```bash
ssh -L 8085:localhost:8085 <user>@<server-ip>
```

2. В этой же SSH-сессии на сервере (Google-зависимости: `uv pip install --python .venv/bin/python -r requirements-google.txt`):

```bash
cd ~/intake-bot
.venv/bin/python tools/google_auth.py
```

3. Скрипт напечатает ссылку. Открыть ее в браузере на своем компьютере.
4. Выбрать аккаунт. Появится экран "Google не проверил это приложение": это ожидаемо. Нажать "Дополнительно" (Advanced), затем "Перейти на страницу <название>" (Go to <app name>).
5. Отметить все запрошенные разрешения, нажать "Продолжить".
6. Браузер перекинет на localhost:8085 и покажет сообщение об успехе. Скрипт сохранит `google_token.json`.

Если бот запущен локально на компьютере владельца, туннель не нужен: просто запусти `.venv/bin/python tools/google_auth.py` там.

## 7. Права на токен

```bash
chmod 600 google_token.json
```

Токен не копируй в репозиторий и не пересылай.

## Проверка

- Файл `google_token.json` есть, права `600`.
- В Cloud Console статус приложения "In production".
- `.venv/bin/python tools/setup_google_sheet.py` создает таблицу без ошибок (или бот читает существующую).

## Типичные ошибки

- `invalid_grant`: токен протух (приложение было в Testing) или отозван. Опубликовать в Production и повторить шаг 6.
- `access_denied` на экране согласия: аккаунт не добавлен в тестовые пользователи (если приложение еще в Testing). Опубликуй в Production.
- Порт 8085 занят или туннель не открыт: браузер не достучится до localhost. Проверь, что окно с `ssh -L` открыто.
- Не включен нужный API: ошибка `accessNotConfigured`. Включить его в Library.
- Экран согласия не дает опубликовать: не заполнены Branding-поля.
