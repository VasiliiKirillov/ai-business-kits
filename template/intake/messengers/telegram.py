"""Адаптер Telegram (aiogram, long polling). Токен и группа менеджеров - из env."""
import os
import shutil
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import db, media
from ..core import Core


class Telegram:
    channel = "telegram"

    def __init__(self, core: Core):
        self.core, self.cfg = core, core.cfg
        if not os.getenv("BOT_TOKEN"):
            raise SystemExit("В .env нет BOT_TOKEN: возьми токен у @BotFather и впиши строку BOT_TOKEN=...")
        if not os.getenv("MANAGER_CHAT_ID"):
            print("MANAGER_CHAT_ID пуст: карточки отправлять некуда. Добавь бота в группу менеджера, напиши там /id и впиши число в .env")
        self.bot = Bot(os.environ["BOT_TOKEN"])
        self.manager_chat = int(os.getenv("MANAGER_CHAT_ID") or 0)
        self.file_ids: dict[str, str] = {}   # путь фото -> file_id
        self.editing: dict[int, int] = {}    # id менеджера -> id заявки (ответ "сам")
        self.dp = Dispatcher()
        self._routes()

    # --- интерфейс Messenger
    async def send_client(self, client_id, text):
        await self.bot.send_message(int(client_id), text)

    async def send_client_photo(self, client_id, path, caption):
        """Первый раз грузим файл, дальше шлем по закешированному file_id."""
        fid = self.file_ids.get(path)
        msg = await self.bot.send_photo(int(client_id), fid or FSInputFile(path), caption=caption or None)
        if not fid and msg.photo:
            self.file_ids[path] = msg.photo[-1].file_id

    async def send_card(self, lead_id, text, buttons):
        mg, rows = self.cfg.manager, []
        if "confirm" in buttons:
            rows.append([InlineKeyboardButton(text="✅ " + mg.confirm_button, callback_data=f"confirm:{lead_id}")])
        if "own" in buttons:
            rows.append([InlineKeyboardButton(text="💬 " + mg.own_button, callback_data=f"own:{lead_id}")])
        await self.bot.send_message(self.manager_chat, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    async def notify_manager(self, text):
        await self.bot.send_message(self.manager_chat, text)

    async def send_manager_file(self, path, caption):
        await self.bot.send_document(self.manager_chat, FSInputFile(path), caption=caption)

    async def forward_to_manager(self, client_id, message_ref, caption):
        await self.bot.copy_message(self.manager_chat, int(client_id), int(message_ref), caption=caption)

    # --- обработчики
    def _routes(self):
        dp, mgr = self.dp, F.chat.id == self.manager_chat

        @dp.message(Command("id"))
        async def chat_id(m: Message):
            await m.answer(f"chat id: {m.chat.id}")

        @dp.message(Command("start"), F.chat.type == "private")
        async def start(m: Message):
            self.core.reset(str(m.chat.id))
            await m.answer(self.cfg.bot.greeting)

        @dp.message(mgr, F.text)
        async def manager_text(m: Message):
            lid = self.editing.pop(m.from_user.id, None)
            if lid:
                await self.core.manager_said(self, lid, m.text)
                await m.reply(f"✅ Отправлено клиенту по заявке #{lid}")

        @dp.message(F.chat.type == "private", F.text)
        async def client(m: Message):
            await self.bot.send_chat_action(m.chat.id, "typing")
            await self.core.on_client_message(self, str(m.chat.id), m.from_user.full_name, m.text, m.from_user.username)

        @dp.message(F.chat.type == "private", F.voice | F.audio | F.video_note)
        async def voice(m: Message):
            if not media.stt_enabled():
                return await m.answer(self.cfg.bot.voice_reply)
            await self.bot.send_chat_action(m.chat.id, "typing")
            obj, tmp, text = m.voice or m.audio or m.video_note, tempfile.mkdtemp(prefix="intake_"), None
            try:
                path = str(Path(tmp) / "in.bin")
                await self.bot.download(obj, destination=path)
                text = await media.transcribe(path)
            except Exception:
                text = None
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if not text:
                return await m.answer("голосовое не разобралось, напишите текстом")
            await self.core.on_client_message(self, str(m.chat.id), m.from_user.full_name, text, m.from_user.username)

        @dp.message(F.chat.type == "private", F.photo | (F.document & F.document.mime_type.startswith("image/")))
        async def photo(m: Message):
            await self.bot.send_chat_action(m.chat.id, "typing")
            obj, mt = (m.photo[-1], "image/jpeg") if m.photo else (m.document, m.document.mime_type)
            if mt not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                return await m.answer("такой формат не открывается, пришлите обычное фото, jpg или png")
            buf = await self.bot.download(obj)
            await self.core.on_document(self, str(m.chat.id), m.from_user.full_name, str(m.message_id), buf.read(), mt,
                                        m.from_user.username)

        @dp.callback_query(F.data.regexp(r"^(confirm|own):\d+$"))
        async def buttons(cb: CallbackQuery):
            action, lid = cb.data.split(":")
            lid = int(lid)
            lead = db.get(lid)
            if not lead or lead["status"] not in ("new", "manual"):
                return await cb.answer("Уже обработана")
            if action == "own":
                await cb.message.edit_reply_markup(reply_markup=None)
                self.editing[cb.from_user.id] = lid
                await cb.message.reply(f"💬 {cb.from_user.first_name} отвечает сам. Пришли следующим сообщением текст для клиента (уйдет дословно)")
            else:
                db.set_status(lid, "confirming")  # сразу, чтобы второе нажатие увидело "Уже обработана"
                try:  # убрать кнопки и дописать внизу карточки
                    await cb.message.edit_text(cb.message.text + "\n\n✅ подтверждено", reply_markup=None)
                except Exception:
                    await cb.message.edit_reply_markup(reply_markup=None)
                await self.core.manager_action(self, lid, "confirm")
            await cb.answer()

    async def run(self):
        await self.dp.start_polling(self.bot)
