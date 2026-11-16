from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from dotenv import load_dotenv, set_key

BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BASE_DIR / ".env"
_SETTINGS_LOCK = threading.RLock()
load_dotenv(DOTENV_PATH)


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


@dataclass
class Settings:
    app_mode: str
    sms_enabled: bool
    spreadsheet_id: str
    sheets_range: str
    service_account_file: Path
    database_path: Path

    def snapshot(self) -> Settings:
        with _SETTINGS_LOCK:
            return replace(self)

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
        )


settings = Settings.load()


def _write_dotenv_values(env_path: Path, values: dict[str, str]) -> None:
    env_path = Path(env_path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f"{env_path.name}.",
            suffix=".tmp",
            dir=env_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(original)
            if original and not original.endswith(("\n", "\r")):
                temporary.write("\n")

        for key, value in values.items():
            success, _, _ = set_key(
                str(temporary_path),
                key,
                value,
                quote_mode="always",
            )
            if not success:
                raise OSError(f"No se pudo escribir {key} en la configuración.")
        os.replace(temporary_path, env_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def save_sheets_configuration(
    spreadsheet_id: str,
    sheets_range: str,
    env_path: Path | None = None,
) -> Settings:
    raw_id = spreadsheet_id.strip()
    if not raw_id or len(raw_id) > 512 or "\n" in raw_id or "\r" in raw_id:
        raise ValueError("Ingresá un ID o una URL válida de Google Sheets.")
    try:
        normalized_id = extract_spreadsheet_id(raw_id)
    except RuntimeError as error:
        raise ValueError(str(error)) from error

    normalized_range = sheets_range.strip()
    if (
        not normalized_range
        or len(normalized_range) > 256
        or any(character in normalized_range for character in ("\n", "\r", "\x00"))
    ):
        raise ValueError("Ingresá un rango A1 válido, por ejemplo DESTINATARIOS!A1:I.")

    _write_dotenv_values(
        env_path or DOTENV_PATH,
        {
            "GOOGLE_SHEETS_ID": normalized_id,
            "GOOGLE_SHEETS_RANGE": normalized_range,
        },
    )
    with _SETTINGS_LOCK:
        settings.spreadsheet_id = normalized_id
        settings.sheets_range = normalized_range
        return replace(settings)
