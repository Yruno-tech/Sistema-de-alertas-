from message_builder import AlertValidationError, build_message


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
