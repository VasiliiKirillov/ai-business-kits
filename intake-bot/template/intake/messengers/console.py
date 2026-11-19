"""Терминальный "мессенджер": вы печатаете за клиента, видите ответы бота и группу менеджеров.

Команды: /confirm - менеджер подтверждает последнюю карточку, /own <текст> - менеджер отвечает сам,
/photo <путь> - клиент шлет фото, /reset - начать заново, /quit - выход.
Запуск: python -m intake --console [--mock]
"""
import asyncio
import mimetypes
import sys
from pathlib import Path

from ..core import Core


class Console:
    channel = "console"

    def __init__(self, core: Core):
        self.core, self.last_lid = core, None

    async def send_client(self, client_id, text):
        print(f"  БОТ: {text}")

    async def send_client_photo(self, client_id, path, caption):
        print(f"  БОТ: [фото {Path(path).name}] {caption}")

    async def send_card(self, lead_id, text, buttons):
        self.last_lid = lead_id
        print(f"  ГРУППА: карточка, кнопки {buttons}")
        print("\n".join("     | " + x for x in text.splitlines()))

    async def notify_manager(self, text):
        print(f"  ГРУППА: {text}")

    async def send_manager_file(self, path, caption):
        print(f"  ГРУППА: [файл {path}] {caption}")

    async def forward_to_manager(self, client_id, message_ref, caption):
        print(f"  ГРУППА: [фото от клиента] {caption}")

    async def run(self):
        loop, cid = asyncio.get_running_loop(), "console-client"
        print(f"{self.core.cfg.bot.greeting}\n(команды: /confirm, /own <текст>, /photo <путь>, /reset, /quit)")
        while True:
            line = (await loop.run_in_executor(None, sys.stdin.readline))
            if not line or line.strip() == "/quit":
                return
            line = line.strip()
            if not line:
                continue
            if line == "/reset":
                self.core.reset(cid)
                print("  (сброшено)")
            elif line == "/confirm" and self.last_lid:
                await self.core.manager_action(self, self.last_lid, "confirm")
            elif line.startswith("/own") and self.last_lid:
                await self.core.manager_said(self, self.last_lid, line[4:].strip())
            elif line.startswith("/photo"):
                p = Path(line[6:].strip())
                if not p.is_file():
                    print("  нет такого файла")
                    continue
                await self.core.on_document(self, cid, "TEST CLIENT", str(p), p.read_bytes(),
                                            mimetypes.guess_type(p.name)[0] or "image/jpeg", "test_client")
            else:
                await self.core.on_client_message(self, cid, "TEST CLIENT", line, "test_client")


async def run_console(core: Core):
    await Console(core).run()


def main():
    from .. import __main__
    __main__.main(["--console"] + sys.argv[1:])


if __name__ == "__main__":
    main()
