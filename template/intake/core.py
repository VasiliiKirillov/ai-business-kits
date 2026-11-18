"""Ядро: не знает ни про Telegram, ни про конкретную модель, ни про конкретный бизнес.

Схема: бот сам ведет диалог и собирает заявку (код решает, что сказать, чат только говорит по статусу).
Карточка менеджеру уходит один раз, когда клиент подтвердил итог.
"""
import asyncio
import json
import logging
import time
from typing import Optional

from . import booking as bk
from . import chat, cards, db, media, photos, pricing
from .catalog import Catalog
from .config import Config
from .data import get_source
from .documents import get_engine
from .llm import get_provider, get_vision
from .messengers.base import Messenger
from .parser import parse
from .schema import build_lead_model

log = logging.getLogger("intake")
HISTORY_SEC = 2 * 3600
DOC_ASK = {"full_name": "имя и фамилия как в документе", "number": "номер", "nationality": "гражданство",
           "birth_date": "дата рождения"}


def new_state() -> dict:
    return {"fields": {}, "phase": "collect", "lid": None, "kind": None, "summary": None, "convo": [], "turn": 0,
            "open_q": None, "ts": time.time(), "avail_key": None, "unit": None, "photo_doc": None, "docs": [],
            "photos_sent": set(), "explained": set(), "skipped": set()}


