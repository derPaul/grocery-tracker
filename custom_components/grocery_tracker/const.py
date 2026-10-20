"""Constants for the Grocery Tracker integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "grocery_tracker"

CONF_INBOX_PATH: Final = "inbox_path"

DEFAULT_INBOX_DIR: Final = "grocery_tracker/inbox"
DATABASE_FILE: Final = "grocery_tracker.db"
ARCHIVE_DIR: Final = "archive"
FAILED_DIR: Final = "failed"

SCAN_INTERVAL: Final = timedelta(minutes=5)

SERVICE_IMPORT_RECEIPT: Final = "import_receipt"
ATTR_PATH: Final = "path"

EVENT_RECEIPT_IMPORTED: Final = f"{DOMAIN}_receipt_imported"
