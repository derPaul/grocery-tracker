"""Coordinator: imports receipts from the inbox and computes statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from pathlib import Path
import shutil
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .categories import resolve_category
from .const import (
    ARCHIVE_DIR,
    CONF_INBOX_PATH,
    CONF_WATCHED_PRODUCTS,
    DOMAIN,
    EVENT_PRICE_CHANGED,
    EVENT_RECEIPT_IMPORTED,
    FAILED_DIR,
    SCAN_INTERVAL,
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


def local_isoformat(value: datetime) -> str:
    """Return a receipt time (naive local time) as ISO 8601 with UTC offset."""
    return value.replace(tzinfo=dt_util.get_default_time_zone()).isoformat()


@dataclass(frozen=True, slots=True)
class GroceryStats:
    """Aggregated values exposed as sensors."""

    spending_this_week: Decimal
    spending_this_month: Decimal
    spending_last_month: Decimal
    receipts_this_month: int
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
        self.inbox = Path(entry.data[CONF_INBOX_PATH])

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
        assigned = self.store.assigned_categories()
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
                    "category": resolve_category(name, assigned),
                    "old_price": float(stats.previous),
                    "new_price": float(stats.last),
                    "change_percent": stats.change_percent,
                    "unit": stats.unit,
                }
            )
        return changes

    def _import_file(self, path: Path) -> tuple[Receipt, bool, list[dict[str, Any]]]:
        """Parse and store one file.

        Return the receipt, whether it was new and the price changes it brought.
        """
        receipt = parse_receipt(extract_text(path))
        if not receipt.is_consistent:
            _LOGGER.warning(
                "%s: items add up to %s EUR, but receipt total is %s EUR",
                path.name,
                receipt.items_total,
                receipt.total,
            )
        if not self.store.add_receipt(receipt, source=path.name):
            return receipt, False, []
        return receipt, True, self._price_changes(receipt)

    async def async_import_file(self, path: Path) -> Receipt | None:
        """Import a single receipt file; return the receipt if it was new."""
        receipt, is_new, price_changes = await self.hass.async_add_executor_job(
            self._import_file, path
        )
        if not is_new:
            _LOGGER.info("%s was already imported, skipping", path.name)
            return None
        _LOGGER.info(
            "Imported %s receipt from %s (%s EUR)", receipt.store, path.name, receipt.total
        )
        self.hass.bus.async_fire(
            EVENT_RECEIPT_IMPORTED,
            {
                "uid": receipt.uid,
                "store": receipt.store,
                "timestamp": local_isoformat(receipt.timestamp),
                "total": float(receipt.total),
                "item_count": len(receipt.items),
            },
        )
        for change in price_changes:
            self.hass.bus.async_fire(EVENT_PRICE_CHANGED, change)
        return receipt

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
            receipts_this_month=self.store.receipt_count_between(month_start, far_future),
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
