"""Parser for REWE eBons (digital receipts sent as PDF by REWE).

The parser works on the plain text extracted from the PDF. A REWE eBon
looks roughly like this::

                                           EUR
    BIO H-MILCH 1,5%                      1,19 B
    PFAND 0,25 EURO                       0,50 A *
         2 Stk x    0,25
    BANANE                                1,48 B
         0,994 kg x    1,49 EUR/kg
    --------------------------------------------
    SUMME                       EUR      15,37
    ============================================
    Geg. EC-Cash                EUR      15,37
    ...
    12.03.2024     18:23      Bon-Nr.:4711
    Markt:1234     Kasse:3    Bed.:123456
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re

from ..models import Receipt, ReceiptItem
from . import ReceiptParseError

STORE = "REWE"

_AMOUNT = r"-?\d{1,5},\d{2}"

# "BIO H-MILCH 1,5%        1,19 B" / "PFAND 0,25 EURO   0,50 A *"
_ITEM_RE = re.compile(rf"^(?P<name>\S.*?)\s+(?P<total>{_AMOUNT})\s+(?P<tax>[A-Z])(?:\s+\*)?$")
# "2 Stk x    0,25"
_PIECES_RE = re.compile(rf"^(?P<qty>\d+)\s+Stk\s+x\s+(?P<price>{_AMOUNT})$")
# "0,994 kg x    1,49 EUR/kg"
_WEIGHT_RE = re.compile(rf"^(?P<qty>\d+,\d{{3}})\s+kg\s+x\s+(?P<price>{_AMOUNT})\s+EUR/kg$")
_TOTAL_RE = re.compile(rf"^SUMME\s+EUR\s+(?P<total>{_AMOUNT})$")
_PAYMENT_RE = re.compile(rf"^Geg\.\s+(?P<method>.+?)\s+EUR\s+{_AMOUNT}$")
_DATE_RE = re.compile(
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<time>\d{2}:\d{2})(?::\d{2})?\s+Bon-Nr\.?:\s*(?P<bon>\d+)"
)
_MARKET_RE = re.compile(r"Markt:\s*(?P<market>\d+)")


def _to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))


def looks_like_rewe_ebon(text: str) -> bool:
    """Return True if the text is most likely a REWE eBon."""
    return "REWE" in text and any(_TOTAL_RE.match(line) for line in _normalize(text).splitlines())


def _normalize(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines())


def parse_rewe_ebon(text: str) -> Receipt:
    """Parse the text of a REWE eBon into a Receipt."""
    lines = [line for line in _normalize(text).splitlines() if line]

    items: list[ReceiptItem] = []
    total: Decimal | None = None
    payment_method: str | None = None
    timestamp: datetime | None = None
    receipt_number: str | None = None
    market_id: str | None = None

    for line in lines:
        # Everything above "SUMME" is header (store address) or item block.
        # Header lines never end in "<amount> <tax category>", so they are
        # skipped by the item pattern without needing a start marker.
        if total is None:
            if (match := _TOTAL_RE.match(line)) is not None:
                total = _to_decimal(match["total"])
                continue
            if (match := _ITEM_RE.match(line)) is not None:
                items.append(
                    ReceiptItem(
                        name=match["name"],
                        total=_to_decimal(match["total"]),
                        tax_category=match["tax"],
                    )
                )
            elif (match := _PIECES_RE.match(line) or _WEIGHT_RE.match(line)) and items:
                unit = "Stk" if "Stk" in line else "kg"
                prev = items[-1]
                items[-1] = ReceiptItem(
                    name=prev.name,
                    total=prev.total,
                    quantity=_to_decimal(match["qty"]),
                    unit=unit,
                    unit_price=_to_decimal(match["price"]),
                    tax_category=prev.tax_category,
                )
            continue

        if payment_method is None and (match := _PAYMENT_RE.match(line)):
            payment_method = match["method"]
        elif timestamp is None and (match := _DATE_RE.search(line)):
            timestamp = datetime.strptime(f"{match['date']} {match['time']}", "%d.%m.%Y %H:%M")
            receipt_number = match["bon"]
        elif market_id is None and (match := _MARKET_RE.search(line)):
            market_id = match["market"]

    if total is None:
        raise ReceiptParseError("REWE eBon: no 'SUMME' line found")
    if timestamp is None:
        raise ReceiptParseError("REWE eBon: no date / Bon-Nr. line found")
    if not items:
        raise ReceiptParseError("REWE eBon: no items found")

    return Receipt(
        store=STORE,
        timestamp=timestamp,
        total=total,
        items=items,
        market_id=market_id,
        receipt_number=receipt_number,
        payment_method=payment_method,
    )