class Core:
    def __init__(self, cfg: Config, provider=None, source=None, engine=None, vision=None):
        self.cfg = cfg
        self.provider = provider or get_provider(cfg=cfg)
        self.vision = vision or get_vision(self.provider)
        self.source = source or get_source(cfg)
        self.engine = engine or get_engine(cfg)
        self.catalog = Catalog(cfg)
        self.Lead = build_lead_model(cfg)
        self.ik = cfg.item_key
        self.idc = cfg.request.identity_document
        self.idf = list(self.idc.fields) if self.idc.enabled else []
        self.history: dict[str, list] = {}   # client_id -> [(время, client|bot, текст)] за 2 часа, для чата
        self.state: dict[str, dict] = {}     # client_id -> состояние заявки

    # ------------------------------------------------------------------ состояние
    def _hist(self, client_id: str) -> list:
        h = [x for x in self.history.get(client_id, []) if time.time() - x[0] < HISTORY_SEC]
        self.history[client_id] = h
        return h

    def _st(self, client_id: str) -> dict:
        st = self.state.get(client_id)
        if not st or time.time() - st["ts"] > HISTORY_SEC:
            st = self.state[client_id] = new_state()
        st["ts"] = time.time()
        return st

    def _restart_if_done(self, st: dict):
        if st["phase"] == "done":  # прошлая заявка закрыта, начинаем заново
            st.clear()
            st.update(new_state())

    def reset(self, client_id: str):
        """/start: чистый лист. Открытую карточку закрываем."""
        st = self.state.pop(client_id, None)
        if st and st.get("lid"):
            row = db.get(st["lid"])
            if row and row["status"] in ("new", "manual"):
                db.set_status(st["lid"], "closed")
        self.history.pop(client_id, None)
        if hasattr(self.provider, "reset"):
            self.provider.reset()

    # ------------------------------------------------------------------ речь
    def _remember(self, client_id, text, role="bot"):
        self.history.setdefault(client_id, []).append((time.time(), role, text))
        if client_id in self.state and role == "bot":
            self.state[client_id]["convo"].append(("Бот", text))
            self.state[client_id]["turn"] += 1

    async def _say(self, m, client_id, text):
        if not text:
            return
        self._remember(client_id, text)
        db.log_msg(client_id, "bot", text)
        await m.send_client(client_id, text)

    async def _say_photo(self, m, client_id, path, caption, qstatus=None):
        """Подпись собирает код; следующий вопрос - от чата. Отправка упала - не роняем бота."""
        if qstatus:
            q = await self._chat(client_id, "Задай только вопрос, без описаний и без цен. " + qstatus)
            if q:
                caption = f"{caption} {q}"
        self._remember(client_id, caption)
        db.log_msg(client_id, "bot", f"[фото {path.name}] {caption}")
        try:
            await m.send_client_photo(client_id, str(path), caption)
        except Exception as e:
            log.warning("send photo failed: %s", e)
            await m.send_client(client_id, caption)

    async def _chat(self, client_id, status) -> Optional[str]:
        try:
            return await chat.reply(self.provider, self.cfg, self.catalog, [(r, t) for _, r, t in self._hist(client_id)], status)
        except Exception as e:
            log.warning("chat failed: %s", e)
            return None

    async def _safe(self, coro, what: str):
        """Сообщение менеджеру не должно ронять бота."""
        try:
            await coro
        except Exception as e:
            log.warning("%s failed: %s", what, e)

    def _client_tail(self, client_id) -> str:
        return "\n".join(t for _, r, t in self._hist(client_id) if r == "client")[-600:]

    async def _flush_docs(self, m, client_id, st):
        """Фото документов, накопленные до карточки, уходят в группу прямо перед ней."""
        docs, st["docs"] = st.get("docs") or [], []
        for ref, cap in docs:
            await m.forward_to_manager(client_id, ref, cap)

    # ------------------------------------------------------------------ сообщения клиента
    async def on_client_message(self, m: Messenger, client_id: str, client_name: str, text: str, username: Optional[str] = None):
        cfg, ik = self.cfg, self.ik
        self._hist(client_id).append((time.time(), "client", text))
        db.log_msg(client_id, "client", text)
        st = self._st(client_id)
        self._restart_if_done(st)
        st["convo"].append(("Клиент", text))
        try:
            self.catalog.set_items(await asyncio.to_thread(self.source.catalog))
        except Exception as e:
            log.warning("catalog refresh failed: %s", e)
        transcript = "\n".join(f"{r}: {t}" for r, t in st["convo"])
        who = client_name + (f", @{username}" if username else "")
        res = await parse(self.provider, cfg, self.catalog, transcript, who, awaiting_confirm=st["phase"] == "confirm", model=self.Lead)
        lead, sec, pname = res["lead"], res["seconds"], self.provider.name
        log.info("lead from %s via %s: %.1fs ok=%s phase=%s", client_id, pname, sec, lead is not None, st["phase"])

        if lead is None:  # модель дважды не смогла - человеку
            if st["phase"] == "carded":
                await m.notify_manager(f"💬 #{st['lid']} {client_name}: {text}")
                return await self._say(m, client_id, await self._chat(client_id, "Менеджер уже получил заявку. Просто ответь на сообщение клиента"))
            lid = db.add(m.channel, client_id, client_name, text, pname, {}, "manual")
            await self._flush_docs(m, client_id, st)
            await m.send_card(lid, f"⚠️ #{lid} от {client_name}: не удалось разобрать, ответь сам\n\n{text}", ["own"])
            st.update(phase="carded", lid=lid, kind="complaint")
            return await self._say(m, client_id, await self._chat(client_id, "Скажи, что передал старшему, он свяжется"))

        contact = lead.contact or (f"@{username}" if username else None)

        # тип определяется по первому сообщению диалога; внутри заявки это всегда request
        if st["kind"] is None:
            typ = lead.type
            if typ != "spam":
                st["kind"] = typ
        elif st["kind"] == "request":
            typ = "request"
        elif st["kind"] == "question":
            typ = lead.type if lead.type in ("request", "complaint") else "question"
            if typ == "request":
                st["kind"] = "request"
        else:
            typ = st["kind"]

        if typ == "spam":  # молча, только запись
            db.add(m.channel, client_id, client_name, text, pname, lead.model_dump(), "spam")
            return

        if typ == "complaint":
            if st["phase"] == "carded":
                await m.notify_manager(f"💬 #{st['lid']} {client_name}: {text}")
                status = "Менеджер уже в курсе и свяжется. Просто ответь на сообщение клиента"
            else:
                lid = db.add(m.channel, client_id, client_name, text, pname, lead.model_dump(), "new")
                await self._flush_docs(m, client_id, st)
                await m.send_card(lid, cards.complaint_card(lid, client_name, contact, self._client_tail(client_id), pname, sec), ["own"])
                st.update(phase="carded", lid=lid, kind="complaint")
                status = "Скажи коротко, что передал менеджеру, он свяжется"
            return await self._say(m, client_id, await self._chat(client_id, status))

        if typ == "question":  # вопрос вне заявки: бот отвечает сам, карточки нет
            if await self._photo_request(m, client_id, st, lead, st["fields"]):
                return
            return await self._say(m, client_id, await self._chat(
                client_id, "Это вопрос, ответь по существу. Можно спросить, что нужно клиенту"))

        # --- заявка: полное состояние из парсера, без слияния
        old = st["fields"]
        f = self._build_fields(lead, st)
        st["fields"] = f
        changed = [k for k in cfg.keys if k in f and not same(f[k], old.get(k), k == ik)]

        if await self._photo_request(m, client_id, st, lead, f):
            return

        if st["phase"] == "carded":  # карточка уже у менеджера
            line = f"💬 #{st['lid']} {client_name}: {text}"
            status = "Менеджер уже получил заявку и проверяет. Просто ответь на сообщение клиента"
            if changed and not self._missing(f):
                line += "\nобновлено: " + ", ".join(f"{k} {old.get(k)} -> {f[k]}" for k in changed)
                status += ". Клиент поменял детали, они переданы менеджеру"
                db.update_data(st["lid"], {**self._lead_data(st, f, contact, client_name), "summary": self._summary(f)})
            await m.notify_manager(line)
            return await self._say(m, client_id, await self._chat(client_id, status))

        busy = await self._check_availability(client_id, st, f)
        if busy:
            return await self._say(m, client_id, await self._chat(client_id, busy))

        if st["phase"] == "confirm" and lead.confirmed and not self._missing(f):
            summ = self._summary(f)
            data = {**self._lead_data(st, f, contact, client_name), "summary": summ}
            lid = db.add(m.channel, client_id, client_name, self._client_tail(client_id), pname, data, "new")
            await self._flush_docs(m, client_id, st)  # фото документов - в группу прямо перед карточкой
            await m.send_card(lid, cards.booking_card(cfg, lid, client_name, f, contact, self._item_line(st, f),
                                                      self._price_line(f), pname, sec, self._value), ["confirm", "own"])
            st.update(phase="carded", lid=lid, summary=summ)
            return await self._say(m, client_id, await self._chat(client_id, f"Клиент подтвердил итог. Скажи коротко: {cfg.manager.handoff_text}"))

        dk = lead.declined_field
        fld = next((x for x in cfg.request.fields if x.key == dk and x.declinable), None)
        if fld and not f.get(fld.key):
            if fld.key not in st["explained"]:  # один раз объясняем, не давим
                st["explained"].add(fld.key)
                st.update(phase="collect", open_q=(fld.key, st["turn"] + 1))
                return await self._say(m, client_id, await self._chat(
                    client_id, f"Клиент не хочет давать: {fld.label}. Один раз мягко объясни: {fld.decline_reason}. Не дави, вопрос не повторяй"))
            st["skipped"].add(fld.key)  # отказался второй раз: идем дальше, значение "-"
            f[fld.key] = "-"

        missing = self._missing(f)
        if missing:
            st["phase"] = "collect"
            item = self.catalog.named(f.get(ik) or "") if ik and ik in changed else None
            if item and photos.find(item.name) and photos.key(item.name) not in st["photos_sent"]:  # выбрал позицию: фото один раз
                st["photos_sent"].add(photos.key(item.name))
                picked = bool(st.get("open_q") and st["open_q"][0] == ik)  # выбрал из альтернатив: вопрос будет в следующей реплике
                if picked:
                    st["open_q"] = None
                return await self._say_photo(m, client_id, photos.find(item.name), *self._photo_status(st, f, item, allow_q=not picked))
            status = self._ask_status(st, missing)
            if ik and ik in changed and f.get(ik) and (ps := pricing.price_status(cfg, self.catalog, f[ik], f)):
                # цена сразу после названной позиции; следующий вопрос - только если open_q его разрешает
                status = ps + (". " + status if status.startswith(("Спроси", "Вернись")) else ". Больше ничего не спрашивай")
            return await self._say(m, client_id, await self._chat(client_id, status))

        summ = self._summary(f)
        if st["phase"] == "confirm" and not changed:  # вопрос по ходу, подтверждения нет
            status = f"Клиент еще не подтвердил итог: {summ}. Ответь на его сообщение и спроси, все ли верно"
        else:
            status = f"Все собрано, покажи клиенту итог списком и спроси, все ли верно: {summ}"
        st.update(phase="confirm", summary=summ)
        await self._say(m, client_id, await self._chat(client_id, status))

    # ------------------------------------------------------------------ помощники
    def _build_fields(self, lead, st) -> dict:
        d, f = lead.model_dump(), {}
        for fld in self.cfg.request.fields:
            v = d.get(fld.key)
            if v in (None, ""):
                if fld.ask_only_if_unclear and d.get(fld.key + "_unclear"):
                    f[fld.key + "_unclear"] = True   # значение останется пустым -> спросим
                elif fld.default is not None:
                    f[fld.key] = fld.default
                continue
            if fld.type == "date" and (dt := bk.parse_dt(v)) and dt.date() < bk.today(self.cfg):
                continue  # дата в прошлом: не принимаем, бот спросит снова
            f[fld.key] = v
        for k in st["skipped"]:
            if not f.get(k):
                f[k] = "-"
        if self.idf:
            doc = {k: d.get("doc_" + k) for k in self.idf}
            doc.update({k: v for k, v in (st.get("photo_doc") or {}).items() if v and k in self.idf})  # фото надежнее текста
            f["doc"] = doc
        return f

    def _lead_data(self, st, f, contact, name) -> dict:
        return {"fields": f, "contact": contact, "name": name, "unit": st.get("unit")}

    def _missing(self, f: dict) -> list:
        out = [x.key for x in self.cfg.request.fields if f.get(x.key) in (None, "")]
        if self.idf and any(not (f.get("doc") or {}).get(k) for k in self.idf):
            out.append("doc")
        return out

    def _ask_text(self, st, k) -> str:
        if k != "doc":
            return self.cfg.field(k).ask
        doc = st["fields"].get("doc") or {}
        miss = [DOC_ASK[x] for x in self.idf if not doc.get(x)]
        n, reason = self.idc.name, (f", {self.idc.reason}" if self.idc.reason else "")
        if len(miss) == len(self.idf):
            how = f"фото документа ({n}) или данные текстом" if self.idc.accept_photo else "данные документа текстом"
            return f"{how} ({', '.join(miss)}){reason}"
        return "недостающие данные документа: " + ", ".join(miss)

    def _ask_status(self, st: dict, missing: list) -> str:
        """Один открытый вопрос за раз. Проигнорировали - 2 реплики ничего не спрашиваем, на 3-й возвращаемся другими словами."""
        nxt = st["turn"] + 1  # номер реплики, которую бот сейчас скажет
        oq = st.get("open_q")
        if oq and oq[0] not in missing:  # клиент ответил, вопрос закрыт
            oq = st["open_q"] = None
        if oq:
            if nxt - oq[1] >= 3:
                st["open_q"] = (oq[0], nxt)
                return (f"Вернись к вопросу ({self._ask_text(st, oq[0])}), по-свойски и другими словами. "
                        "Только это, одним вопросом")
            return "Ничего не спрашивай, просто ответь на то, что сказал клиент"
        st["open_q"] = (missing[0], nxt)
        return f"Спроси {self._ask_text(st, missing[0])}. Только это, одним вопросом"

    def _item(self, f):
        return self.catalog.named(f.get(self.ik) or "") if self.ik else None

    def _value(self, fld, v) -> str:
        if fld.type == "date":
            return bk.fmt_date(v)
        if fld.key == self.cfg.pricing.duration_field and pricing.duration(self.cfg, {fld.key: v}):
            return f"{v} {pricing.dur_word(self.cfg, v)}"
        return str(v)

    def _summary(self, f: dict) -> str:
        """Итог для клиента: код собирает точную цену, чат только оформляет."""
        parts, qk = [], self.cfg.pricing.quantity_field
        for fld in self.cfg.request.fields:
            v = f.get(fld.key)
            if v in (None, "", "-") or fld.type == "phone" or (fld.key == qk and str(v) == "1"):
                continue
            parts.append(f"{fld.label}: {self._value(fld, v)}")
        parts.append(self._price_line(f, short=True))
        ph = bk.phone_of(self.cfg, f)
        if ph:
            parts.append(f"тел: {ph}")
        doc = f.get("doc") or {}
        if doc.get("full_name") and doc.get("number"):
            parts.append(f"{self.idc.name}: {doc['full_name']} {doc['number']}")
        return "; ".join(parts)

    def _price_line(self, f, short=False) -> str:
        c = pricing.calc(self.cfg, self._item(f), f)
        if not c:
            return "цену подтвердит менеджер"
        return (f"итого {c['total']} {self.cfg.business.currency}" + (f" (скидка {c['discount']:g}%)" if c["discount"] else "")) if short else c["formula"]

    def _item_line(self, st, f) -> str:
        return f"{self.cfg.request.item_noun}: {st.get('unit') or f.get(self.ik) or '-'}"

    def _photo_status(self, st, f, item, allow_q=True):
        """-> (подпись, статус для вопроса или None)"""
        cap = f"{item.name}: {pricing.price_phrase(self.cfg, item, f)}." if item.price is not None else f"{item.name}."
        missing = self._missing(f) if st["phase"] != "carded" else []
        if allow_q and missing:
            ask = self._ask_status(st, missing)
            if ask.startswith(("Спроси", "Вернись")):
                return cap, ask
        return cap, None

    async def _photo_request(self, m, client_id, st, lead, f) -> bool:
        """Клиент сам просит фото. True - ответили."""
        if not lead.wants_photo:
            return False
        item = self.catalog.named(lead.photo_of or "") or self._item(f)
        if not item:
            await self._say(m, client_id, await self._chat(client_id, "Клиент просит фото, но не ясно чего. Спроси, фото чего скинуть"))
            return True
        path = photos.find(item.name)
        if not path:
            await self._say(m, client_id, await self._chat(client_id, f"Фото {item.name} сейчас нет. Скажи это коротко, больше ничего не обещай"))
            return True
        st["photos_sent"].add(photos.key(item.name))
        await self._say_photo(m, client_id, path, *self._photo_status(st, f, item))
        return True

    # ------------------------------------------------------------------ наличие
    def _req(self, f: dict) -> dict:
        return {k: v for k, v in f.items() if k != "doc"}

    async def _check_availability(self, client_id, st, f) -> Optional[str]:
        """Занято -> убираем поле, пишем в переписку строку от менеджера, возвращаем статус для чата. Иначе None."""
        a, ik = self.cfg.availability, self.ik
        if a.mode == "none" or not f.get(ik) or not f.get(a.date_field):
            return None
        need = a.duration_field if a.mode == "days" else a.time_field
        if not f.get(need):
            return None
        qk = self.cfg.pricing.quantity_field
        key = tuple(f.get(k) for k in (ik, a.date_field, need, qk) if k)
        if st.get("avail_key") == key:
            return None
        try:
            av = await asyncio.to_thread(self.source.check_availability, self._req(f))
        except Exception as e:
            log.warning("availability check failed: %s", e)
            av = None
        if av is None or av.ok:
            st["avail_key"] = key
            if av:
                st["unit"] = av.unit
            return None
        old = f.pop(av.drop_key, None)
        st.update(avail_key=None, unit=None, phase="collect")
        st["convo"].append(("Менеджер", av.busy_text))
        st["open_q"] = (av.drop_key, st["turn"] + 1)
        what = f"{old}" if av.drop_key == ik else av.busy_text
        if av.drop_key == ik:
            head = f"{what} занят(а) на эти даты (скажи именно так, без извинений)"
            none = "и подходящих вариантов тоже нет. Скажи это (без извинений) и предложи другие даты"
            free = "Свободны"
        else:
            head = f"{what} (скажи именно так, без извинений)"
            none = "и свободного времени в этот день нет. Скажи это (без извинений) и предложи другой день"
            free = "Свободное время"
        if av.alternatives:
            return f"{head}. {free}: {'; '.join(av.alternatives)}. Просто назови это фактом, без вопроса в конце: клиент ответит сам"
        return f"{head}, {none}"

    # ------------------------------------------------------------------ документы клиента
    async def on_document(self, m: Messenger, client_id: str, client_name: str, message_ref: str, image: bytes,
                          media_type: str, username: Optional[str] = None):
        cfg = self.cfg
        st = self.state.get(client_id)
        lid = st["lid"] if st and st["phase"] == "carded" else None

        async def forward(cap):
            if lid:  # карточка уже у менеджера - фото сразу
                await m.forward_to_manager(client_id, message_ref, cap)
            else:  # копим до карточки
                cur = self._st(client_id)
                self._restart_if_done(cur)
                cur["docs"].append((message_ref, cap))

        if not (self.idc.enabled and self.idc.accept_photo):
            await forward(f"📎 {'#' + str(lid) + ' ' if lid else ''}{client_name}: фото")
            status = (f"Заявка #{lid} уже у менеджера, просто ответь про фото" if lid else
                      "Клиент прислал фото. Ответь по контексту и, если идет оформление, продолжи по статусу сбора заявки")
            if self.idc.enabled:
                status = f"Клиент прислал фото, но данные документа ({self.idc.name}) нужны текстом. Попроси написать их"
            return await self._say(m, client_id, await self._chat(client_id, status))

        doc = await media.read_doc(self.vision, cfg, image, media_type)
        r = media.check(cfg, doc)
        log.info("document from %s: kind=%s ok=%s", client_id, r["kind"], r["ok"])
        await forward(media.caption(cfg, doc, r, client_name, lid))
        line = media.history_line(cfg, doc, r)
        st = self._st(client_id)
        if r["kind"] == "id_document" and r["ok"]:  # данные документа идут в обычный разбор диалога
            st["photo_doc"] = media.fields(doc)
            return await self.on_client_message(m, client_id, client_name, line, username)
        self._hist(client_id).append((time.time(), "client", line))
        db.log_msg(client_id, "client", line)
        if st["kind"] == "request" and st["phase"] != "carded" and any(not (st["fields"].get("doc") or {}).get(k) for k in self.idf):
            st["open_q"] = ("doc", st["turn"] + 1)
            return await self._say(m, client_id, await self._chat(
                client_id, f"Это не {self.idc.name} (или не читается). Попроси именно его: фото или данные текстом"))
        status = (f"Заявка #{lid} уже у менеджера, просто ответь про документ" if lid
                  else "Ответь про документ и, если идет оформление, продолжи по статусу сбора заявки")
        await self._say(m, client_id, await self._chat(client_id, status))

    # ------------------------------------------------------------------ действия менеджера
    async def manager_action(self, m: Messenger, lid: int, action: str = "confirm"):
        """Единственное действие менеджера по заявке - подтвердить."""
        row = db.get(lid)
        client_id = row["client_id"]
        st = self._st(client_id)
        data = json.loads(row["data"] or "{}")
        summ = data.get("summary") or st.get("summary") or ""
        db.set_status(lid, "confirming")  # защита от двойного нажатия
        if await self._finalize(m, lid, data) == "busy":
            return await self._busy(m, lid, client_id, st, data)
        db.set_status(lid, "confirmed")
        st.update(phase="done", lid=None)
        if not self._hist(client_id):  # после рестарта бота истории нет, чату нужна хотя бы одна реплика клиента
            self._hist(client_id).append((time.time(), "client", "что с моей заявкой?"))
        status = f"{self.cfg.manager.after_confirm_client}: {summ}"
        await self._say(m, client_id, await self._chat(client_id, status))

    async def _busy(self, m, lid, client_id, st, data):
        """При подтверждении позиция/время оказались заняты: сообщаем клиенту, сбор продолжается."""
        a, ik = self.cfg.availability, self.ik
        key = ik if a.mode == "days" else a.time_field
        old = st["fields"].pop(key, None) or (data.get("fields") or {}).get(key)
        if st.get("open_q") and st["open_q"][0] == key:
            st["open_q"] = None
        db.set_status(lid, "no_stock")
        st.update(phase="collect", lid=None, summary=None, avail_key=None, unit=None)
        st["convo"].append(("Менеджер", f"{old} нет в наличии" if key == ik else f"время {old} занято"))
        if not self._hist(client_id):
            self._hist(client_id).append((time.time(), "client", "что с моей заявкой?"))
        status = (f"Пока подтверждали, это уже занято: {old}. Скажи коротко, что занято (не просто нет), без извинений, "
                  "и предложи подобрать другое, фактом, без вопроса про то, подойдет ли")
        await self._say(m, client_id, await self._chat(client_id, status))

    async def _finalize(self, m: Messenger, lid: int, data: dict):
        """Подтверждение: перепроверка наличия, документ, запись брони. 'busy' - занято. Ошибки не роняют бота."""
        a, ik = self.cfg.availability, self.ik
        f = data.get("fields") or {}
        unit = data.get("unit")
        if a.mode != "none" and ik and f.get(ik):
            try:
                unit = await asyncio.to_thread(self.source.reserve, self._req(f))
            except Exception as e:
                log.exception("reserve failed")
                await self._safe(m.notify_manager(f"не смог перепроверить занятость: {type(e).__name__}: {str(e)[:150]}"), "notify")
                unit = data.get("unit")
            else:
                if unit is None:
                    await self._safe(m.notify_manager(f"⛔ #{lid}: {f.get(ik)} уже занято, заявку не подтверждаю"), "notify")
                    return "busy"
        try:
            bid = await asyncio.to_thread(self.source.next_booking_id)
            b = bk.build(self.cfg, self.catalog, data, bid, unit)
            res = {}
            try:
                res = await asyncio.to_thread(self.engine.render, b)
            except Exception as e:
                log.exception("document failed")
                await self._safe(m.notify_manager(f"не смог сделать документ: {type(e).__name__}: {str(e)[:150]}"), "notify")
            b["document"] = res.get("url") or res.get("path") or ""
            await asyncio.to_thread(self.source.save_booking, b)
        except Exception as e:
            log.exception("booking failed")
            await self._safe(m.notify_manager(f"не смог записать бронь: {type(e).__name__}: {str(e)[:150]}"), "notify")
            return None
        note = f"✅ #{lid}: {self.cfg.request.noun} {bid} записана"
        if res.get("url"):
            note += f"\n📄 {res['url']}"
        await self._safe(m.notify_manager(note), "notify")
        if res.get("path"):
            await self._safe(m.send_manager_file(res["path"], f"📄 {bid}"), "send file")
        return b

    async def manager_said(self, m: Messenger, lid: int, text: str):
        """Менеджер ответил сам: текст уходит клиенту дословно."""
        row = db.get(lid)
        client_id = row["client_id"]
        self.history.setdefault(client_id, []).append((time.time(), "bot", text))
        db.log_msg(client_id, "manager", text)
        db.set_status(lid, "answered")
        self.state.pop(client_id, None)
        await m.send_client(client_id, text)


def same(a, b, is_item: bool = False) -> bool:
    """Одно и то же значение с поправкой на разный вывод модели (регистр, 'PCX' / 'Honda PCX 160')."""
    if a is None or b is None:
        return a is b
    if isinstance(a, str) and isinstance(b, str):
        a, b = a.lower().strip(), b.lower().strip()
        return a == b or (is_item and (a in b or b in a))
    return a == b
