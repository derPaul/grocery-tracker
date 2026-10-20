"""Coordinator: imports receipts from the inbox and computes statistics."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
from pathlib import Path
import shutil
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_DESCRIPTION, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.ssl import client_context

from .categories import CustomCategory, parse_keywords
from .const import (
    ARCHIVE_DIR,
    CONF_FOLDER,
    CONF_INBOX_PATH,
    CONF_KEY,
    CONF_KEYWORDS,
    CONF_SENDER,
    CONF_SERVER,
    CONF_SINCE,
    CONF_WATCHED_PRODUCTS,
    DOMAIN,
    EVENT_PRICE_CHANGED,
    EVENT_RECEIPT_IMPORTED,
    FAILED_DIR,
    SCAN_INTERVAL,
    SUBENTRY_CATEGORY,
    SUBENTRY_MAILBOX,
)
from .mail import (
    MailAuthError,
    Mailbox,
    MailboxConfig,
    MailConnectionError,
    MailFolderError,
)
from .models import Receipt
from .parsers import ReceiptParseError, parse_receipt
from .pdf import extract_text
from .storage import (
    ItemDetail,
    PriceStats,
    ProductSpending,
    ReceiptStore,
    ReceiptSummary,
)

_LOGGER = logging.getLogger(__name__)

type GroceryTrackerConfigEntry = ConfigEntry[GroceryTrackerCoordinator]


def custom_categories(entry: ConfigEntry) -> list[CustomCategory]:
    """Return the categories the user added as subentries."""
    return [
        CustomCategory(
            key=subentry.data[CONF_KEY],
            name=subentry.data[CONF_NAME],
            keywords=parse_keywords(subentry.data.get(CONF_KEYWORDS, "")),
            description=subentry.data.get(CONF_DESCRIPTION, ""),
        )
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_CATEGORY
    ]


def mailbox_config(data: Mapping[str, Any]) -> MailboxConfig:
    """Return the connection settings stored in a mailbox subentry."""
    return MailboxConfig(
        server=data[CONF_SERVER],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        folder=data[CONF_FOLDER],
        sender=data[CONF_SENDER],
        since=date.fromisoformat(data[CONF_SINCE]),
    )


def local_isoformat(value: datetime) -> str:
    """Return a receipt time (naive local time) as ISO 8601 with UTC offset."""
    return value.replace(tzinfo=dt_util.get_default_time_zone()).isoformat()


MAILBOX_OK = "ok"
MAILBOX_AUTH_FAILED = "auth_failed"
MAILBOX_FOLDER_NOT_FOUND = "folder_not_found"
MAILBOX_UNREACHABLE = "unreachable"
MAILBOX_ERROR = "error"
MAILBOX_STATES = [
    MAILBOX_OK,
    MAILBOX_AUTH_FAILED,
    MAILBOX_FOLDER_NOT_FOUND,
    MAILBOX_UNREACHABLE,
    MAILBOX_ERROR,
]


@dataclass(frozen=True, slots=True)
class MailboxStatus:
    """Outcome of the last check of a mailbox."""

    last_check: datetime
    status: str
    new_messages: int = 0
    new_receipts: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class GroceryStats:
    """Aggregated values exposed as sensors."""

    spending_this_week: Decimal
    spending_this_month: Decimal
    spending_last_month: Decimal
    spending_this_year: Decimal
    receipts_this_month: int
    receipts_total: int
    last_12_months: list[tuple[str, Decimal, int]]
    last_receipt: ReceiptSummary | None
    spending_by_category_this_month: dict[str, Decimal]
    last_receipt_items: list[ItemDetail]
    top_products_this_month: list[ProductSpending]
    prices: dict[str, PriceStats | None]


class GroceryTrackerCoordinator(DataUpdateCoordinator[GroceryStats]):
    """Scan the inbox folder for new receipts and refresh statistics."""

    config_entry: GroceryTrackerConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: GroceryTrackerConfigEntry, store: ReceiptStore
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.store = store
        store.custom_categories = custom_categories(entry)
        self.inbox = Path(entry.data[CONF_INBOX_PATH])
        self._mail_lock = asyncio.Lock()
        self.mailbox_status: dict[str, MailboxStatus] = {}

    @property
    def watched_products(self) -> list[str]:
        """Return the products whose price is tracked as a sensor."""
        return self.config_entry.options.get(CONF_WATCHED_PRODUCTS, [])

    def _ensure_dirs(self) -> None:
        for directory in (self.inbox, self.inbox / ARCHIVE_DIR, self.inbox / FAILED_DIR):
            directory.mkdir(parents=True, exist_ok=True)

    async def async_setup(self) -> None:
        """Create the inbox folders and the database."""
        await self.hass.async_add_executor_job(self._ensure_dirs)
        await self.hass.async_add_executor_job(self.store.setup)

    def _price_changes(self, receipt: Receipt) -> list[dict[str, Any]]:
        """Return event data for products whose price changed with this receipt."""
        resolver = self.store.resolver()
        changes = []
        for name in dict.fromkeys(item.name for item in receipt.items if item.total > 0):
            stats = self.store.price_stats(name)
            # Skip if an older receipt was imported late, the price is not new then.
            if (
                stats is None
                or stats.previous is None
                or stats.last == stats.previous
                or stats.last_seen != receipt.timestamp
            ):
                continue
            changes.append(
                {
                    "product": name,
                    "category": resolver.resolve(name),
                    "old_price": float(stats.previous),
                    "new_price": float(stats.last),
                    "change_percent": stats.change_percent,
                    "unit": stats.unit,
                }
            )
        return changes

    def _import_pdf(self, source: str, pdf: Path | bytes) -> tuple[Receipt, list[tuple[str, dict]]]:
        """Parse and store one PDF.

        Return the receipt and the events to fire; no events if it was imported before.
        """
        receipt = parse_receipt(extract_text(pdf))
        if not receipt.is_consistent:
            _LOGGER.warning(
                "%s: items add up to %s EUR, but receipt total is %s EUR",
                source,
                receipt.items_total,
                receipt.total,
            )
        if not self.store.add_receipt(receipt, source=source):
            _LOGGER.info("%s was already imported, skipping", source)
            return receipt, []
        _LOGGER.info("Imported %s receipt from %s (%s EUR)", receipt.store, source, receipt.total)
        imported = {
            "uid": receipt.uid,
            "store": receipt.store,
            "timestamp": local_isoformat(receipt.timestamp),
            "total": float(receipt.total),
            "item_count": len(receipt.items),
        }
        return receipt, [
            (EVENT_RECEIPT_IMPORTED, imported),
            *((EVENT_PRICE_CHANGED, change) for change in self._price_changes(receipt)),
        ]

    async def async_import_file(self, path: Path) -> Receipt | None:
        """Import a single receipt file; return the receipt if it was new."""
        receipt, events = await self.hass.async_add_executor_job(self._import_pdf, path.name, path)
        for event_type, data in events:
            self.hass.bus.async_fire(event_type, data)
        return receipt if events else None

    def _scan_inbox(self) -> list[Path]:
        return sorted(p for p in self.inbox.glob("*") if p.is_file() and p.suffix.lower() == ".pdf")

    async def _async_import_inbox(self) -> None:
        for path in await self.hass.async_add_executor_job(self._scan_inbox):
            target_dir = ARCHIVE_DIR
            try:
                await self.async_import_file(path)
            except ReceiptParseError as err:
                _LOGGER.error("Could not parse %s: %s", path.name, err)
                target_dir = FAILED_DIR
            except Exception:
                _LOGGER.exception("Unexpected error importing %s", path.name)
                target_dir = FAILED_DIR
            await self.hass.async_add_executor_job(
                shutil.move, path, self.inbox / target_dir / path.name
            )

    def _check_mailbox(self, key: str, config: MailboxConfig) -> tuple[int, int]:
        """Import receipts from new messages.

        Return the number of new messages and of newly imported receipts.

        Runs in the executor, so events are fired with the thread-safe API.
        """
        uidvalidity, last_uid = self.store.mail_state(key)
        messages = imported = 0
        with Mailbox(config, client_context()) as mailbox:
            if mailbox.uidvalidity != uidvalidity:
                # UIDs were reassigned by the server: start over, duplicates are skipped.
                last_uid = 0
            for message in mailbox.messages(after_uid=last_uid):
                messages += 1
                for filename, data in message.pdfs:
                    source = f"mail {message.uid}: {filename}"
                    try:
                        _, events = self._import_pdf(source, data)
                    except Exception as err:
                        if isinstance(err, ReceiptParseError):
                            _LOGGER.error("Could not parse %s: %s", source, err)
                        else:
                            _LOGGER.exception("Unexpected error importing %s", source)
                        # The file name comes from the email: keep only the base name.
                        name = Path(filename).name or "receipt.pdf"
                        try:
                            (self.inbox / FAILED_DIR / f"mail-{message.uid}-{name}").write_bytes(
                                data
                            )
                        except OSError as write_err:
                            _LOGGER.warning("Could not keep %s: %s", source, write_err)
                        continue
                    for event_type, event_data in events:
                        self.hass.bus.fire(event_type, event_data)
                    imported += bool(events)
                # Remember progress per message, so an interruption loses nothing.
                self.store.set_mail_state(key, mailbox.uidvalidity, message.uid)
        return messages, imported

    def _mailboxes(self) -> list[ConfigSubentry]:
        return [
            subentry
            for subentry in self.config_entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_MAILBOX
        ]

    async def async_check_mailboxes(self) -> dict[str, MailboxStatus]:
        """Import receipts from all configured mailboxes; return their status.

        A check that is requested while one is running waits for it and then
        runs again, so it never misses a message that just arrived.
        """
        async with self._mail_lock:
            imported = 0
            for subentry in self._mailboxes():
                issue_id = f"mailbox_{subentry.subentry_id}"
                config = mailbox_config(subentry.data)
                now = dt_util.now()
                try:
                    messages, receipts = await self.hass.async_add_executor_job(
                        self._check_mailbox, config.search_key, config
                    )
                except (MailAuthError, MailFolderError) as err:
                    self.mailbox_status[subentry.subentry_id] = MailboxStatus(
                        now,
                        MAILBOX_AUTH_FAILED
                        if isinstance(err, MailAuthError)
                        else MAILBOX_FOLDER_NOT_FOUND,
                        error=str(err),
                    )
                    _LOGGER.error("Mailbox %s: %s", subentry.title, err)
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        issue_id,
                        is_fixable=False,
                        severity=ir.IssueSeverity.ERROR,
                        translation_key=(
                            "mailbox_auth_failed"
                            if isinstance(err, MailAuthError)
                            else "mailbox_folder_not_found"
                        ),
                        translation_placeholders={
                            "mailbox": subentry.title,
                            "folder": subentry.data[CONF_FOLDER],
                        },
                    )
                except MailConnectionError as err:
                    # Temporary (network, server); try again at the next interval.
                    _LOGGER.warning("Mailbox %s not reachable: %s", subentry.title, err)
                    self.mailbox_status[subentry.subentry_id] = MailboxStatus(
                        now, MAILBOX_UNREACHABLE, error=str(err)
                    )
                except Exception as err:
                    # A bug or an unexpected server answer: show it instead of failing silently.
                    _LOGGER.exception("Error checking mailbox %s", subentry.title)
                    self.mailbox_status[subentry.subentry_id] = MailboxStatus(
                        now, MAILBOX_ERROR, error=f"{type(err).__name__}: {err}"
                    )
                else:
                    _LOGGER.info(
                        "Mailbox %s checked: %d new messages, %d new receipts",
                        subentry.title,
                        messages,
                        receipts,
                    )
                    self.mailbox_status[subentry.subentry_id] = MailboxStatus(
                        now, MAILBOX_OK, messages, receipts
                    )
                    imported += receipts
                    ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            if imported:
                await self.async_refresh()
            else:
                # Only the mailbox status changed.
                self.async_update_listeners()
            return dict(self.mailbox_status)

    def _last_12_months(self, month_start: datetime) -> list[tuple[str, Decimal, int]]:
        """Return (month, amount, receipts) for the current and the 11 previous months."""
        months = [month_start]
        while len(months) < 12:
            months.append((months[-1] - timedelta(days=1)).replace(day=1))
        months.reverse()
        spending = self.store.monthly_spending(months[0], datetime.max)
        result = []
        for month in months:
            key = month.strftime("%Y-%m")
            amount, receipts = spending.get(key, (Decimal("0.00"), 0))
            result.append((key, amount, receipts))
        return result

    def _compute_stats(self, now: datetime) -> GroceryStats:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)
        far_future = datetime.max
        last = self.store.last_receipt()
        return GroceryStats(
            spending_this_week=self.store.spending_between(week_start, far_future),
            spending_this_month=self.store.spending_between(month_start, far_future),
            spending_last_month=self.store.spending_between(last_month_start, month_start),
            spending_this_year=self.store.spending_between(
                today.replace(month=1, day=1), far_future
            ),
            receipts_this_month=self.store.receipt_count_between(month_start, far_future),
            receipts_total=self.store.receipt_count_between(datetime.min, far_future),
            last_12_months=self._last_12_months(month_start),
            last_receipt=last,
            spending_by_category_this_month=self.store.spending_by_category(
                month_start, far_future
            ),
            last_receipt_items=self.store.receipt_items(last.uid) if last else [],
            top_products_this_month=self.store.top_products(month_start, far_future),
            prices={name: self.store.price_stats(name) for name in self.watched_products},
        )

    async def _async_update_data(self) -> GroceryStats:
        await self._async_import_inbox()
        # Receipts carry naive local time, so compare against naive local now.
        now = dt_util.now().replace(tzinfo=None)
        return await self.hass.async_add_executor_job(self._compute_stats, now)
