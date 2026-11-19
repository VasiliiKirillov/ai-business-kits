"""Google Docs: копия шаблона (GOOGLE_DOC_TEMPLATE_ID) + replaceAllText. Возвращает ссылку."""
import os

from .. import google_auth
from ..config import Config
from .base import placeholders, title


class GoogleDocsEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def render(self, booking: dict) -> dict:
        drive, docs = google_auth.service("drive", "v3"), google_auth.service("docs", "v1")
        body = {"name": title(self.cfg, booking)}
        if os.getenv("GOOGLE_DOCS_FOLDER_ID"):
            body["parents"] = [os.environ["GOOGLE_DOCS_FOLDER_ID"]]
        new = drive.files().copy(fileId=os.environ["GOOGLE_DOC_TEMPLATE_ID"], body=body).execute()["id"]
        reqs = [{"replaceAllText": {"containsText": {"text": "{{" + k + "}}", "matchCase": True}, "replaceText": v}}
                for k, v in placeholders(self.cfg, booking).items()]
        docs.documents().batchUpdate(documentId=new, body={"requests": reqs}).execute()
        return {"url": f"https://docs.google.com/document/d/{new}/edit", "path": None, "id": new}

    def delete(self, result: dict) -> None:
        if result.get("id"):
            google_auth.service("drive", "v3").files().delete(fileId=result["id"]).execute()
