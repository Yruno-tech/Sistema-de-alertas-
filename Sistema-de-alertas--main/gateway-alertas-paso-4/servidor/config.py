from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} debe contener un número entero.") from exc
    if value < 1:
        raise RuntimeError(f"{name} debe ser mayor que cero.")
    return value


def _resolve_path(raw_path: str, default_relative: str) -> Path:
    value = raw_path.strip() if raw_path else default_relative
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def extract_spreadsheet_id(value: str) -> str:
    """Accept either a Google Sheets ID or its complete URL."""
    candidate = value.strip()
    if not candidate:
        return ""

    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", candidate)
    if match:
        return match.group(1)

    if re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        return candidate

    raise RuntimeError(
        "GOOGLE_SHEETS_ID no parece ser un ID ni una URL válida de Google Sheets."
    )


@dataclass(frozen=True)
class Settings:
    app_mode: str
    sms_enabled: bool
    spreadsheet_id: str
    sheets_range: str
    service_account_file: Path
    database_path: Path
    test_recipient_limit: int

    @classmethod
    def load(cls) -> "Settings":
        app_mode = os.getenv("APP_MODE", "test").strip().lower() or "test"
        sms_enabled = _env_bool("SMS_ENABLED", False)

        if app_mode != "test" or sms_enabled:
            raise RuntimeError(
                "Esta versión requiere APP_MODE=test y SMS_ENABLED=false. "
                "Los SMS reales de prueba se habilitan por separado desde /gateway."
            )

        return cls(
            app_mode=app_mode,
            sms_enabled=sms_enabled,
            spreadsheet_id=extract_spreadsheet_id(
                os.getenv("GOOGLE_SHEETS_ID", "")
            ),
            sheets_range=os.getenv(
                "GOOGLE_SHEETS_RANGE",
                "DESTINATARIOS!A1:I",
            ).strip(),
            service_account_file=_resolve_path(
                os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
                "credentials/service-account.json",
            ),
            database_path=_resolve_path(
                os.getenv("DATABASE_PATH", ""),
                "data/alerts.db",
            ),
            test_recipient_limit=_env_int("TEST_RECIPIENT_LIMIT", 3),
        )


settings = Settings.load()
