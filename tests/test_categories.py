"""Tests for the keyword category rules."""

from __future__ import annotations

import pytest

from custom_components.grocery_tracker.categories import (
    BAKERY,
    BEVERAGES,
    DAIRY_EGGS,
    DEPOSIT,
    DRUGSTORE_HOUSEHOLD,
    FRUIT_VEGETABLES,
    MEAT_FISH,
    OTHER,
    PANTRY,
    SNACKS_SWEETS,
    categorize,
    resolve_category,
)


@pytest.mark.parametrize(
    ("name", "category"),
    [
        # Real product names from REWE eBons.
        ("APFEL CRIPPSPINK", FRUIT_VEGETABLES),
        ("GRANATAPEL", FRUIT_VEGETABLES),
        ("ROMARISPENTOM.", FRUIT_VEGETABLES),
        ("FELDSALAT BIO", FRUIT_VEGETABLES),
        ("BIO KOKOSMILCH", PANTRY),
        ("FR. WEIDEMILCH", DAIRY_EGGS),
        ("BIO MINI-MOZZAR.", DAIRY_EGGS),
        ("MEGGLE STREICHZA", DAIRY_EGGS),
        ("BIO EIER", DAIRY_EGGS),
        ("KAROTTENKRUEST.", BAKERY),
        ("WALN.HONIG BROE.", BAKERY),
        ("SCHWEIZER WECKLI", BAKERY),
        ("TOASTBROET.KOE", BAKERY),
        ("LINSEN CHIPS", SNACKS_SWEETS),
        ("KINDER UE-EI", SNACKS_SWEETS),
        ("MINI WIENER", MEAT_FISH),
        ("TOFU NATUR", MEAT_FISH),
        ("PRINZ.LILLI TEE", BEVERAGES),
        ("YOGI HALSWAERMER", BEVERAGES),
        ("ZEWA ULTRA SOFT", DRUGSTORE_HOUSEHOLD),
        ("TASCHENTUECHER", DRUGSTORE_HOUSEHOLD),
        ("PFAND 0,25 EURO", DEPOSIT),
        ("BUCHSTABENNUDELN", PANTRY),
    ],
)
def test_rules(name: str, category: str) -> None:
    assert categorize(name) == category


def test_unknown() -> None:
    assert categorize("JAP. CLASSIC") is None
    assert resolve_category("JAP. CLASSIC", {}) == OTHER


def test_assigned_category_wins() -> None:
    assert resolve_category("MINI WIENER", {"MINI WIENER": SNACKS_SWEETS}) == SNACKS_SWEETS
