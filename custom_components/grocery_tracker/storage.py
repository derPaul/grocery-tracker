"""SQLite storage for receipts and their items.

Money is stored as integer cents. Timestamps are stored as naive local time
(ISO 8601), exactly as printed on the receipt. All methods are blocking and
must be run in the executor from Home Assistant.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sqlite3

from .models import Receipt

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    uid TEXT PRIMARY KEY,
    store TEXT NOT NULL,
    market_id TEXT,
    receipt_number TEXT,
    timestamp TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    payment_method TEXT,
    source TEXT,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receipts_timestamp ON receipts(timestamp);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_uid TEXT NOT NULL REFERENCES receipts(uid) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    quantity TEXT NOT NULL,
    unit TEXT NOT NULL,
    unit_price_cents INTEGER,
    total_cents INTEGER NOT NULL,
    tax_category TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_receipt ON items(receipt_uid);
CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
"""


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value())


def _euros(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class ReceiptSummary:
    """Short summary of a stored receipt."""

    uid: str
    store: str
    timestamp: datetime
    total: Decimal
    item_count: int


@dataclass(frozen=True, slots=True)
class ProductSummary:
    """A product (item name) with its purchase history condensed."""

    name: str
    purchases: int
    last_price: Decimal
    unit: str
    last_seen: datetime


class ReceiptStore:
    """Persist receipts in a SQLite database."""

    def __init__(self, path: Path | str) -> None:
        """Initialize the store; call ``setup`` before use."""
        self._path = str(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def setup(self) -> None:
        """Create the database schema."""
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def add_receipt(self, receipt: Receipt, source: str | None = None) -> bool:
        """Store a receipt; return False if it was already imported."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.uid,
                    receipt.store,
                    receipt.market_id,
                    receipt.receipt_number,
                    receipt.timestamp.isoformat(),
                    _cents(receipt.total),
                    receipt.payment_method,
                    source,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            if cur.rowcount == 0:
                return False
            conn.executemany(
                "INSERT INTO items (receipt_uid, position, name, quantity, unit,"
                " unit_price_cents, total_cents, tax_category)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        receipt.uid,
                        position,
                        item.name,
                        str(item.quantity),
                        item.unit,
                        None if item.unit_price is None else _cents(item.unit_price),
                        _cents(item.total),
                        item.tax_category,
                    )
                    for position, item in enumerate(receipt.items)
                ],
            )
        return True

    def spending_between(self, start: datetime, end: datetime) -> Decimal:
        """Return the total spent in [start, end)."""
        with self._connect() as conn:
            (cents,) = conn.execute(
                "SELECT COALESCE(SUM(total_cents), 0) FROM receipts"
                " WHERE timestamp >= ? AND timestamp < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return _euros(cents)

    def receipt_count_between(self, start: datetime, end: datetime) -> int:
        """Return the number of receipts in [start, end)."""
        with self._connect() as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM receipts WHERE timestamp >= ? AND timestamp < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return count

    def last_receipt(self) -> ReceiptSummary | None:
        """Return the most recent receipt."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT r.uid, r.store, r.timestamp, r.total_cents, COUNT(i.id)"
                " FROM receipts r LEFT JOIN items i ON i.receipt_uid = r.uid"
                " GROUP BY r.uid ORDER BY r.timestamp DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        uid, store, timestamp, total_cents, item_count = row
        return ReceiptSummary(
            uid=uid,
            store=store,
            timestamp=datetime.fromisoformat(timestamp),
            total=_euros(total_cents),
            item_count=item_count,
        )

    def products(self, search: str | None = None) -> list[ProductSummary]:
        """Return all purchased products, most frequently bought first.

        ``last_price`` is the price per unit (piece or kg) of the latest
        purchase. Discount lines are left out.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "WITH ranked AS ("
                " SELECT i.name, i.unit, r.timestamp,"
                "  COALESCE(i.unit_price_cents, i.total_cents) AS price_cents,"
                "  COUNT(*) OVER (PARTITION BY i.name) AS purchases,"
                "  ROW_NUMBER() OVER (PARTITION BY i.name ORDER BY r.timestamp DESC) AS rn"
                " FROM items i JOIN receipts r ON r.uid = i.receipt_uid"
                " WHERE i.total_cents > 0 AND (?1 IS NULL OR instr(upper(i.name), upper(?1)) > 0)"
                ") SELECT name, purchases, price_cents, unit, timestamp FROM ranked"
                " WHERE rn = 1 ORDER BY purchases DESC, name",
                (search,),
            ).fetchall()
        return [
            ProductSummary(
                name=name,
                purchases=purchases,
                last_price=_euros(price_cents),
                unit=unit,
                last_seen=datetime.fromisoformat(timestamp),
            )
            for name, purchases, price_cents, unit, timestamp in rows
        ]
