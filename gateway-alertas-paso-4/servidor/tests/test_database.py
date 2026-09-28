from pathlib import Path

from database import Database
from recipient_validation import RecipientRecord, ValidationResult


def test_sync_and_list(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    recipient = RecipientRecord(
        source_key="sheet:1",
        sheet_row=2,
        external_id="1",
        name="Persona de prueba",
        phone="+5493764000001",
        email="persona@example.org",
        building_id="edificio-anexo",
        active=True,
        sms_enabled=True,
        email_enabled=False,
    )
    result = ValidationResult(
        recipients=(recipient,),
        errors=(),
        rows_read=1,
        blank_rows=0,
        seen_source_keys=frozenset({"sheet:1"}),
    )

    summary = database.sync_recipients(result)
    recipients = database.get_active_sms_recipients("edificio-anexo")

    assert summary.inserted == 1
    assert len(recipients) == 1
    assert recipients[0]["phone_masked"].endswith("0001")
