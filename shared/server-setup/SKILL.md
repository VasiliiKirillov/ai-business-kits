---
name: server-setup
description: "Поднять VPS под любую автоматизацию из репозитория: SSH-ключи, отдельный пользователь, Python и uv, systemd --user с автозапуском, логи; используй, когда кит должен работать круглосуточно."
---

# Сервер: VPS, SSH, systemd

Общий скилл для любого кита. Подставь свои значения вместо плейсхолдеров:

- `<app-dir>` - рабочая папка кита на сервере (для `intake-bot` это `~/intake-bot`);
- `<service>` - имя systemd-юнита (для `intake-bot` это `intake-bot`);
- `<user>` и `<server-ip>` - обычный пользователь и адрес сервера.

Конкретные имена, команды запуска и зависимости смотри в папке своего кита (`AGENTS.md` кита).

## Когда использовать

Когда кит уже запускается локально и его нужно перенести туда, где он работает 24/7. Либо когда владелец просит "сначала на своем компьютере": тогда используй раздел "Локальный запуск" и вернись сюда позже.

## Что нужно от человека

- Решение, где держать кит: VPS или свой компьютер (для теста).
- Если VPS: аккаунт у хостинг-провайдера и готовность заплатить (порядка 5 долларов в месяц). Покупку делает человек сам, ты только говоришь, что выбрать.
- Доступ к серверу: IP-адрес и пароль root (или уже добавленный ключ) от провайдера. Пароль человек вводит сам при первом входе, в чат его лучше не писать.

## Шаги

Перед каждым шагом объясни человеку, что делаешь и зачем, одной-двумя фразами. Перед платным и необратимым (покупка сервера, отключение пароля) спроси явное согласие.

### 1. Выбор VPS

Скажи человеку, на что смотреть:

- 1 vCPU, 1 ГБ памяти, 10 ГБ диска: этого хватает.
- Ubuntu 24.04 LTS.
- Регион: такой, где провайдеры LLM не блокируют обращения (у многих API блокировка по стране). Если сомневаешься, выбери регион в Европе или США, либо заранее планируй прокси.
- Не селись на сервер, где уже работают важные вещи при малой памяти: кит не тяжелый, но вы можете уронить соседей.
- Оплата и покупка на стороне человека. После покупки провайдер выдаст IP и пароль root.

### 2. SSH-ключ на компьютере владельца

Объясни: "Ключ это как цифровой ключ от двери сервера, надежнее пароля."

```bash
ls ~/.ssh/id_ed25519.pub 2>/dev/null || ssh-keygen -t ed25519 -C "kits" -f ~/.ssh/id_ed25519 -N ""
ssh-copy-id root@<server-ip>
```

Пароль root человек вводит сам. Если `ssh-copy-id` нет (Windows), покажи содержимое `~/.ssh/id_ed25519.pub` и попроси добавить его в панели провайдера или в файл `~/.ssh/authorized_keys` на сервере.

### 3. Первый вход и отдельный пользователь

Объясни: "Работать под root небезопасно, создадим обычного пользователя."

```bash
ssh root@<server-ip>
adduser --disabled-password --gecos "" <user>
usermod -aG sudo <user>
mkdir -p ~<user>/.ssh && cp ~/.ssh/authorized_keys ~<user>/.ssh/
chown -R <user>:<user> ~<user>/.ssh && chmod 700 ~<user>/.ssh && chmod 600 ~<user>/.ssh/authorized_keys
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

### 6. Копирование кита на сервер

С компьютера владельца (из папки кита на компьютере):

```bash
rsync -av --exclude .venv --exclude .env --exclude '*.db' --exclude output --exclude google_token.json <app-dir>/ <user>@<server-ip>:<app-dir>/
```

Или `git clone`, если кит лежит в приватном репозитории. `.env` и токены не копируй через git.

### 7. Виртуальное окружение и зависимости

```bash
ssh <user>@<server-ip>
cd <app-dir>
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
# если данные в Google:
uv pip install --python .venv/bin/python -r requirements-google.txt
```

### 8. Файл .env

Объясни: "В этом файле лежат пароли и ключи. Он виден только вам."

Лучше, чтобы человек сам вписал значения:

```bash
cp .env.example .env && chmod 600 .env
nano .env
```

Список переменных смотри в `.env.example` кита (для `intake-bot` см. `intake-bot/skills/intake-bot-build/SKILL.md`). Ключи моделей и выбор провайдера: `../llm-providers/SKILL.md`. Если пишешь сам, не печатай значения в чат.

### 9. Проверка региона и прокси

Если кит ходит к LLM-провайдеру, проверь с сервера доступ к его API и при необходимости настрой прокси: см. `../llm-providers/SKILL.md` (разделы про геоблок и прокси). Проверь заодно, что сервер достает до сервисов, которые нужны киту (например `curl -sI https://api.telegram.org | head -1`). Любой HTTP-ответ (200, 401, 404) значит, что дорога открыта.

