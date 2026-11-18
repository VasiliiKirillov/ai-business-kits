---
name: intake-server-setup
description: "Поднять VPS под бота: SSH-ключи, отдельный пользователь, Python и uv, systemd --user с автозапуском, логи, прокси при геоблокировке; используй, когда бот должен работать круглосуточно."
---

# Сервер: VPS, SSH, systemd

## Когда использовать

Когда бот уже запускается локально (`intake-bot-build`) и его нужно перенести туда, где он работает 24/7. Либо когда владелец просит "сначала на своем компьютере": тогда используй раздел "Локальный запуск" и вернись сюда позже.

## Что нужно от человека

- Решение, где держать бота: VPS или свой компьютер (для теста).
- Если VPS: аккаунт у хостинг-провайдера и готовность заплатить (порядка 5 долларов в месяц). Покупку делает человек сам, ты только говоришь, что выбрать.
- Доступ к серверу: IP-адрес и пароль root (или уже добавленный ключ) от провайдера. Пароль человек вводит сам при первом входе, в чат его лучше не писать.

## Шаги

Перед каждым шагом объясни человеку, что делаешь и зачем, одной-двумя фразами. Перед платным и необратимым (покупка сервера, отключение пароля) спроси явное согласие.

### 1. Выбор VPS

Скажи человеку, на что смотреть:

- 1 vCPU, 1 ГБ памяти, 10 ГБ диска: этого хватает.
- Ubuntu 24.04 LTS.
- Регион: такой, где провайдеры LLM не блокируют обращения (у многих API блокировка по стране). Если сомневаешься, выбери регион в Европе или США, либо заранее планируй прокси.
- Не селись на сервер, где уже работают важные вещи при малой памяти: бот не тяжелый, но вы можете уронить соседей.
- Оплата и покупка на стороне человека. После покупки провайдер выдаст IP и пароль root.

### 2. SSH-ключ на компьютере владельца

Объясни: "Ключ это как цифровой ключ от двери сервера, надежнее пароля."

```bash
ls ~/.ssh/id_ed25519.pub 2>/dev/null || ssh-keygen -t ed25519 -C "intake-bot" -f ~/.ssh/id_ed25519 -N ""
ssh-copy-id root@<server-ip>
```

Пароль root человек вводит сам. Если `ssh-copy-id` нет (Windows), покажи содержимое `~/.ssh/id_ed25519.pub` и попроси добавить его в панели провайдера или в файл `~/.ssh/authorized_keys` на сервере.

### 3. Первый вход и отдельный пользователь

Объясни: "Работать под root небезопасно, создадим обычного пользователя."

```bash
ssh root@<server-ip>
adduser --disabled-password --gecos "" <user>
usermod -aG sudo <user>
mkdir -p /home/<user>/.ssh && cp ~/.ssh/authorized_keys /home/<user>/.ssh/
chown -R <user>:<user> /home/<user>/.ssh && chmod 700 /home/<user>/.ssh && chmod 600 /home/<user>/.ssh/authorized_keys
echo "<user> ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-<user>
apt update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
exit
```

Проверь вход под новым пользователем: `ssh <user>@<server-ip> whoami`.

### 4. Отключить вход по паролю (только после проверки ключа)

Спроси согласие. Это необратимо в том смысле, что без ключа не зайти.

```bash
ssh <user>@<server-ip>
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/*.conf 2>/dev/null
sudo sshd -T | grep -i passwordauthentication     # должно быть: passwordauthentication no
sudo systemctl restart ssh
```

Дополнительные файлы в `sshd_config.d/` могут перебивать основной, поэтому правим и их и проверяем итог через `sshd -T`. Не закрывай первый терминал: сначала во ВТОРОМ терминале проверь вход по ключу (`ssh <user>@<server-ip> whoami`), и только после этого закрой первый.

### 5. Python 3.12 и uv

```bash
ssh <user>@<server-ip>
sudo DEBIAN_FRONTEND=noninteractive apt-get -y install rsync curl git
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
uv python install 3.12
```

### 6. Копирование бота на сервер

С компьютера владельца (из папки с ботом):

```bash
rsync -av --exclude .venv --exclude .env --exclude '*.db' --exclude output --exclude google_token.json ~/intake-bot/ <user>@<server-ip>:~/intake-bot/
```

Или `git clone`, если бот лежит в приватном репозитории. `.env` и токены не копируй через git.

### 7. Виртуальное окружение и зависимости

```bash
ssh <user>@<server-ip>
cd ~/intake-bot
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
# если данные в Google:
uv pip install --python .venv/bin/python -r requirements-google.txt
```

### 8. Файл .env

Объясни: "В этом файле лежат пароли бота. Он виден только вам."

Лучше, чтобы человек сам вписал значения:

```bash
cp .env.example .env && chmod 600 .env
nano .env
```

