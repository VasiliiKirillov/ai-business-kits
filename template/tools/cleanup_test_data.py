"""python tools/cleanup_test_data.py [--apply]: тестовые брони (клиент содержит TEST) и их документы.
Без --apply только показывает; с --apply отменяет брони и удаляет сгенерированные документы."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()
from intake.config import load
from intake.data import get_source
from intake.data.base import CANCELLED


def main():
    cfg, apply = load(), "--apply" in sys.argv
    src = get_source(cfg)
    test = [b for b in src.list_bookings() if "TEST" in str(b.get("client", "")).upper() and b.get("status") != CANCELLED]
    if not test:
        print("тестовых броней нет")
        return
    engine = None
    if apply:
        from intake.documents import get_engine
        engine = get_engine(cfg)
    for b in test:
        doc = str(b.get("document") or "")
        print(f"{b['id']}  {b.get('item')}  {b.get('start')}  {b.get('client')}  {doc}")
        if not apply:
            continue
        src.cancel_booking(b["id"])
        m = re.search(r"/document/d/([\w-]+)", doc)
        if m:
            engine.delete({"id": m.group(1)})
        elif doc and Path(doc).exists():
            engine.delete({"path": doc})
    print("отменено и удалено" if apply else "это пробный запуск, добавь --apply")


if __name__ == "__main__":
    main()
