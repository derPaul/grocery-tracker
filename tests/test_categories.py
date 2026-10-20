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
    CategoryResolver,
    CustomCategory,
    categorize,
    parse_keywords,
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
    resolver = CategoryResolver()
    assert resolver.resolve("JAP. CLASSIC") == OTHER
    assert resolver.is_unknown("JAP. CLASSIC")
    assert not resolver.is_unknown("MINI WIENER")


BABY = CustomCategory(
    key="custom_baby",
    name="Baby",
    keywords=parse_keywords("windel, Hipp, Brei für"),
    description="",
)


def test_keywords_are_normalized() -> None:
    assert BABY.keywords == ("WINDEL", "HIPP", "BREI FUER")


def test_resolution_order() -> None:
    resolver = CategoryResolver(
        [BABY],
        manual={"HIPP APFEL": SNACKS_SWEETS},
        ai={"WINDELN GR.4": FRUIT_VEGETABLES, "JAP. CLASSIC": SNACKS_SWEETS, "ALT": "custom_gone"},
    )
    # Manual beats everything.
    assert resolver.resolve("HIPP APFEL") == SNACKS_SWEETS
    # Custom keywords beat AI and built-in rules ("APFEL" would be fruit).
    assert resolver.resolve("WINDELN GR.4") == "custom_baby"
    assert resolver.resolve("HIPP BIRNE") == "custom_baby"
    # AI beats the fallback.
    assert resolver.resolve("JAP. CLASSIC") == SNACKS_SWEETS
    # Assignments to removed categories are ignored.
    assert resolver.resolve("ALT") == OTHER
    assert resolver.is_unknown("ALT")
    assert not resolver.is_unknown("HIPP BIRNE")


def test_lookup_and_descriptions() -> None:
    resolver = CategoryResolver([BABY])
    assert resolver.keys[-1] == "custom_baby"
    assert resolver.lookup("dairy_eggs") == DAIRY_EGGS
    assert resolver.lookup("custom_baby") == "custom_baby"
    assert resolver.lookup(" baby ") == "custom_baby"
    assert resolver.lookup("Kaffee") is None
    assert resolver.descriptions()["custom_baby"] == "Baby, Windel, Hipp, Brei Fuer"
