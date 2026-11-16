from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MAX_CREDENTIAL_SIZE = 1024 * 1024


class CredentialUploadError(ValueError):
    pass


def save_service_account_json(contents: bytes, destination: Path) -> str:
    if not contents:
        raise CredentialUploadError("Seleccioná un archivo JSON.")
    if len(contents) > MAX_CREDENTIAL_SIZE:
        raise CredentialUploadError("El archivo supera el límite de 1 MB.")

    try:
        payload = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CredentialUploadError("El archivo seleccionado no contiene JSON válido.") from error

    if not isinstance(payload, dict) or payload.get("type") != "service_account":
        raise CredentialUploadError(
            "El JSON no es una clave de cuenta de servicio de Google."
        )
    email = str(payload.get("client_email", "")).strip()
    if not email or not payload.get("private_key"):
        raise CredentialUploadError(
            "La clave debe incluir client_email y private_key."
        )

    try:
        from google.oauth2 import service_account

        service_account.Credentials.from_service_account_info(
            payload,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
    except (ImportError, ValueError, TypeError, KeyError) as error:
        raise CredentialUploadError(
            "La clave no tiene una estructura válida o su clave privada está dañada."
        ) from error

    destination = Path(destination)
    temporary_path = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".service-account-", suffix=".tmp",
            dir=destination.parent, delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
        if os.name != "nt":
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, destination)
    except OSError as error:
        raise CredentialUploadError(
            "No se pudo guardar la credencial. Revisá los permisos de la carpeta del servidor."
        ) from error
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()

    return email
