"""Tests for the REWE eBon parser."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from custom_components.grocery_tracker.parsers import ReceiptParseError, parse_receipt
from custom_components.grocery_tracker.parsers.rewe import parse_rewe_ebon


def test_parse_header_and_total(rewe_ebon_text: str) -> None:
    receipt = parse_rewe_ebon(rewe_ebon_text)

    assert receipt.store == "REWE"
    assert receipt.total == Decimal("10.60")
    assert receipt.timestamp == datetime(2024, 3, 12, 18, 23)
    assert receipt.receipt_number == "4711"
    assert receipt.market_id == "1234"
    assert receipt.payment_method == "EC-Cash"
    assert receipt.uid == "rewe-1234-202403121823-4711"


def test_parse_items(rewe_ebon_text: str) -> None:
    receipt = parse_rewe_ebon(rewe_ebon_text)

    assert [item.name for item in receipt.items] == [
        "BIO H-MILCH 1,5%",
        "GOUDA JUNG",
        "PFAND 0,25 EURO",
        "BANANE CHIQUITA",
        "SPUELMITTEL",
        "MINERALWASSER",
        "RABATT 10%",
    ]
    assert receipt.is_consistent

    milk, _, deposit, banana, _, water, discount = receipt.items
    assert (milk.total, milk.quantity, milk.unit, milk.tax_category) == (
        Decimal("1.19"),
        Decimal(1),
        "Stk",
        "B",
    )
    assert (deposit.quantity, deposit.unit_price, deposit.tax_category) == (
        Decimal(2),
        Decimal("0.25"),
        "A",
    )
    assert (banana.quantity, banana.unit, banana.unit_price) == (
        Decimal("0.994"),
        "kg",
        Decimal("1.49"),
    )
    assert water.quantity == Decimal(6)
    assert discount.total == Decimal("-0.35")
    assert discount.is_discount


def test_parse_receipt_detects_rewe(rewe_ebon_text: str) -> None:
    assert parse_receipt(rewe_ebon_text).store == "REWE"


def test_unknown_format() -> None:
    with pytest.raises(ReceiptParseError):
        parse_receipt("ALDI SÜD\nSumme 12,00")


def test_missing_date_raises(rewe_ebon_text: str) -> None:
    text = rewe_ebon_text.replace("Bon-Nr.:4711", "")
    with pytest.raises(ReceiptParseError, match="date"):
        parse_rewe_ebon(text)
