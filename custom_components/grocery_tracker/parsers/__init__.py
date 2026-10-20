"""Receipt parsers.

Each parser turns the text of a receipt into a ``Receipt``. ``parse_receipt``
picks the matching parser, so new stores only need to be registered here.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import Receipt


class ReceiptParseError(Exception):
    """Raised when a receipt cannot be parsed."""


def parse_receipt(text: str) -> Receipt:
    """Detect the store and parse the receipt text."""
    # Imported here to avoid a circular import (parsers import ReceiptParseError).
    from .rewe import looks_like_rewe_ebon, parse_rewe_ebon

    parsers: list[tuple[Callable[[str], bool], Callable[[str], Receipt]]] = [
        (looks_like_rewe_ebon, parse_rewe_ebon),
    ]
    for detect, parse in parsers:
        if detect(text):
            return parse(text)
    raise ReceiptParseError("Unknown receipt format")
