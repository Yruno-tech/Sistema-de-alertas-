from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_SMS_CHARS = 160
TEST_PREFIX = "PRUEBA - "

BUILDINGS = {
    "tribunal-electoral": {
        "label": "Tribunal Electoral de la Provincia de Misiones",
        "sms_name": "Tribunal Electoral",
    },
    "edificio-historico": {
        "label": "Edificio Histórico",
        "sms_name": "Edificio Historico",
    },
    "edificio-anexo": {
        "label": "Edificio Anexo",
        "sms_name": "Edificio Anexo",
    },
}

ALERT_TYPES = {
    "evacuation": "Alarma de Evacuación",
    "maintenance": "Mantenimiento/Pruebas",
    "technical": "Error técnico",
    "controlled": "Alarma de Situación Controlada",
}

CONTROLLED_REASON_SUFFIX = ". Puede retornar a sus actividades."

TECHNICAL_CAUSES = {
    "sensor-dirt": {
        "label": "Acumulación de suciedad en los sensores",
        "sms_text": "suciedad en sensores",
    },
    "wiring": {
        "label": "Fallas en el cableado eléctrico",
        "sms_text": "falla de cableado electrico",
    },
    "batteries": {
        "label": "Baterías agotadas",
        "sms_text": "baterias agotadas",
    },
    "panel": {
        "label": "Problemas en la programación del panel central",
        "sms_text": "falla en la programacion del panel central",
    },
    "other": {
        "label": "Otros",
        "sms_text": None,
    },
}


class AlertValidationError(ValueError):
    """Raised when alert data cannot produce a valid test SMS."""


@dataclass(frozen=True)
class MessagePreview:
    building_label: str
    alert_label: str
    cause_label: str | None
    message: str
    characters: int
    segments: int
    remaining: int


def normalize_sms_text(value: str) -> str:
    """Convert free text to a conservative ASCII subset for one-part test SMS."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
    ascii_text = re.sub(r"[^A-Za-z0-9 .,;:()/_-]", "", ascii_text)
    return ascii_text


def controlled_reason_limit(building_id: str) -> int:
    building = BUILDINGS.get(building_id)
    if building is None:
        raise AlertValidationError("Seleccione un edificio válido.")

    fixed_text = (
        f"{TEST_PREFIX}AVISO: Situacion controlada en {building['sms_name']}. "
        f"Motivo: {CONTROLLED_REASON_SUFFIX}"
    )
    return MAX_SMS_CHARS - len(fixed_text)


def build_message(
    building_id: str,
    alert_type: str,
    technical_cause: str = "",
    other_description: str = "",
    controlled_reason: str = "",
) -> MessagePreview:
    building = BUILDINGS.get(building_id)
    if building is None:
        raise AlertValidationError("Seleccione un edificio válido.")

    alert_label = ALERT_TYPES.get(alert_type)
    if alert_label is None:
        raise AlertValidationError("Seleccione un tipo de alerta válido.")

    sms_building = building["sms_name"]
    cause_label: str | None = None

    if alert_type == "evacuation":
        message = (
            f"{TEST_PREFIX}ALERTA EVACUACION - {sms_building}. "
            "Evacue en orden y siga las indicaciones del personal de seguridad."
        )
    elif alert_type == "maintenance":
        message = (
            f"{TEST_PREFIX}AVISO MANTENIMIENTO - {sms_building}. "
            "Alarma por tareas programadas. Mantenga la calma y siga las "
            "indicaciones de seguridad."
        )
    elif alert_type == "controlled":
        reason_limit = controlled_reason_limit(building_id)
        if not controlled_reason.strip():
            raise AlertValidationError("Ingrese el motivo por el que finaliza la alerta.")
        if len(controlled_reason) > reason_limit:
            raise AlertValidationError(
                f"El motivo admite hasta {reason_limit} caracteres para este edificio."
            )
        cause_text = normalize_sms_text(controlled_reason).rstrip(". ")
        if not cause_text:
            raise AlertValidationError("Ingrese un motivo válido para finalizar la alerta.")
        cause_label = f"Motivo: {controlled_reason.strip()}"
        message = (
            f"{TEST_PREFIX}AVISO: Situacion controlada en {sms_building}. "
            f"Motivo: {cause_text}{CONTROLLED_REASON_SUFFIX}"
        )
    else:
        cause = TECHNICAL_CAUSES.get(technical_cause)
        if cause is None:
            raise AlertValidationError("Seleccione una causa del error técnico.")

        cause_label = cause["label"]
        if technical_cause == "other":
            if len(other_description.strip()) > 50:
                raise AlertValidationError("La descripción de Otros admite hasta 50 caracteres.")
            cause_text = normalize_sms_text(other_description)
            if not cause_text:
                raise AlertValidationError(
                    "Ingrese una descripción breve para la opción Otros."
                )
            cause_label = f"Otros: {other_description.strip()}"
        else:
            cause_text = str(cause["sms_text"])

        message = (
            f"{TEST_PREFIX}AVISO TECNICO - {sms_building}. Falla: {cause_text}. "
            "Mantenga la calma y siga indicaciones de seguridad."
        )

    characters = len(message)
    if characters > MAX_SMS_CHARS:
        overflow = characters - MAX_SMS_CHARS
        raise AlertValidationError(
            f"El mensaje supera el límite de {MAX_SMS_CHARS} caracteres por "
            f"{overflow}. Reduzca la descripción."
        )

    return MessagePreview(
        building_label=building["label"],
        alert_label=alert_label,
        cause_label=cause_label,
        message=message,
        characters=characters,
        segments=1,
        remaining=MAX_SMS_CHARS - characters,
    )
