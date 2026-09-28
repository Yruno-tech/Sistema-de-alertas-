from recipient_validation import validate_sheet_values


HEADERS = [
    "id",
    "nombre",
    "telefono",
    "correo",
    "edificio",
    "activo",
    "sms",
    "correo_habilitado",
]


def test_accepts_three_valid_recipients() -> None:
    values = [
        HEADERS,
        [
            "1",
            "Persona Uno",
            "+5493764000001",
            "uno@example.org",
            "Edificio Anexo",
            "SI",
            "SI",
            "NO",
        ],
        [
            "2",
            "Persona Dos",
            "5493764000002",
            "dos@example.org",
            "Edificio Histórico",
            "SI",
            "SI",
            "SI",
        ],
        [
            "3",
            "Persona Tres",
            "005493764000003",
            "",
            "Tribunal Electoral",
            "SI",
            "SI",
            "NO",
        ],
    ]

    result = validate_sheet_values(values)

    assert len(result.recipients) == 3
    assert not result.errors
    assert result.recipients[1].phone == "+5493764000002"


def test_rejects_domestic_phone_to_avoid_guessing() -> None:
    values = [
        HEADERS,
        [
            "1",
            "Persona Uno",
            "0376415000001",
            "",
            "Edificio Anexo",
            "SI",
            "SI",
            "NO",
        ],
    ]

    result = validate_sheet_values(values)

    assert not result.recipients
    assert len(result.errors) == 1
    assert "+549" in result.errors[0].messages[0]


def test_rejects_duplicate_phone() -> None:
    values = [
        HEADERS,
        ["1", "Uno", "+5493764000001", "", "Anexo", "SI", "SI", "NO"],
        ["2", "Dos", "+5493764000001", "", "Anexo", "SI", "SI", "NO"],
    ]

    result = validate_sheet_values(values)

    assert len(result.recipients) == 1
    assert len(result.errors) == 1
    assert any("duplicado" in item for item in result.errors[0].messages)
