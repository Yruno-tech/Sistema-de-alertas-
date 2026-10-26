import asyncio
import os
import threading

from database import SyncSafetyError
from recipient_validation import HeaderValidationError, validate_sheet_values
from sheets_service import SheetsConfigurationError, SheetsReadError, read_sheet_values

_sync_lock = threading.Lock()


def synchronize(database, settings):
    with _sync_lock:
        try:
            result = validate_sheet_values(read_sheet_values(settings))
            summary = database.sync_recipients(result)
            return result, summary, None
        except (SheetsConfigurationError, SheetsReadError, HeaderValidationError, SyncSafetyError) as error:
            database.record_failed_sync(str(error))
            return None, None, str(error)


async def auto_sync(database, settings):
    interval = max(5, int(os.getenv('SHEETS_SYNC_SECONDS', '15')))
    while True:
        if settings.spreadsheet_id and settings.service_account_file.exists():
            await asyncio.to_thread(synchronize, database, settings)
        await asyncio.sleep(interval)
