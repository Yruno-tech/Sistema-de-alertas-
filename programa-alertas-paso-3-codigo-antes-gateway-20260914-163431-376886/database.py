from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from message_builder import MessagePreview
from recipient_validation import RecipientRecord, ValidationResult


def now_iso() -> str:
    try:
        timezone_info = ZoneInfo("America/Argentina/Cordoba")
    except Exception:
        timezone_info = timezone.utc
    return datetime.now(timezone_info).isoformat(timespec="seconds")


def mask_phone(phone: str) -> str:
    if len(phone) <= 8:
        return "•" * max(len(phone) - 2, 0) + phone[-2:]
    return phone[:4] + "•" * (len(phone) - 8) + phone[-4:]


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "•"
    else:
        masked_local = local[:2] + "•" * max(len(local) - 2, 1)
    return f"{masked_local}@{domain}"


@dataclass(frozen=True)
class SyncSummary:
    sync_id: int
    status: str
    rows_read: int
    accepted: int
    rejected: int
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    active_sms_recipients: int
    completed_at: str


class SyncSafetyError(RuntimeError):
    """Raised when a sync would be unsafe to apply."""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS recipients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    external_id TEXT NOT NULL DEFAULT '',
                    sheet_row INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    building_id TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK (active IN (0, 1)),
                    sms_enabled INTEGER NOT NULL CHECK (sms_enabled IN (0, 1)),
                    email_enabled INTEGER NOT NULL CHECK (email_enabled IN (0, 1)),
                    source TEXT NOT NULL DEFAULT 'google_sheets',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_recipients_building_active
                    ON recipients (building_id, active, sms_enabled);

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rows_read INTEGER NOT NULL,
                    accepted INTEGER NOT NULL,
                    rejected INTEGER NOT NULL,
                    inserted INTEGER NOT NULL,
                    updated INTEGER NOT NULL,
                    unchanged INTEGER NOT NULL,
                    deactivated INTEGER NOT NULL,
                    error_message TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    building_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    technical_cause TEXT NOT NULL DEFAULT '',
                    other_description TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL,
                    characters INTEGER NOT NULL,
                    segments INTEGER NOT NULL,
                    recipient_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    test_mode INTEGER NOT NULL CHECK (test_mode IN (0, 1)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    destination_masked TEXT NOT NULL,
                    recipient_name_snapshot TEXT NOT NULL,
                    segments INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (alert_id) REFERENCES alerts(id),
                    FOREIGN KEY (recipient_id) REFERENCES recipients(id)
                );

                CREATE INDEX IF NOT EXISTS idx_deliveries_alert
                    ON deliveries (alert_id);
                """
            )

    @staticmethod
    def _recipient_values(recipient: RecipientRecord) -> tuple[object, ...]:
        return (
            recipient.external_id,
            recipient.sheet_row,
            recipient.name,
            recipient.phone,
            recipient.email,
            recipient.building_id,
            int(recipient.active),
            int(recipient.sms_enabled),
            int(recipient.email_enabled),
        )

    def sync_recipients(self, result: ValidationResult) -> SyncSummary:
        if result.rows_read == 0:
            raise SyncSafetyError(
                "La planilla no contiene destinatarios debajo de los encabezados. "
                "La copia local no fue modificada."
            )
        if not result.recipients:
            raise SyncSafetyError(
                "Ninguna fila superó la validación. La copia local no fue "
                "modificada para evitar perder destinatarios válidos anteriores."
            )

        started_at = now_iso()
        completed_at = started_at
        inserted = 0
        updated = 0
        unchanged = 0
        deactivated = 0

        with self.connect() as connection:
            existing_rows = connection.execute(
                "SELECT * FROM recipients WHERE source = 'google_sheets'"
            ).fetchall()
            existing = {row["source_key"]: row for row in existing_rows}

            for recipient in result.recipients:
                current = existing.get(recipient.source_key)
                new_values = self._recipient_values(recipient)

                if current is None:
                    connection.execute(
                        """
                        INSERT INTO recipients (
                            source_key, external_id, sheet_row, name, phone, email,
                            building_id, active, sms_enabled, email_enabled,
                            source, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'google_sheets', ?, ?)
                        """,
                        (recipient.source_key, *new_values, completed_at, completed_at),
                    )
                    inserted += 1
                    continue

                old_values = (
                    current["external_id"],
                    current["sheet_row"],
                    current["name"],
                    current["phone"],
                    current["email"],
                    current["building_id"],
                    current["active"],
                    current["sms_enabled"],
                    current["email_enabled"],
                )

                if old_values == new_values:
                    unchanged += 1
                    continue

                connection.execute(
                    """
                    UPDATE recipients
                    SET external_id = ?,
                        sheet_row = ?,
                        name = ?,
                        phone = ?,
                        email = ?,
                        building_id = ?,
                        active = ?,
                        sms_enabled = ?,
                        email_enabled = ?,
                        updated_at = ?
                    WHERE source_key = ?
                    """,
                    (*new_values, completed_at, recipient.source_key),
                )
                updated += 1

            for source_key, current in existing.items():
                if source_key in result.seen_source_keys:
                    continue
                if current["active"] or current["sms_enabled"] or current["email_enabled"]:
                    connection.execute(
                        """
                        UPDATE recipients
                        SET active = 0,
                            sms_enabled = 0,
                            email_enabled = 0,
                            updated_at = ?
                        WHERE source_key = ?
                        """,
                        (completed_at, source_key),
                    )
                    deactivated += 1

            status = "success_with_errors" if result.errors else "success"
            cursor = connection.execute(
                """
                INSERT INTO sync_runs (
                    started_at, completed_at, status, rows_read, accepted,
                    rejected, inserted, updated, unchanged, deactivated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    completed_at,
                    status,
                    result.rows_read,
                    len(result.recipients),
                    len(result.errors),
                    inserted,
                    updated,
                    unchanged,
                    deactivated,
                ),
            )
            sync_id = int(cursor.lastrowid)

            active_sms_recipients = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM recipients
                    WHERE active = 1 AND sms_enabled = 1
                    """
                ).fetchone()[0]
            )

        return SyncSummary(
            sync_id=sync_id,
            status=status,
            rows_read=result.rows_read,
            accepted=len(result.recipients),
            rejected=len(result.errors),
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            deactivated=deactivated,
            active_sms_recipients=active_sms_recipients,
            completed_at=completed_at,
        )

    def record_failed_sync(self, error_message: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_runs (
                    started_at, completed_at, status, rows_read, accepted,
                    rejected, inserted, updated, unchanged, deactivated,
                    error_message
                ) VALUES (?, ?, 'failed', 0, 0, 0, 0, 0, 0, 0, ?)
                """,
                (timestamp, timestamp, error_message[:1000]),
            )

    def get_last_sync(self) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def list_recipients(
        self,
        *,
        building_id: str | None = None,
        active_only: bool = False,
        sms_only: bool = False,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[object] = []

        if building_id:
            clauses.append("building_id = ?")
            parameters.append(building_id)
        if active_only:
            clauses.append("active = 1")
        if sms_only:
            clauses.append("sms_enabled = 1")

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = (
            "SELECT * FROM recipients"
            + where
            + " ORDER BY building_id, name COLLATE NOCASE"
        )

        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["phone_masked"] = mask_phone(str(item["phone"]))
            item["email_masked"] = mask_email(str(item["email"]))
            result.append(item)
        return result

    def get_active_sms_recipients(self, building_id: str) -> list[dict[str, object]]:
        return self.list_recipients(
            building_id=building_id,
            active_only=True,
            sms_only=True,
        )

    def count_active_sms_by_building(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT building_id, COUNT(*) AS total
                FROM recipients
                WHERE active = 1 AND sms_enabled = 1
                GROUP BY building_id
                """
            ).fetchall()
        return {str(row["building_id"]): int(row["total"]) for row in rows}

    def create_simulation(
        self,
        *,
        building_id: str,
        alert_type: str,
        technical_cause: str,
        other_description: str,
        preview: MessagePreview,
        recipients: Sequence[dict[str, object]],
    ) -> int:
        if not recipients:
            raise ValueError("No hay destinatarios para registrar la simulación.")

        timestamp = now_iso()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO alerts (
                    building_id, alert_type, technical_cause, other_description,
                    message, characters, segments, recipient_count, status,
                    test_mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SIMULATED', 1, ?)
                """,
                (
                    building_id,
                    alert_type,
                    technical_cause,
                    other_description,
                    preview.message,
                    preview.characters,
                    preview.segments,
                    len(recipients),
                    timestamp,
                ),
            )
            alert_id = int(cursor.lastrowid)

            connection.executemany(
                """
                INSERT INTO deliveries (
                    alert_id, recipient_id, channel, status, destination_masked,
                    recipient_name_snapshot, segments, created_at
                ) VALUES (?, ?, 'SMS', 'SIMULATED', ?, ?, ?, ?)
                """,
                [
                    (
                        alert_id,
                        int(recipient["id"]),
                        str(recipient["phone_masked"]),
                        str(recipient["name"]),
                        preview.segments,
                        timestamp,
                    )
                    for recipient in recipients
                ],
            )

        return alert_id

    def get_alert(self, alert_id: int) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM alerts WHERE id = ?",
                (alert_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_deliveries(self, alert_id: int) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM deliveries
                WHERE alert_id = ?
                ORDER BY id
                """,
                (alert_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_alerts(self, limit: int = 50) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.*,
                       COUNT(d.id) AS delivery_count
                FROM alerts AS a
                LEFT JOIN deliveries AS d ON d.alert_id = a.id
                GROUP BY a.id
                ORDER BY a.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
