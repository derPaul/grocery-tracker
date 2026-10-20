"""Tests for the SQLite receipt store."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from custom_components.grocery_tracker.parsers.rewe import parse_rewe_ebon
from custom_components.grocery_tracker.storage import ReceiptStore


def test_add_and_query(tmp_path: Path, rewe_ebon_text: str) -> None:
    store = ReceiptStore(tmp_path / "db.sqlite")
    store.setup()
    receipt = parse_rewe_ebon(rewe_ebon_text)

    assert store.add_receipt(receipt, source="ebon.pdf")
    assert not store.add_receipt(receipt), "duplicate must be ignored"

    march = (datetime(2024, 3, 1), datetime(2024, 4, 1))
    assert store.spending_between(*march) == Decimal("10.60")
    assert store.receipt_count_between(*march) == 1
    assert store.spending_between(datetime(2024, 4, 1), datetime(2024, 5, 1)) == Decimal("0.00")

    last = store.last_receipt()
    assert last is not None
    assert (last.store, last.total, last.item_count) == ("REWE", Decimal("10.60"), 7)


def test_empty_store(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / "db.sqlite")
    store.setup()
    assert store.last_receipt() is None
