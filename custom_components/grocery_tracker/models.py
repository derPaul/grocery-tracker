"""Data models for parsed receipts.

These are plain dataclasses without any Home Assistant dependency so the
parsers and the storage layer can be used and tested on their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ReceiptItem:
    """A single line on a receipt (product, deposit or discount)."""

    name: str
    total: Decimal
    quantity: Decimal = Decimal(1)
    unit: str = "Stk"
    unit_price: Decimal | None = None
    tax_category: str | None = None

    @property
    def is_discount(self) -> bool:
        """Return True for discount / coupon lines."""
        return self.total < 0


@dataclass(slots=True)
class Receipt:
    """A complete, parsed receipt."""

    store: str
    timestamp: datetime
    total: Decimal
    items: list[ReceiptItem] = field(default_factory=list)
    market_id: str | None = None
    receipt_number: str | None = None
    payment_method: str | None = None
    address: str | None = None

    @property
    def uid(self) -> str:
        """Return a stable identifier used to detect duplicate imports."""
        return "-".join(
            (
                self.store.lower(),
                self.market_id or "0",
                self.timestamp.strftime("%Y%m%d%H%M"),
                self.receipt_number or "0",
            )
        )

    @property
    def items_total(self) -> Decimal:
        """Return the sum of all item lines."""
        return sum((item.total for item in self.items), Decimal(0))

    @property
    def is_consistent(self) -> bool:
        """Return True if the item lines add up to the receipt total."""
        return self.items_total == self.total
