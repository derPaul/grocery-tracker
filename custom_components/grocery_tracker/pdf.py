"""Text extraction from PDF receipts."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text(path: Path) -> str:
    """Return the text of all pages, keeping the column layout."""
    reader = PdfReader(path)
    return "\n".join(page.extract_text(extraction_mode="layout") for page in reader.pages)
