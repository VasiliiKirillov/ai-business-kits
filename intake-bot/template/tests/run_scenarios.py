"""python tests/run_scenarios.py [фильтр] [-q]: прогон сценариев tests/scenarios/<конфиг>/*.yaml.

Без ключей и сети: MockProvider вместо нейросети, временная sqlite, временная папка документов.
Каждый шаг сценария: client (+ parse, что "вернул" парсер) | photo | manager: confirm / {own: текст} | seed (брони).
Проверки шага: expect_bot, expect_not_bot, expect_silent, expect_card, expect_buttons, expect_manager,
expect_booking (true или поля), expect_no_booking, expect_document, expect_photo, expect_no_photo,
expect_forward_before_card, expect_fields. Код выхода 1, если что-то упало.
"""
import asyncio
import re
import sys
import tempfile
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from intake import config, db, prompts  # noqa: E402
from intake.catalog import Catalog  # noqa: E402
from intake.core import Core  # noqa: E402
from intake.data.local import LocalSource  # noqa: E402
from intake.documents import get_engine  # noqa: E402
from intake.llm.mock import MockProvider  # noqa: E402

CID = "000000000"


class Fake:
    """Мессенджер-заглушка: пишет все события в список."""
    channel = "fake"

    def __init__(self):
        self.ev = []

    async def send_client(self, cid, text): self.ev.append(("bot", text))
    async def send_client_photo(self, cid, path, cap): self.ev.append(("photo", Path(path).name, cap))
    async def send_card(self, lid, text, buttons): self.ev.append(("card", lid, text, list(buttons)))
    async def notify_manager(self, text): self.ev.append(("mgr", text))
    async def send_manager_file(self, path, cap): self.ev.append(("file", path, cap))
    async def forward_to_manager(self, cid, ref, cap): self.ev.append(("fwd", ref, cap))


def show(ev) -> list[str]:
    out = []
    for e in ev:
        k = e[0]
        if k == "bot": out.append(f"    БОТ: {e[1]}")
        elif k == "photo": out.append(f"    БОТ: [фото {e[1]}] {e[2]}")
        elif k == "card": out += [f"    ГРУППА: карточка #{e[1]}, кнопки {e[3]}"] + [f"       | {x}" for x in e[2].splitlines()]
        elif k == "mgr": out.append(f"    ГРУППА: {e[1]}")
        elif k == "file": out.append(f"    ГРУППА: [файл {Path(e[1]).name}] {e[2]}")
        elif k == "fwd": out.append(f"    ГРУППА: [фото клиента] {e[2]}")
    return out


def bot_text(ev) -> str:
    return "\n".join(e[1] if e[0] == "bot" else e[2] for e in ev if e[0] in ("bot", "photo"))


def seed(cfg, items):
    qk = cfg.pricing.quantity_field or "quantity"
    for s in items:
        db.add_booking({"id": db.next_booking_id(), "item": s["item"], "start": s["start"], "end": s["end"],
                        "client_name": "SEED", "status": s.get("status", "подтверждена"), "fields": {qk: s.get("quantity", 1)}})


def check_docx(path, contains):
    from docx import Document
    d = Document(path)
    parts = [p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells]
    for s in d.sections:
        parts += [p.text for p in s.header.paragraphs + s.footer.paragraphs]
    text = "\n".join(parts)
    errs = []
    if "{{" in text:
        errs.append(f"в документе остались плейсхолдеры: {re.findall(r'[{][{][^}]*[}][}]', text)[:3]}")
    errs += [f"в документе нет '{c}'" for c in contains if c not in text]
    return errs


