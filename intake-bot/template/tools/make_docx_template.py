"""python tools/make_docx_template.py [config.yaml] (по умолчанию BUSINESS_CONFIG или config/business.yaml): создает templates/contract.docx с плейсхолдерами {{КЛЮЧ}} по конфигу.
Это заготовка: открой в Word, поправь текст под свой договор или замени файл своим (плейсхолдеры оставь)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from intake.config import ConfigError, load


def main():
    try:
        cfg = load(sys.argv[1] if len(sys.argv) > 1 else None)
    except ConfigError as e:
        print(e)
        raise SystemExit(1)
    r, idc = cfg.request, cfg.request.identity_document
    d = Document()
    h = d.add_heading("Договор {{BOOKING_ID}}", level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    d.add_paragraph(f"{cfg.business.name}. Дата: {{{{DATE}}}}")
    d.add_heading("Клиент", level=2)
    d.add_paragraph("Имя: {{CLIENT_NAME}}")
    d.add_paragraph("Контакт: {{CLIENT_CONTACT}}   Телефон: {{CLIENT_PHONE}}")
    if idc.enabled:
        d.add_paragraph(f"Документ ({idc.name}): {{{{DOC_NUMBER}}}}, гражданство {{{{DOC_NATIONALITY}}}}, дата рождения {{{{DOC_BIRTH_DATE}}}}")
    d.add_heading(r.noun.capitalize(), level=2)
    t = d.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    rows = [(r.item_noun.capitalize(), "{{ITEM}}"), ("Период / дата", "{{DATE_FROM}} - {{DATE_TO}}"),
            ("Цена за единицу", "{{PRICE}} {{CURRENCY}}"), ("Итого", "{{TOTAL}} {{CURRENCY}}")]
    rows += [(f.label.capitalize(), "{{" + f.key.upper() + "}}") for f in r.fields if f.type not in ("item", "phone")]
    for a, b in rows:
        c = t.add_row().cells
        c[0].text, c[1].text = a, b
    if cfg.documents.constants:
        d.add_heading("Условия", level=2)
        for k in cfg.documents.constants:
            d.add_paragraph(f"{k}: {{{{{k}}}}}")
    d.add_paragraph("\n\nПодпись клиента: ____________________        Подпись представителя: ____________________")
    out = cfg.path(cfg.documents.docx_template)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))
    print(f"создан {out}")


if __name__ == "__main__":
    main()
