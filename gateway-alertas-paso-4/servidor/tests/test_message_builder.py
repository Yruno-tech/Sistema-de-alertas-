from message_builder import (
    AlertValidationError,
    BUILDINGS,
    MAX_SMS_CHARS,
    build_message,
    controlled_reason_limit,
)


def test_evacuation_message_is_one_segment() -> None:
    preview = build_message("edificio-anexo", "evacuation")
    assert preview.message.startswith("PRUEBA - ")
    assert preview.characters <= 160
    assert preview.segments == 1


def test_other_requires_description() -> None:
    try:
        build_message(
            "edificio-anexo",
            "technical",
            technical_cause="other",
            other_description="",
        )
    except AlertValidationError as exc:
        assert "descripción" in str(exc)
    else:
        raise AssertionError("Se esperaba AlertValidationError")


def test_controlled_alert_requires_reason_and_builds_requested_message() -> None:
    try:
        build_message("edificio-anexo", "controlled")
    except AlertValidationError as exc:
        assert "motivo" in str(exc)
    else:
        raise AssertionError("Se esperaba AlertValidationError")

    preview = build_message(
        "edificio-anexo",
        "controlled",
        controlled_reason="Falsa alarma por sensor de humo activado en cocina.",
    )
    assert preview.message == (
        "PRUEBA - AVISO: Situacion controlada en Edificio Anexo. Motivo: "
        "Falsa alarma por sensor de humo activado en cocina. "
        "Puede retornar a sus actividades."
    )
    assert preview.characters == len(preview.message) <= MAX_SMS_CHARS
    assert preview.segments == 1


def test_controlled_alert_reason_limit_keeps_entire_message_within_one_sms() -> None:
    for building_id in BUILDINGS:
        limit = controlled_reason_limit(building_id)
        preview = build_message(
            building_id, "controlled", controlled_reason="x" * limit
        )
        assert preview.characters == MAX_SMS_CHARS
        assert len(preview.message) == MAX_SMS_CHARS
        try:
            build_message(
                building_id, "controlled", controlled_reason="x" * (limit + 1)
            )
        except AlertValidationError as exc:
            assert "admite hasta" in str(exc)
        else:
            raise AssertionError("Se esperaba AlertValidationError")
