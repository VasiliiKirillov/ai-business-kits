"""python tools/setup_google_sheet.py [--upload-template]: создает таблицу с вкладками каталога и броней по конфигу.
Печатает SHEET_ID (и GOOGLE_DOC_TEMPLATE_ID при --upload-template) для .env. Нужен google_token.json."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()
from intake import google_auth
from intake.config import load
from intake.data.google_sheets import CATALOG_COLS, columns


def main():
    cfg = load()
    tabs = cfg.data.google_sheets
    sh = google_auth.service("sheets", "v4")
    # локаль en_US: иначе формулы через API ломаются
    ss = sh.spreadsheets().create(body={
        "properties": {"title": f"{cfg.business.name} - учет", "locale": "en_US"},
        "sheets": [{"properties": {"title": tabs.catalog_tab}}, {"properties": {"title": tabs.bookings_tab}}]}).execute()
    sid = ss["spreadsheetId"]
    cat = [CATALOG_COLS] + [[i.name, i.category or "", i.price if i.price is not None else "", i.stock,
                             ", ".join(i.aliases), i.details or ""] for i in cfg.catalog.items]
    for tab, rows in ((tabs.catalog_tab, cat), (tabs.bookings_tab, [columns(cfg)])):
        sh.spreadsheets().values().update(spreadsheetId=sid, range=f"{tab}!A1", valueInputOption="USER_ENTERED",
                                          body={"values": rows}).execute()
    print(f"SHEET_ID={sid}")
    print(f"https://docs.google.com/spreadsheets/d/{sid}/edit")
    if "--upload-template" in sys.argv:
        from googleapiclient.http import MediaFileUpload
        src = cfg.path(cfg.documents.docx_template)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        f = google_auth.service("drive", "v3").files().create(
            body={"name": f"{cfg.business.name} - шаблон", "mimeType": "application/vnd.google-apps.document"},
            media_body=MediaFileUpload(str(src), mimetype=mime), fields="id").execute()
        print(f"GOOGLE_DOC_TEMPLATE_ID={f['id']}")


if __name__ == "__main__":
    main()