async def run_step(core, m, mock, cfg, step, state):
    m.ev.clear()
    before = len(db.bookings())
    if "seed" in step:
        seed(cfg, step["seed"])
    elif "client" in step:
        mock.next_parse = step.get("parse")
        await core.on_client_message(m, CID, "TEST CLIENT", step["client"], "test_client")
        print(f"  КЛИЕНТ: {step['client']}")
    elif "photo" in step:
        ph = step["photo"] or {}
        mock.next_doc = ph
        mock.next_parse = None if ph.get("doc_type") == "other" else {k: v for k, v in ph.items() if k != "doc_type"}
        print("  КЛИЕНТ: [фото документа]")
        await core.on_document(m, CID, "TEST CLIENT", "1", b"fake-image", "image/jpeg", "test_client")
    elif "manager" in step:
        v, lid = step["manager"], state.get("lid")
        print(f"  МЕНЕДЖЕР: {v}")
        if v == "confirm":
            await core.manager_action(m, lid, "confirm")
        else:
            await core.manager_said(m, lid, v["own"])
    mock.next_parse = None
    cards = [e for e in m.ev if e[0] == "card"]
    if cards:
        state["lid"] = cards[-1][1]
    for line in show(m.ev):
        print(line)

    errs, bt = [], bot_text(m.ev)
    mgr = "\n".join(e[1] if e[0] in ("mgr", "file") else e[2] for e in m.ev if e[0] in ("mgr", "file", "card"))
    for s in step.get("expect_bot", []):
        if s not in bt: errs.append(f"бот не сказал '{s}'")
    for s in step.get("expect_not_bot", []):
        if s in bt: errs.append(f"бот сказал лишнее '{s}'")
    if step.get("expect_silent") and bt: errs.append("бот должен молчать")
    if "expect_card" in step and bool(cards) != step["expect_card"]: errs.append(f"карточка: ожидали {step['expect_card']}, было {len(cards)}")
    if "expect_buttons" in step and (not cards or cards[-1][3] != step["expect_buttons"]): errs.append(f"кнопки: {cards[-1][3] if cards else None}")
    for s in step.get("expect_manager", []):
        if s not in mgr: errs.append(f"в группу не ушло '{s}'")
    if step.get("expect_forward_before_card"):
        kinds = [e[0] for e in m.ev]
        if "fwd" not in kinds or "card" not in kinds or kinds.index("fwd") > kinds.index("card"):
            errs.append("фото документа должно уйти в группу до карточки")
    ph = [e for e in m.ev if e[0] == "photo"]
    if step.get("expect_photo") and not any(step["expect_photo"] in e[1] for e in ph): errs.append("фото позиции не отправлено")
    if step.get("expect_no_photo") and ph: errs.append("фото позиции отправлено повторно")
    new = db.bookings()[before:]
    eb = step.get("expect_booking")
    if eb:
        if len(new) != 1: errs.append(f"ожидали 1 новую бронь, стало {len(new)}")
        elif isinstance(eb, dict):
            for k, v in eb.items():
                if str(new[0].get(k)) != str(v): errs.append(f"бронь: {k}={new[0].get(k)!r}, ожидали {v!r}")
    if step.get("expect_no_booking") and new: errs.append("бронь не должна создаваться")
    if "expect_document" in step:
        doc = new[0].get("document") if new else ""
        if step["expect_document"] and not (doc and Path(doc).exists()): errs.append("документ не создан")
        elif step["expect_document"] and doc.endswith(".docx"): errs += check_docx(doc, step.get("expect_doc_contains", []))
        if not step["expect_document"] and doc: errs.append("документ не должен создаваться")
    for k, v in (step.get("expect_fields") or {}).items():
        got = (core.state.get(CID) or {}).get("fields", {}).get(k)
        if str(got) != str(v): errs.append(f"поле {k}={got!r}, ожидали {v!r}")
    return errs


async def run_scenario(path: Path, quiet=False) -> list[str]:
    sc = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = config.load(sc["config"])
    tmp = Path(tempfile.mkdtemp(prefix="intake_test_"))
    db.DB = tmp / "test.db"
    cfg.documents.output_dir = str(tmp / "output")
    pdir = tmp / "photos"
    pdir.mkdir()
    for k in sc.get("photos", []):
        (pdir / f"{k}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    os.environ["PHOTOS_DIR"] = str(pdir)
    mock = MockProvider(cfg)
    core = Core(cfg, provider=mock, vision=mock, source=LocalSource(cfg), engine=get_engine(cfg))
    m, state, errs = Fake(), {}, []
    if sc.get("seed_bookings"):
        seed(cfg, sc["seed_bookings"])
    for i, step in enumerate(sc["steps"], 1):
        try:
            e = await run_step(core, m, mock, cfg, step, state)
        except Exception as ex:  # падение кода - тоже провал сценария
            import traceback
            traceback.print_exc()
            e = [f"исключение: {type(ex).__name__}: {ex}"]
        errs += [f"шаг {i}: {x}" for x in e]
    return errs


def check_prompts() -> list[str]:
    """Промпты генерируются из конфига: ключевые правила на месте, нет 'е с точками' и длинных тире."""
    errs = []
    for p in sorted((ROOT / "config").rglob("*.yaml")):
        cfg = config.load(str(p))
        cat = Catalog(cfg)
        ps, pc = prompts.parser_system(cfg, cat, config.today(cfg)), prompts.chat_system(cfg, cat, config.today(cfg), "тест")
        for must in ("ПЕРВОМУ сообщению", "НЕ жалоба", "ПОСЛЕДНЕМ сообщении", "[Бот показал клиенту итог]"):
            if must not in ps: errs.append(f"{p.name}: в промпте разбора нет '{must}'")
        if "[Статус: тест]" not in pc: errs.append(f"{p.name}: в промпте чата нет статуса")
        for name, text in (("разбор", ps), ("чат", pc)):
            if re.search("[\u2014\u2013]", text) or "\u0451" in text.replace("букву \u0451", ""):
                errs.append(f"{p.name}: в промпте ({name}) есть 'е с точками' или длинное тире")
    return errs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    quiet = "-q" in sys.argv
    files = sorted((ROOT / "tests" / "scenarios").rglob("*.yaml"))
    files = [f for f in files if not args or any(a in str(f) for a in args)]
    failed = 0
    errs = check_prompts()
    print(("FAIL" if errs else "PASS") + "  проверка промптов и конфигов" + "".join(f"\n    - {e}" for e in errs))
    failed += bool(errs)
    for f in files:
        name = yaml.safe_load(f.read_text(encoding="utf-8")).get("name", f.stem)
        label = f"{f.parent.name}/{f.stem}: {name}"
        print(f"\n=== {label}")
        if quiet:
            import contextlib, io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                errs = asyncio.run(run_scenario(f))
            if errs:
                print(buf.getvalue())
        else:
            errs = asyncio.run(run_scenario(f))
        print(("FAIL" if errs else "PASS") + f"  {label}" + "".join(f"\n    - {e}" for e in errs))
        failed += bool(errs)
    print(f"\nитого: {len(files) + 1 - failed} из {len(files) + 1} прошли")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
