"""Tests for the IMAP mailbox reader."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from unittest.mock import patch

import pytest

from custom_components.grocery_tracker.mail import (
    MailAuthError,
    Mailbox,
    MailboxConfig,
    MailConnectionError,
    MailFolderError,
    _imap_date,
)

from .fake_imap import FakeIMAP4SSL, FakeServer, make_mail

SENDER = "REWE eBon <ebon@mailing.rewe.de>"
CONFIG = MailboxConfig(
    server="imap.example.com",
    port=993,
    username="me@example.com",
    password="secret",
    folder="REWE",
    sender="ebon@mailing.rewe.de",
    since=date(2026, 1, 1),
)


@pytest.fixture
def server():
    server = FakeServer()
    with (
        patch.object(FakeIMAP4SSL, "server", server),
        patch("custom_components.grocery_tracker.mail.imaplib.IMAP4_SSL", FakeIMAP4SSL),
    ):
        yield server


def test_imap_date() -> None:
    assert _imap_date(date(2026, 3, 5)) == "05-Mar-2026"


def test_messages(server: FakeServer) -> None:
    server.add(
        "REWE",
        3,
        SENDER,
        date(2025, 12, 31),
        make_mail(SENDER, "old", date(2025, 12, 31), b"%PDF-old"),
    )
    server.add(
        "REWE",
        5,
        SENDER,
        date(2026, 1, 2),
        make_mail(SENDER, "eBon 1", date(2026, 1, 2), b"%PDF-1"),
    )
    server.add(
        "REWE",
        7,
        "news@example.com",
        date(2026, 1, 3),
        make_mail("news@example.com", "spam", date(2026, 1, 3), b"%PDF-x"),
    )
    server.add(
        "REWE", 9, SENDER, date(2026, 1, 9), make_mail(SENDER, "eBon 2", date(2026, 1, 9), None)
    )
    server.add(
        "REWE",
        11,
        SENDER,
        date(2026, 1, 10),
        make_mail(SENDER, "eBon 3", date(2026, 1, 10), b"%PDF-3"),
    )

    with Mailbox(CONFIG) as mailbox:
        assert mailbox.uidvalidity == 1
        messages = list(mailbox.messages())
        assert [(m.uid, m.subject, m.pdfs) for m in messages] == [
            (5, "eBon 1", [("eBon.pdf", b"%PDF-1")]),
            (9, "eBon 2", []),
            (11, "eBon 3", [("eBon.pdf", b"%PDF-3")]),
        ]
        assert [m.uid for m in mailbox.messages(after_uid=9)] == [11]

    # The mailbox is opened read-only and messages are fetched without "seen" flag.
    assert ("EXAMINE", '"REWE"') in server.commands
    assert ("SEARCH", "FROM", '"ebon@mailing.rewe.de"', "SINCE", "01-Jan-2026") in server.commands
    fetches = [c for c in server.commands if c[0] == "FETCH"]
    assert fetches and all(c[2] == "(BODY.PEEK[])" for c in fetches)


def test_errors(server: FakeServer) -> None:
    server.add("REWE", 1, SENDER, date(2026, 1, 2), make_mail(SENDER, "x", date(2026, 1, 2), None))
    with pytest.raises(MailAuthError), Mailbox(replace(CONFIG, password="wrong")):
        pass
    with pytest.raises(MailFolderError), Mailbox(replace(CONFIG, folder="Missing")):
        pass
    server.reachable = False
    with pytest.raises(MailConnectionError), Mailbox(CONFIG):
        pass


def test_nested_and_unnamed_pdfs() -> None:
    from email.message import EmailMessage

    from custom_components.grocery_tracker.mail import _pdf_attachments

    message = EmailMessage()
    message["From"] = "ebon@mailing.rewe.de"
    message.set_content("Dein eBon")
    message.add_alternative("<p>Dein eBon</p>", subtype="html")
    # PDF nested in multipart/related inside the HTML alternative.
    html = message.get_payload()[1]
    html.add_related(b"%PDF-nested", maintype="application", subtype="pdf", cid="<ebon>")
    message.add_attachment(
        b"%PDF-octet", maintype="application", subtype="octet-stream", filename="Bon.PDF"
    )
    message.add_attachment(b"no pdf", maintype="text", subtype="plain", filename="info.txt")

    assert _pdf_attachments(message.as_bytes()) == [
        ("receipt.pdf", b"%PDF-nested"),
        ("Bon.PDF", b"%PDF-octet"),
    ]
