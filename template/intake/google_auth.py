"""Общий загрузчик Google-учетных данных. Библиотеки Google импортируются лениво."""
import os
import threading
from pathlib import Path

from .config import ROOT

_lock = threading.Lock()
_creds = None


def token_path() -> Path:
    p = Path(os.getenv("GOOGLE_TOKEN_FILE") or "google_token.json")
    return p if p.is_absolute() else ROOT / p


def enabled() -> bool:
    return token_path().exists()


def credentials():
    global _creds
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    with _lock:
        if _creds is None:
            _creds = Credentials.from_authorized_user_file(str(token_path()))
        if not _creds.valid:
            _creds.refresh(Request())
        return _creds


def service(name: str, version: str):
    from googleapiclient.discovery import build
    return build(name, version, credentials=credentials(), cache_discovery=False)
