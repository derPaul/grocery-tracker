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


def test_products(tmp_path: Path, rewe_ebon_text: str, rewe_ebon_text_later: str) -> None:
    store = ReceiptStore(tmp_path / "db.sqlite")
    store.setup()
    store.add_receipt(parse_rewe_ebon(rewe_ebon_text))
    store.add_receipt(parse_rewe_ebon(rewe_ebon_text_later))

    products = {product.name: product for product in store.products()}

    assert "RABATT 10%" not in products, "discounts are not products"
    milk = products["BIO H-MILCH 1,5%"]
    assert (milk.purchases, milk.last_price, milk.unit) == (2, Decimal("1.29"), "Stk")
    assert milk.last_seen == datetime(2024, 3, 19, 18, 23)
    banana = products["BANANE CHIQUITA"]
    assert (banana.last_price, banana.unit) == (Decimal("1.49"), "kg")
    assert products["PFAND 0,25 EURO"].last_price == Decimal("0.25")

    assert [p.name for p in store.products(search="milch")] == ["BIO H-MILCH 1,5%"]


def test_spending_by_category(tmp_path: Path, rewe_ebon_text: str) -> None:
    store = ReceiptStore(tmp_path / "db.sqlite")
    store.setup()
    store.add_receipt(parse_rewe_ebon(rewe_ebon_text))
    march = (datetime(2024, 3, 1), datetime(2024, 4, 1))

    spending = store.spending_by_category(*march)

    assert spending["dairy_eggs"] == Decimal("3.48")
    assert spending["deposit"] == Decimal("0.50")
    assert spending["fruit_vegetables"] == Decimal("1.48")
    assert spending["drugstore_household"] == Decimal("1.95")
    # The discount line is printed below the water and reduces its category.
    assert spending["beverages"] == Decimal("3.19")
    assert spending["other"] == Decimal("0.00")
    assert sum(spending.values()) == Decimal("10.60")

    store.set_category("GOUDA JUNG", "other", "manual")
    assert store.assigned_categories() == {"GOUDA JUNG": "other"}
    spending = store.spending_by_category(*march)
    assert spending["dairy_eggs"] == Decimal("1.19")
    assert spending["other"] == Decimal("2.29")

    assert store.has_product("GOUDA JUNG")
    assert not store.has_product("GOUDA")


def test_receipt_items_and_top_products(tmp_path: Path, rewe_ebon_text: str) -> None:
    store = ReceiptStore(tmp_path / "db.sqlite")
    store.setup()
    receipt = parse_rewe_ebon(rewe_ebon_text)
    store.add_receipt(receipt)

    items = store.receipt_items(receipt.uid)
    assert [item.name for item in items] == [item.name for item in receipt.items]
    banana = items[3]
    assert (banana.category, banana.quantity, banana.unit, banana.unit_price, banana.total) == (
        "fruit_vegetables",
        Decimal("0.994"),
        "kg",
        Decimal("1.49"),
        Decimal("1.48"),
    )
    discount = items[-1]
    assert (discount.category, discount.total) == ("beverages", Decimal("-0.35"))

    top = store.top_products(datetime(2024, 3, 1), datetime(2024, 4, 1), limit=2)
    assert [(p.name, p.category, p.amount) for p in top] == [
        ("MINERALWASSER", "beverages", Decimal("3.54")),
        ("GOUDA JUNG", "dairy_eggs", Decimal("2.29")),
    ]


def test_price_stats(tmp_path: Path, rewe_ebon_text: str, rewe_ebon_text_later: str) -> None:
    store = ReceiptStore(tmp_path / "db.sqlite")
    store.setup()
    assert store.price_stats("BIO H-MILCH 1,5%") is None

    store.add_receipt(parse_rewe_ebon(rewe_ebon_text))
    stats = store.price_stats("BIO H-MILCH 1,5%")
    assert (stats.last, stats.previous, stats.change_percent) == (Decimal("1.19"), None, None)

    store.add_receipt(parse_rewe_ebon(rewe_ebon_text_later))
    stats = store.price_stats("BIO H-MILCH 1,5%")
    assert (stats.last, stats.previous, stats.minimum, stats.maximum, stats.average) == (
        Decimal("1.29"),
        Decimal("1.19"),
        Decimal("1.19"),
        Decimal("1.29"),
        Decimal("1.24"),
    )
    assert stats.change_percent == 8.4
    assert (stats.unit, stats.purchases) == ("Stk", 2)
    assert stats.last_seen == datetime(2024, 3, 19, 18, 23)

    # Weighed products are priced per kg, multi-packs per piece.
    assert store.price_stats("BANANE CHIQUITA").last == Decimal("1.49")
    assert store.price_stats("BANANE CHIQUITA").unit == "kg"
    assert store.price_stats("MINERALWASSER").last == Decimal("0.59")
