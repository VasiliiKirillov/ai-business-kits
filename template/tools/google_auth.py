"""Один раз получить токен Google (на сервере, где работает бот). Запуск:
  1) на своем компьютере:  ssh -L 8085:localhost:8085 <сервер>
  2) на сервере:            cd ~/intake-bot && .venv/bin/python tools/google_auth.py
  3) открыть ссылку из вывода в браузере на своем компьютере, войти в нужный аккаунт, разрешить доступ.
Нужны GOOGLE_OAUTH_CLIENT_ID и GOOGLE_OAUTH_CLIENT_SECRET в .env и requirements-google.txt.
Токен сохраняется в google_token.json (права 600)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

from intake.google_auth import token_path

load_dotenv()
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/documents",
          "https://www.googleapis.com/auth/drive.file"]


def main():
    cfg = {"installed": {"client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"], "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
                         "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                         "redirect_uris": ["http://localhost"]}}
    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(host="localhost", port=8085, open_browser=False, access_type="offline", prompt="consent",
                                  authorization_prompt_message="Открой эту ссылку в браузере:\n{url}\n")
    out = token_path()
    out.write_text(creds.to_json())
    out.chmod(0o600)
    print("готово, токен сохранен, refresh_token есть:", bool(creds.refresh_token))


if __name__ == "__main__":
    main()
