from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

from message_builder import BUILDINGS


class HeaderValidationError(ValueError):
    """Raised when the first row of the sheet does not contain required columns."""


@dataclass(frozen=True)
class RecipientRecord:
    source_key: str
    sheet_row: int
    external_id: str
    name: str
    phone: str
    email: str
    building_id: str
    active: bool
    sms_enabled: bool
    email_enabled: bool


@dataclass(frozen=True)
class RowValidationError:
    row_number: int
    source_key: str | None
    name_hint: str
    messages: tuple[str, ...]


@dataclass(frozen=True)
class ValidationResult:
    recipients: tuple[RecipientRecord, ...]
    errors: tuple[RowValidationError, ...]
    rows_read: int
    blank_rows: int
    seen_source_keys: frozenset[str]


HEADER_ALIASES = {
    "id": {
        "id",
        "identificador",
        "legajo",
    },
    "name": {
        "nombre",
        "nombre_y_apellido",
        "apellido_y_nombre",
        "trabajador",
        "persona",
    },
    "phone": {
        "telefono",
        "numero_de_telefono",
        "numero_telefono",
        "nro_telefono",
        "celular",
        "movil",
    },
    "email": {
        "correo",
        "correo_electronico",
        "email",
        "e_mail",
    },
    "building": {
        "edificio",
        "sede",
        "lugar",
        "dependencia",
    },
    "active": {
        "activo",
        "activa",
        "habilitado",
        "habilitada",
    },
    "sms_enabled": {
        "sms",
        "recibe_sms",
        "sms_habilitado",
        "enviar_sms",
    },
    "email_enabled": {
        "correo_habilitado",
        "recibe_correo",
        "email_habilitado",
        "enviar_correo",
    },
}

REQUIRED_COLUMNS = {"name", "phone", "building", "active", "sms_enabled"}

TRUE_VALUES = {"1", "true", "yes", "si", "s", "x", "activo", "activa"}
FALSE_VALUES = {"0", "false", "no", "n", "inactivo", "inactiva"}

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ARGENTINA_MOBILE_PATTERN = re.compile(r"^\+549\d{10}$")


