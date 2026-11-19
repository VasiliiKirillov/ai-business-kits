"""Детерминированная заглушка для тестов: без ключей и сети.

parse: возвращает накопленное состояние из сценария (mock.next_parse), без сценария - простая эвристика.
chat: "[бот] " + статус, чтобы тесты проверяли, что именно сказал код.
vision: возвращает mock.next_doc.
"""
import json
import re
from typing import Optional

from .base import Provider

META = {"type": None, "confirmed": False, "declined_field": None, "wants_photo": False, "photo_of": None}


class MockProvider(Provider):
    name = "mock"
    vision = True

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.next_parse: Optional[dict] = None
        self.next_doc: Optional[dict] = None
        self.reset()

    def reset(self):
        self.state: dict = {}
        self.type: Optional[str] = None

    async def complete(self, system, messages, json=False, image=None, purpose="parse"):
        if purpose == "chat":
            i = system.rfind("[Статус:")
            status = system[i + len("[Статус:"):].strip().rstrip("]").strip() if i >= 0 else ""
            return "[бот] " + status, {"in": 0, "out": 0}
        if image:
            doc = {k.removeprefix("doc_"): v for k, v in (self.next_doc or {}).items()}
            doc.setdefault("doc_type", "id_document")
            return _dumps(doc), {"in": 0, "out": 0}
        step, self.next_parse = self.next_parse, None
        if step is None:
            step = self._heuristic(messages[-1]["content"])
        for k, v in step.items():
            if k not in META:
                self.state[k] = v
        self.type = step.get("type") or self.type or "question"
        out = {**self.state, "type": self.type, **{k: step.get(k, d) for k, d in META.items() if k != "type"}}
        return _dumps(out), {"in": 0, "out": 0}

    def _heuristic(self, transcript: str) -> dict:
        """Очень простой разбор для --console --mock: позиция по синонимам, дата YYYY-MM-DD, время HH:MM,
        "на N" для числового поля, телефон, "да"; иначе весь текст идет в первое пустое текстовое поле."""
        lines = [x for x in transcript.splitlines() if x.startswith("Клиент:")]
        text = lines[-1][len("Клиент:"):].strip() if lines else ""
        step: dict = {}
        if re.fullmatch(r"(да|ок|ok|yes|верно)\W*", text.lower()):
            return {"confirmed": True}
        if not self.cfg:
            return step
        fields = self.cfg.request.fields
        first = lambda t: next((f.key for f in fields if f.type == t), None)  # noqa: E731
        rest = text
        from ..catalog import Catalog
        ms = Catalog(self.cfg).match(text)
        if ms and self.cfg.item_key:
            step[self.cfg.item_key] = ms[0][0].name if ms[0][1] == "item" else ms[0][0].category
            step["type"] = "request"
        if (m := re.search(r"\d{4}-\d{2}-\d{2}", rest)) and first("date"):
            step[first("date")] = m.group(0)
            rest = rest.replace(m.group(0), " ")
        if (m := re.search(r"\b(\d{1,2}):(\d{2})\b", rest)) and first("time"):
            step[first("time")] = f"{int(m.group(1)):02d}:{m.group(2)}"
            rest = rest.replace(m.group(0), " ")
        if (m := re.search(r"\+?\d[\d ()-]{7,}\d", rest)) and first("phone"):
            step[first("phone")] = m.group(0)
            rest = rest.replace(m.group(0), " ")
        dur = self.cfg.pricing.duration_field or next((f.key for f in fields if f.type == "int" and not f.default), None)
        if (m := re.search(r"на (\d+)", rest)) and dur:
            step[dur] = int(m.group(1))
        idc = self.cfg.request.identity_document
        if idc.enabled and (m := re.search(r"\b([A-Z]{2,} [A-Z]{2,})\b.*?\b(\d{6,})\b", text)):  # "IVAN TESTOV 000000000 ..."
            step.update(doc_full_name=m.group(1), doc_number=m.group(2))
            step.pop(first("phone"), None)
            if (c := re.search(r"\b([A-Z][a-z]+)\b", text)):
                step["doc_nationality"] = c.group(1)
            if (d := re.search(r"\d{4}-\d{2}-\d{2}", text)):
                step["doc_birth_date"] = d.group(0)
                step.pop(first("date"), None)
        if not step:
            k = next((f.key for f in fields if f.type == "text" and not self.state.get(f.key)), None)
            if k and self.state:
                step[k] = text
        return step


def _dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)
