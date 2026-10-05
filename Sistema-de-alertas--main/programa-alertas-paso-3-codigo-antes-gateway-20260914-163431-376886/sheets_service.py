from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from config import Settings


class SheetsConfigurationError(RuntimeError):
    """Raised when local configuration is missing or unsafe."""


class SheetsReadError(RuntimeError):
    """Raised when Google Sheets cannot be read."""


def read_service_account_email(credentials_file: Path) -> str:
    try:
        payload = json.loads(credentials_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SheetsConfigurationError(
            "No se encontró el archivo de credenciales: "
            f"{credentials_file}. Guarde allí la clave JSON de la cuenta de servicio."
        ) from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise SheetsConfigurationError(
            "El archivo de credenciales existe, pero no es un JSON válido."
        ) from exc

    email = str(payload.get("client_email", "")).strip()
    if not email:
        raise SheetsConfigurationError(
            "El JSON no contiene client_email y no parece ser una clave "
            "de cuenta de servicio válida."
        )
    return email


def read_sheet_values(settings: Settings) -> Sequence[Sequence[object]]:
    if not settings.spreadsheet_id:
        raise SheetsConfigurationError(
            "Falta GOOGLE_SHEETS_ID en el archivo .env."
        )
    if not settings.sheets_range:
        raise SheetsConfigurationError(
            "Falta GOOGLE_SHEETS_RANGE en el archivo .env."
        )

    credentials_file = settings.service_account_file
    service_account_email = read_service_account_email(credentials_file)

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as exc:
        raise SheetsConfigurationError(
            "Faltan las bibliotecas de Google. Ejecute: "
            "pip install -r requirements.txt"
        ) from exc

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_file),
            scopes=scopes,
        )
        service = build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False,
        )
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=settings.spreadsheet_id,
                range=settings.sheets_range,
                majorDimension="ROWS",
                valueRenderOption="FORMATTED_VALUE",
            )
            .execute()
        )
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        if status == 403:
            detail = (
                "Google devolvió 403. Comparta la planilla con "
                f"{service_account_email} como Lector y verifique que "
                "Google Sheets API esté habilitada."
            )
        elif status == 404:
            detail = (
                "Google devolvió 404. Revise GOOGLE_SHEETS_ID y el nombre "
                "de la pestaña indicado en GOOGLE_SHEETS_RANGE."
            )
        else:
            detail = f"Google Sheets devolvió un error HTTP {status or 'desconocido'}."
        raise SheetsReadError(detail) from exc
    except OSError as exc:
        raise SheetsConfigurationError(
            "No se pudieron leer las credenciales de Google."
        ) from exc
    except Exception as exc:
        raise SheetsReadError(
            "No fue posible conectarse con Google Sheets. Revise Internet, "
            "credenciales, ID y rango."
        ) from exc

    values = result.get("values", [])
    if not isinstance(values, list):
        raise SheetsReadError("Google Sheets devolvió una respuesta inesperada.")
    return values
