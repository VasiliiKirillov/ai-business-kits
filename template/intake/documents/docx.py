"""Договор из шаблона .docx: копия + замена {{КЛЮЧ}} в абзацах, таблицах, колонтитулах (в том числе разбитых по run)."""
import re
import shutil
from pathlib import Path

from ..config import Config
from .base import placeholders, title

PH = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def _paragraphs(container):
    """Все абзацы: тело, вложенные таблицы."""
    for p in container.paragraphs:
        yield p
    for t in getattr(container, "tables", []):
        for row in t.rows:
            for cell in row.cells:
                yield from _paragraphs(cell)


def replace_in_paragraph(p, values: dict):
    if "{{" not in p.text:
        return
    sub = lambda m: values.get(m.group(1), m.group(0))
    for r in p.runs:  # сначала по run: сохраняет форматирование
        if "{{" in r.text:
            r.text = PH.sub(sub, r.text)
    if "{{" in p.text and p.runs:  # плейсхолдер разбит по run: склеиваем в первый
        full = PH.sub(sub, p.text)
        p.runs[0].text = full
        for r in p.runs[1:]:
            r.text = ""


class DocxEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def render(self, booking: dict) -> dict:
        from docx import Document
        src = self.cfg.path(self.cfg.documents.docx_template)
        if not src.exists():
            raise FileNotFoundError(f"нет шаблона {src}: python tools/make_docx_template.py")
        out_dir = self.cfg.path(self.cfg.documents.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{title(self.cfg, booking)}.docx"
        shutil.copy(src, out)
        doc, values = Document(str(out)), placeholders(self.cfg, booking)
        parts = [doc] + [x for s in doc.sections for x in (s.header, s.footer, s.first_page_header, s.first_page_footer)]
        for part in parts:
            for p in _paragraphs(part):
                replace_in_paragraph(p, values)
        doc.save(str(out))
        return {"url": None, "path": str(out), "id": None}

    def delete(self, result: dict) -> None:
        if result.get("path"):
            Path(result["path"]).unlink(missing_ok=True)
