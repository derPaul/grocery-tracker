"""Constants for the Grocery Tracker integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "grocery_tracker"

CONF_INBOX_PATH: Final = "inbox_path"
CONF_WATCHED_PRODUCTS: Final = "watched_products"

SUBENTRY_MAILBOX: Final = "mailbox"
CONF_SERVER: Final = "server"
CONF_FOLDER: Final = "folder"
CONF_SENDER: Final = "sender"
CONF_SINCE: Final = "since"

DEFAULT_INBOX_DIR: Final = "grocery_tracker/inbox"
DATABASE_FILE: Final = "grocery_tracker.db"
ARCHIVE_DIR: Final = "archive"
FAILED_DIR: Final = "failed"

SCAN_INTERVAL: Final = timedelta(minutes=5)
MAIL_SCAN_INTERVAL: Final = timedelta(minutes=15)

SERVICE_IMPORT_RECEIPT: Final = "import_receipt"
SERVICE_LIST_PRODUCTS: Final = "list_products"
SERVICE_SET_CATEGORY: Final = "set_category"
SERVICE_CATEGORIZE_PRODUCTS: Final = "categorize_products"
ATTR_PATH: Final = "path"
ATTR_SEARCH: Final = "search"
ATTR_PRODUCT: Final = "product"
ATTR_CATEGORY: Final = "category"
ATTR_ENTITY_ID: Final = "entity_id"

EVENT_RECEIPT_IMPORTED: Final = f"{DOMAIN}_receipt_imported"
EVENT_PRICE_CHANGED: Final = f"{DOMAIN}_price_changed"
