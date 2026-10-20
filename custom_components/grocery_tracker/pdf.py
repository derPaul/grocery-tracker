"""Text extraction from PDF receipts."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


def extract_text(pdf: Path | bytes) -> str:
    """Return the text of all pages, keeping the column layout."""
    reader = PdfReader(BytesIO(pdf) if isinstance(pdf, bytes) else pdf)
    return "\n".join(page.extract_text(extraction_mode="layout") for page in reader.pages)