### 10. Сервис systemd --user с автозапуском

Объясни: "Сделаем так, чтобы сервис сам запускался при перезагрузке сервера и поднимался после сбоя."

```bash
mkdir -p ~/.config/systemd/user
cp <app-dir>/deploy/<service>.service ~/.config/systemd/user/<service>.service
sudo loginctl enable-linger <user>
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user daemon-reload
systemctl --user enable --now <service>
```

Юнит лежит в папке кита (для `intake-bot`: `intake-bot/template/deploy/intake-bot.service`; папка на сервере `<app-dir>`, venv в `<app-dir>/.venv`). Если папка другая, поправь пути в юните. В юните нет `EnvironmentFile`: приложение само читает `.env` из `WorkingDirectory` (systemd-овский `EnvironmentFile` ломается на комментариях в конце строки). Значит `.env` должен лежать в `<app-dir>/`.

`enable-linger` нужен, чтобы user-сервисы жили без открытой SSH-сессии. `XDG_RUNTIME_DIR` нужен при каждом входе по SSH, когда управляешь сервисом. Добавь строку в `~/.bashrc`:

```bash
echo 'export XDG_RUNTIME_DIR=/run/user/$(id -u)' >> ~/.bashrc
```

### 11. Логи, перезапуск, обновление

```bash
journalctl --user -u <service> -n 100 --no-pager      # последние строки
journalctl --user -u <service> -f                     # живой поток
systemctl --user status <service>
systemctl --user restart <service>
```

Обновление кода (с компьютера владельца):

```bash
rsync -av --exclude .venv --exclude .env --exclude '*.db' --exclude output --exclude google_token.json <app-dir>/ <user>@<server-ip>:<app-dir>/
ssh <user>@<server-ip> "export XDG_RUNTIME_DIR=/run/user/\$(id -u); systemctl --user restart <service>"
```

Сначала проверь изменение локально, потом выкатывай. Не затирай базу `*.db` и `.env` на сервере.

## Локальный запуск (на своем компьютере)

Для теста сервер не нужен (нет uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`; Python 3.11-3.13 подойдет):

```bash
cd <app-dir>
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
```

Команды запуска смотри в `AGENTS.md` и README своего кита (для `intake-bot`: `.venv/bin/python -m intake --console` и `.venv/bin/python -m intake`).

Минус: все работает, пока компьютер включен и терминал открыт. Для постоянной работы нужен сервер.

## Проверка

- `ssh <user>@<server-ip> whoami` возвращает имя пользователя без пароля.
- `ls -l <app-dir>/.env` показывает права `-rw-------`.
- `systemctl --user is-active <service>` отвечает `active`.
- `journalctl --user -u <service> -n 30` без трейсбэков, есть строка о запуске.
- Перезагрузи сервер (спроси согласие): `sudo reboot`, через минуту `systemctl --user is-active <service>` снова `active`.
- Кит отвечает так, как описано в его README (для `intake-bot`: `/start` в Telegram возвращает приветствие).

## Подводные камни

- Слабый VPS: ничего тяжелого. Не ставь локальные модели, браузеры, базы данных. Типичный кит занимает порядка сотни мегабайт.
- Не отключай вход по паролю, пока ключ не проверен в отдельной сессии.
- Без `loginctl enable-linger` сервис умирает при выходе из SSH.
- Без `XDG_RUNTIME_DIR` команда `systemctl --user` отвечает "Failed to connect to bus".
- Геоблок провайдеров LLM и официальные API-ключи: `../llm-providers/SKILL.md`.
- Не копируй `.env` в git и не пересылай по мессенджерам.
- Если сервер используется для чего-то еще, спроси владельца, чтобы не сломать чужое.

## Дальше

- Данные в Google: `../google-workspace/SKILL.md`.
- Дальнейшие шаги (документы, тесты, запуск) идут по `AGENTS.md` выбранного кита.
