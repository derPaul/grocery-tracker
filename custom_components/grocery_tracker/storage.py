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

from .categories import OTHER, CategoryResolver, CustomCategory
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
CREATE TABLE IF NOT EXISTS mail_state (
    mailbox TEXT PRIMARY KEY,
    uidvalidity INTEGER,
    last_uid INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS product_categories (
    name TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    source TEXT NOT NULL
);
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


@dataclass(frozen=True, slots=True)
class ItemDetail:
    """One line of a stored receipt."""

    name: str
    category: str
    quantity: Decimal
    unit: str
    unit_price: Decimal | None
    total: Decimal


@dataclass(frozen=True, slots=True)
class ProductSpending:
    """Amount spent on one product in a period."""

    name: str
    category: str
    amount: Decimal
    purchases: int


@dataclass(frozen=True, slots=True)
class PricePoint:
    """Price per piece / kg of one purchase."""

    timestamp: datetime
    price: Decimal
    unit: str
    receipt_uid: str


@dataclass(frozen=True, slots=True)
class PriceStats:
    """Price history of a product condensed."""

    last: Decimal
    previous: Decimal | None
    minimum: Decimal
    maximum: Decimal
    average: Decimal
    unit: str
    purchases: int
    last_seen: datetime

    @property
    def change_percent(self) -> float | None:
        """Return the change from the previous to the last price in percent."""
        if not self.previous:
            return None
        return round(float((self.last - self.previous) / self.previous * 100), 1)


class ReceiptStore:
    """Persist receipts in a SQLite database."""

    def __init__(self, path: Path | str) -> None:
        """Initialize the store; call ``setup`` before use."""
        self._path = str(path)
        self.custom_categories: list[CustomCategory] = []

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

    def monthly_spending(self, start: datetime, end: datetime) -> dict[str, tuple[Decimal, int]]:
        """Return amount and number of receipts per month ("YYYY-MM") in [start, end)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT substr(timestamp, 1, 7) AS month, SUM(total_cents), COUNT(*)"
                " FROM receipts WHERE timestamp >= ? AND timestamp < ?"
                " GROUP BY month",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return {month: (_euros(cents), count) for month, cents, count in rows}

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

    def has_product(self, name: str) -> bool:
        """Return True if a product with exactly this name was ever bought."""
        with self._connect() as conn:
            return (
                conn.execute("SELECT 1 FROM items WHERE name = ? LIMIT 1", (name,)).fetchone()
                is not None
            )

    def mail_state(self, mailbox: str) -> tuple[int | None, int]:
        """Return (UIDVALIDITY, last processed UID) of a mailbox."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT uidvalidity, last_uid FROM mail_state WHERE mailbox = ?", (mailbox,)
            ).fetchone()
        return (row[0], row[1]) if row else (None, 0)

    def set_mail_state(self, mailbox: str, uidvalidity: int | None, last_uid: int) -> None:
        """Remember the last processed message of a mailbox."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mail_state VALUES (?, ?, ?)",
                (mailbox, uidvalidity, last_uid),
            )

    def delete_mail_state(self, mailbox: str) -> None:
        """Forget a mailbox, so it is scanned from the start again."""
        with self._connect() as conn:
            conn.execute("DELETE FROM mail_state WHERE mailbox = ?", (mailbox,))

    def assigned_categories(self) -> dict[str, str]:
        """Return the stored (manual or AI) category per product name."""
        with self._connect() as conn:
            return dict(conn.execute("SELECT name, category FROM product_categories"))

    def resolver(self) -> CategoryResolver:
        """Return a resolver with the stored assignments and custom categories."""
        with self._connect() as conn:
            rows = conn.execute("SELECT name, category, source FROM product_categories").fetchall()
        return CategoryResolver(
            self.custom_categories,
            manual={name: category for name, category, source in rows if source == "manual"},
            ai={name: category for name, category, source in rows if source != "manual"},
        )

    def set_category(self, name: str, category: str, source: str) -> None:
        """Store the category of a product; ``source`` is "manual" or "ai"."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO product_categories VALUES (?, ?, ?)",
                (name, category, source),
            )

    def spending_by_category(self, start: datetime, end: datetime) -> dict[str, Decimal]:
        """Return the amount spent per category in [start, end).

        Discount lines belong to the item printed right above them.
        """
        resolver = self.resolver()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT i.receipt_uid, i.name, i.total_cents"
                " FROM items i JOIN receipts r ON r.uid = i.receipt_uid"
                " WHERE r.timestamp >= ? AND r.timestamp < ?"
                " ORDER BY r.timestamp, i.receipt_uid, i.position",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        cents = dict.fromkeys(resolver.keys, 0)
        prev: tuple[str, str] | None = None  # (receipt uid, category) of the last item
        for receipt_uid, name, total_cents in rows:
            if total_cents < 0 and prev is not None and prev[0] == receipt_uid:
                category = prev[1]
            elif total_cents < 0:
                category = OTHER
            else:
                category = resolver.resolve(name)
                prev = (receipt_uid, category)
            cents[category] += total_cents
        return {category: _euros(value) for category, value in cents.items()}

    def receipt_items(self, uid: str) -> list[ItemDetail]:
        """Return the lines of a receipt; discounts get the category of the item above."""
        resolver = self.resolver()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, quantity, unit, unit_price_cents, total_cents FROM items"
                " WHERE receipt_uid = ? ORDER BY position",
                (uid,),
            ).fetchall()
        items: list[ItemDetail] = []
        for name, quantity, unit, unit_price_cents, total_cents in rows:
            if total_cents < 0:
                category = items[-1].category if items else OTHER
            else:
                category = resolver.resolve(name)
            items.append(
                ItemDetail(
                    name=name,
                    category=category,
                    quantity=Decimal(quantity),
                    unit=unit,
                    unit_price=None if unit_price_cents is None else _euros(unit_price_cents),
                    total=_euros(total_cents),
                )
            )
        return items

    def top_products(
        self, start: datetime, end: datetime, limit: int = 10
    ) -> list[ProductSpending]:
        """Return the products with the highest spending in [start, end)."""
        resolver = self.resolver()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT i.name, SUM(i.total_cents) AS cents, COUNT(*)"
                " FROM items i JOIN receipts r ON r.uid = i.receipt_uid"
                " WHERE r.timestamp >= ? AND r.timestamp < ? AND i.total_cents > 0"
                " GROUP BY i.name ORDER BY cents DESC, i.name LIMIT ?",
                (start.isoformat(), end.isoformat(), limit),
            ).fetchall()
        return [
            ProductSpending(
                name=name,
                category=resolver.resolve(name),
                amount=_euros(cents),
                purchases=purchases,
            )
            for name, cents, purchases in rows
        ]

    def price_history(self, name: str) -> list[PricePoint]:
        """Return the price per piece / kg of every purchase, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT r.timestamp, COALESCE(i.unit_price_cents, i.total_cents), i.unit, r.uid"
                " FROM items i JOIN receipts r ON r.uid = i.receipt_uid"
                " WHERE i.name = ? AND i.total_cents > 0"
                " ORDER BY r.timestamp, i.position",
                (name,),
            ).fetchall()
        return [
            PricePoint(
                timestamp=datetime.fromisoformat(timestamp),
                price=_euros(cents),
                unit=unit,
                receipt_uid=uid,
            )
            for timestamp, cents, unit, uid in rows
        ]

    def price_stats(self, name: str) -> PriceStats | None:
        """Return the condensed price history of a product."""
        if not (history := self.price_history(name)):
            return None
        last = history[-1]
        # The previous price is the one from an earlier receipt, not a second
        # line of the same receipt.
        earlier = [point for point in history if point.receipt_uid != last.receipt_uid]
        prices = [point.price for point in history]
        return PriceStats(
            last=last.price,
            previous=earlier[-1].price if earlier else None,
            minimum=min(prices),
            maximum=max(prices),
            average=(sum(prices) / len(prices)).quantize(Decimal("0.01")),
            unit=last.unit,
            purchases=len(history),
            last_seen=last.timestamp,
        )
