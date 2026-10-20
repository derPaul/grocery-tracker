"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
def rewe_ebon_text() -> str:
    """Return the text of a sample REWE eBon."""
    return (FIXTURES / "rewe_ebon.txt").read_text(encoding="utf-8")


def make_text_pdf(text: str) -> bytes:
    """Build a minimal one-page PDF that renders the text in a monospace font."""

    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    lines = text.splitlines()
    stream = f"BT /F1 8 Tf 10 TL 20 {20 + 10 * len(lines)} Td\n"
    stream += "".join(f"({escape(line)}) Tj T*\n" for line in lines) + "ET"
    stream_bytes = stream.encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 {40 + 10 * len(lines)}]"
        " /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>".encode(),
        f"<< /Length {len(stream_bytes)} >>\nstream\n".encode() + stream_bytes + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