Заполняется как в `intake-bot-build` (BOT_TOKEN, MANAGER_CHAT_ID, LLM_PROVIDER, LLM_API_KEY, модели). Если пишешь сам, не печатай значения в чат.

### 9. Проверка региона и прокси

Перед запуском проверь, достает ли сервер до выбранного провайдера LLM:

```bash
curl -sI https://api.anthropic.com | head -1
curl -sI https://api.deepseek.com | head -1
curl -sI https://api.openai.com | head -1
curl -sI https://api.telegram.org | head -1
```

Ответ HTTP любого кода (200, 401, 404) значит, что дорога открыта. Если видишь 403 с текстом о стране, таймаут или обрыв, это геоблок или сеть. Решение: другой регион сервера, либо прокси. Прокси задается в `.env`:

```
LLM_PROXY=http://<proxy-host>:<port>
```

Поддерживаются http(s) и socks. Прокси человек покупает или поднимает сам, это платное, спроси согласие.

### 10. Сервис systemd --user с автозапуском

Объясни: "Сделаем так, чтобы бот сам запускался при перезагрузке сервера и поднимался после сбоя."

```bash
mkdir -p ~/.config/systemd/user
cp ~/intake-bot/deploy/intake-bot.service ~/.config/systemd/user/intake-bot.service
sudo loginctl enable-linger <user>
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user daemon-reload
systemctl --user enable --now intake-bot
```

Юнит лежит в `template/deploy/intake-bot.service` (папка бота `~/intake-bot`, venv в `~/intake-bot/.venv`). Если папка другая, поправь пути в юните. В юните нет `EnvironmentFile`: бот сам читает `.env` из `WorkingDirectory` (systemd-овский `EnvironmentFile` ломается на комментариях в конце строки). Значит `.env` должен лежать в `~/intake-bot/`.

`enable-linger` нужен, чтобы user-сервисы жили без открытой SSH-сессии. `XDG_RUNTIME_DIR` нужен при каждом входе по SSH, когда управляешь сервисом. Добавь строку в `~/.bashrc`:

```bash
echo 'export XDG_RUNTIME_DIR=/run/user/$(id -u)' >> ~/.bashrc
```

### 11. Логи, перезапуск, обновление

```bash
journalctl --user -u intake-bot -n 100 --no-pager      # последние строки
journalctl --user -u intake-bot -f                     # живой поток
systemctl --user status intake-bot
systemctl --user restart intake-bot
```

Обновление кода (с компьютера владельца):

```bash
rsync -av --exclude .venv --exclude .env --exclude '*.db' --exclude output --exclude google_token.json ~/intake-bot/ <user>@<server-ip>:~/intake-bot/
ssh <user>@<server-ip> "export XDG_RUNTIME_DIR=/run/user/\$(id -u); systemctl --user restart intake-bot"
```

Сначала проверь изменение локально, потом выкатывай. Не затирай базу `*.db` и `.env` на сервере.

## Локальный запуск (на своем компьютере)

Для теста сервер не нужен (нет uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`; Python 3.11-3.13 подойдет):

```bash
cd ~/intake-bot
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m intake --console      # терминальный режим
.venv/bin/python -m intake                # настоящий Telegram, пока открыт терминал
```

Минус: бот работает, пока компьютер включен и терминал открыт. Для постоянной работы нужен сервер.

## Проверка

- `ssh <user>@<server-ip> whoami` возвращает имя пользователя без пароля.
- `ls -l ~/intake-bot/.env` показывает права `-rw-------`.
- `systemctl --user is-active intake-bot` отвечает `active`.
- `journalctl --user -u intake-bot -n 30` без трейсбэков, есть строка о запуске.
- Перезагрузи сервер (спроси согласие): `sudo reboot`, через минуту `systemctl --user is-active intake-bot` снова `active`.
- Написать боту в Telegram `/start` и получить приветствие.

## Подводные камни

- Слабый VPS: ничего тяжелого. Не ставь локальные модели, браузеры, базы данных. Бот должен занимать порядка сотни мегабайт.
- Не отключай вход по паролю, пока ключ не проверен в отдельной сессии.
- Без `loginctl enable-linger` сервис умирает при выходе из SSH.
- Без `XDG_RUNTIME_DIR` команда `systemctl --user` отвечает "Failed to connect to bus".
- Геоблок: у ряда провайдеров LLM нельзя обращаться из некоторых стран. Проверь `curl` до запуска, а не после.
- Подписочные OAuth-токены провайдеров LLM могут быть запрещены в сторонних приложениях. Используй официальные API-ключи.
- Не копируй `.env` в git и не пересылай по мессенджерам.
- Если сервер используется для чего-то еще, спроси владельца, чтобы не сломать чужое.

## Дальше

- Данные в Google или чужой системе: `intake-data-integration`.
- Документы: `intake-documents`.
- Тесты в Telegram и запуск: `intake-testing-launch`.
