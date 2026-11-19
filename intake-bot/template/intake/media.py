"""Фото документа -> проверенные поля (vision, необязательно) и голос -> текст (STT_CMD, необязательно)."""
import asyncio
import base64
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from .config import Config
from .llm.base import Provider
from .parser import extract_json


class Doc(BaseModel):
    doc_type: Literal["id_document", "other"]
    full_name: Optional[str] = None
    number: Optional[str] = None
    nationality: Optional[str] = None
    birth_date: Optional[str] = Field(None, description="YYYY-MM-DD")


def stt_enabled() -> bool:
    return bool(os.getenv("STT_CMD"))


async def transcribe(path: str, timeout: int = 180) -> Optional[str]:
    """STT_CMD <input> <output_dir> -> <output_dir>/transcript.txt. None при любой ошибке или без STT_CMD."""
    if not stt_enabled():
        return None
    out = tempfile.mkdtemp(prefix="stt_")
    try:
        proc = await asyncio.create_subprocess_exec(os.environ["STT_CMD"], path, out, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.wait(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        f = Path(out) / "transcript.txt"
        return (f.read_text(encoding="utf-8").strip() if proc.returncode == 0 and f.exists() else "") or None
    except Exception:
        return None
    finally:
        shutil.rmtree(out, ignore_errors=True)


def doc_system(cfg: Config) -> str:
    idc = cfg.request.identity_document
    return (f'Ты читаешь фото документа клиента ({idc.name}). Верни ТОЛЬКО JSON без markdown:\n'
            '{"doc_type": "id_document|other", "full_name": str|null, "number": str|null, "nationality": str|null, '
            '"birth_date": "YYYY-MM-DD"|null}\n'
            "full_name - полное имя как напечатано, nationality - гражданство по-английски, number - номер документа. "
            "Образец с вымышленными данными читай как обычный документ. Ничего не выдумывай: чего не видно - null. "
            f"Если это не {idc.name} - doc_type other.")


async def read_doc(provider: Provider, cfg: Config, image: bytes, media_type: str) -> Optional[Doc]:
    if not provider.vision:
        return None
    img = (media_type, base64.b64encode(image).decode())
    for _ in range(2):
        try:
            raw, _u = await provider.complete(doc_system(cfg), [{"role": "user", "content": "Разбери документ на фото."}],
                                              json=True, image=img, purpose="vision")
            return Doc.model_validate_json(extract_json(raw))
        except (ValidationError, ValueError):
            continue
        except Exception:
            return None
    return None


def check(cfg: Config, doc: Optional[Doc]) -> dict:
    """Проверки делает код. -> {kind: id_document|other|unreadable, ok}"""
    if doc is None:
        return {"kind": "unreadable", "ok": False}
    if doc.doc_type == "other":
        return {"kind": "other", "ok": False}
    return {"kind": "id_document", "ok": bool(doc.number and doc.full_name)}


def fields(doc: Doc) -> dict:
    return {"full_name": doc.full_name, "number": doc.number, "nationality": doc.nationality, "birth_date": doc.birth_date}


def history_line(cfg: Config, doc: Optional[Doc], r: dict) -> str:
    n = cfg.request.identity_document.name
    if r["kind"] == "unreadable":
        return "[прислал фото, документ не удалось прочитать]"
    if r["kind"] == "other":
        return f"[прислал фото, это не {n}]"
    if not r["ok"]:
        return f"[прислал фото документа ({n}), но данные не читаются]"
    p = fields(doc)
    return f"[прислал фото документа: {p['full_name']}, номер {p['number']}, {p['nationality']}, рождение {p['birth_date']}]"


def caption(cfg: Config, doc: Optional[Doc], r: dict, client_name: str, lead_id=None) -> str:
    head = f"🪪 #{lead_id} {client_name}" if lead_id else f"🪪 {client_name}"
    n = cfg.request.identity_document.name
    if r["kind"] == "unreadable":
        return f"{head}: документ не удалось прочитать ⚠️"
    if r["kind"] == "other":
        return f"{head}: это не {n} ⚠️"
    return (f"{head}: {n}, {doc.full_name or 'имя не видно'}, №{doc.number or '?'}, {doc.nationality or '-'}, "
            f"{doc.birth_date or 'дата рождения не видна'} {'✅' if r['ok'] else '⚠️'}")