def normalize_token(value: object) -> str:
    text = "" if value is None else str(value)
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def normalize_display_text(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def _canonical_header_map(headers: Sequence[object]) -> dict[str, int]:
    alias_to_field: dict[str, str] = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            alias_to_field[normalize_token(alias)] = field

    result: dict[str, int] = {}
    duplicates: list[str] = []

    for index, raw_header in enumerate(headers):
        token = normalize_token(raw_header)
        canonical = alias_to_field.get(token)
        if canonical is None:
            continue
        if canonical in result:
            duplicates.append(canonical)
            continue
        result[canonical] = index

    missing = sorted(REQUIRED_COLUMNS - result.keys())
    if missing:
        friendly = {
            "name": "nombre",
            "phone": "telefono",
            "building": "edificio",
            "active": "activo",
            "sms_enabled": "sms",
        }
        missing_labels = ", ".join(friendly[item] for item in missing)
        raise HeaderValidationError(
            "Faltan columnas obligatorias en la primera fila: "
            f"{missing_labels}. Use, como mínimo: "
            "nombre | telefono | edificio | activo | sms."
        )

    if duplicates:
        raise HeaderValidationError(
            "Hay columnas duplicadas que representan el mismo dato: "
            + ", ".join(sorted(set(duplicates)))
            + "."
        )

    return result


def _cell(row: Sequence[object], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return normalize_display_text(row[index])


def parse_boolean(value: str, *, field_label: str, default: bool | None = None) -> bool:
    token = normalize_token(value)
    if not token and default is not None:
        return default
    if token in TRUE_VALUES:
        return True
    if token in FALSE_VALUES:
        return False
    raise ValueError(
        f"{field_label} debe contener SI o NO; se recibió «{value or '(vacío)'}»."
    )


def normalize_argentina_mobile(value: str) -> str:
    """Normalize only unambiguous Argentine mobile international formats."""
    compact = re.sub(r"[\s().-]+", "", value.strip())

    if compact.startswith("00549"):
        compact = "+" + compact[2:]
    elif compact.startswith("549") and compact.isdigit():
        compact = "+" + compact

    if not ARGENTINA_MOBILE_PATTERN.fullmatch(compact):
        raise ValueError(
            "el teléfono debe ser un celular argentino en formato "
            "+549XXXXXXXXXX, sin 0 ni 15"
        )
    return compact


def normalize_building(value: str) -> str:
    token = normalize_token(value)

    aliases = {
        "tribunal_electoral": "tribunal-electoral",
        "tribunal_electoral_de_la_provincia_de_misiones": "tribunal-electoral",
        "tribunal": "tribunal-electoral",
        "edificio_historico": "edificio-historico",
        "historico": "edificio-historico",
        "edificio_anexo": "edificio-anexo",
        "anexo": "edificio-anexo",
    }

    if token in BUILDINGS:
        return token.replace("_", "-")

    building_id = aliases.get(token)
    if building_id is None:
        valid_labels = ", ".join(item["label"] for item in BUILDINGS.values())
        raise ValueError(f"el edificio no es válido. Opciones: {valid_labels}")
    return building_id


def _source_key(external_id: str, normalized_phone: str | None) -> str | None:
    if external_id:
        return f"sheet:{normalize_token(external_id)}"
    if normalized_phone:
        return f"phone:{normalized_phone}"
    return None


def validate_sheet_values(values: Sequence[Sequence[object]]) -> ValidationResult:
    if not values:
        raise HeaderValidationError(
            "La API no devolvió filas. Verifique el ID y el rango de la planilla."
        )

    header_map = _canonical_header_map(values[0])
    recipients: list[RecipientRecord] = []
    errors: list[RowValidationError] = []
    seen_source_keys: set[str] = set()
    accepted_source_keys: set[str] = set()
    accepted_phones: set[str] = set()
    blank_rows = 0
    rows_read = 0

    for row_number, row in enumerate(values[1:], start=2):
        if not any(normalize_display_text(cell) for cell in row):
            blank_rows += 1
            continue

        rows_read += 1
        external_id = _cell(row, header_map.get("id"))
        name = _cell(row, header_map.get("name"))
        raw_phone = _cell(row, header_map.get("phone"))
        email = _cell(row, header_map.get("email")).lower()
        raw_building = _cell(row, header_map.get("building"))
        raw_active = _cell(row, header_map.get("active"))
        raw_sms = _cell(row, header_map.get("sms_enabled"))
        raw_email_enabled = _cell(row, header_map.get("email_enabled"))

        row_errors: list[str] = []
        normalized_phone: str | None = None

        try:
            normalized_phone = normalize_argentina_mobile(raw_phone)
        except ValueError as exc:
            row_errors.append(str(exc))

        tentative_source_key = _source_key(external_id, normalized_phone)
        if tentative_source_key:
            seen_source_keys.add(tentative_source_key)

        if not name:
            row_errors.append("el nombre está vacío")

        try:
            building_id = normalize_building(raw_building)
        except ValueError as exc:
            row_errors.append(str(exc))
            building_id = ""

        try:
            active = parse_boolean(raw_active, field_label="activo")
        except ValueError as exc:
            row_errors.append(str(exc))
            active = False

        try:
            sms_enabled = parse_boolean(raw_sms, field_label="sms")
        except ValueError as exc:
            row_errors.append(str(exc))
            sms_enabled = False

        try:
            email_enabled = parse_boolean(
                raw_email_enabled,
                field_label="correo_habilitado",
                default=False,
            )
        except ValueError as exc:
            row_errors.append(str(exc))
            email_enabled = False

        if email and not EMAIL_PATTERN.fullmatch(email):
            row_errors.append("el correo electrónico no tiene un formato válido")
        if email_enabled and not email:
            row_errors.append(
                "correo_habilitado está en SI, pero la celda correo está vacía"
            )

        if tentative_source_key and tentative_source_key in accepted_source_keys:
            row_errors.append("el ID o teléfono está duplicado en la planilla")
        if normalized_phone and normalized_phone in accepted_phones:
            row_errors.append("el teléfono está duplicado en la planilla")

        if row_errors:
            errors.append(
                RowValidationError(
                    row_number=row_number,
                    source_key=tentative_source_key,
                    name_hint=name or "(sin nombre)",
                    messages=tuple(row_errors),
                )
            )
            continue

        assert normalized_phone is not None
        assert tentative_source_key is not None

        recipient = RecipientRecord(
            source_key=tentative_source_key,
            sheet_row=row_number,
            external_id=external_id,
            name=name,
            phone=normalized_phone,
            email=email,
            building_id=building_id,
            active=active,
            sms_enabled=sms_enabled,
            email_enabled=email_enabled,
        )
        recipients.append(recipient)
        accepted_source_keys.add(tentative_source_key)
        accepted_phones.add(normalized_phone)

    return ValidationResult(
        recipients=tuple(recipients),
        errors=tuple(errors),
        rows_read=rows_read,
        blank_rows=blank_rows,
        seen_source_keys=frozenset(seen_source_keys),
    )
