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


def test_products(tmp_path: Path, rewe_ebon_text: str) -> None:
    store = ReceiptStore(tmp_path / "db.sqlite")
    store.setup()
    store.add_receipt(parse_rewe_ebon(rewe_ebon_text))
    # A later purchase with a more expensive milk.
    later = rewe_ebon_text.replace("Bon-Nr.:4711", "Bon-Nr.:4712").replace(
        "12.03.2024", "19.03.2024"
    )
    later = later.replace(
        "BIO H-MILCH 1,5%                            1,19 B",
        "BIO H-MILCH 1,5%                            1,29 B",
    )
    later = later.replace(
        "RABATT 10%                                 -0,35 B",
        "RABATT 10%                                 -0,25 B",
    )
    store.add_receipt(parse_rewe_ebon(later))

    products = {product.name: product for product in store.products()}

    assert "RABATT 10%" not in products, "discounts are not products"
    milk = products["BIO H-MILCH 1,5%"]
    assert (milk.purchases, milk.last_price, milk.unit) == (2, Decimal("1.29"), "Stk")
    assert milk.last_seen == datetime(2024, 3, 19, 18, 23)
    banana = products["BANANE CHIQUITA"]
    assert (banana.last_price, banana.unit) == (Decimal("1.49"), "kg")
    assert products["PFAND 0,25 EURO"].last_price == Decimal("0.25")

    assert [p.name for p in store.products(search="milch")] == ["BIO H-MILCH 1,5%"]
