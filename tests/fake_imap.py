"""A fake ``imaplib.IMAP4_SSL`` with the same return values as imaplib."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.message import EmailMessage
import email.utils
import imaplib
import re


def make_mail(
    sender: str, subject: str, sent: date, pdf: bytes | None, filename: str = "eBon.pdf"
) -> bytes:
    """Build a raw email, optionally with a PDF attachment."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "me@example.com"
    message["Subject"] = subject
    message["Date"] = email.utils.format_datetime(
        datetime(sent.year, sent.month, sent.day, 9, 0, tzinfo=UTC)
    )
    message.set_content("Dein eBon")
    message.add_attachment(b"not a pdf", maintype="text", subtype="plain", filename="info.txt")
    if pdf is not None:
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    return message.as_bytes()


@dataclass
class FakeServer:
    """State of the fake server, shared by all connections."""

    password: str = "secret"
    folders: dict[str, dict[int, tuple[str, date, bytes]]] = field(
        default_factory=lambda: {"INBOX": {}}
    )
    uidvalidity: int = 1
    reachable: bool = True
    commands: list[tuple] = field(default_factory=list)

    def add(self, folder: str, uid: int, sender: str, sent: date, raw: bytes) -> None:
        self.folders.setdefault(folder, {})[uid] = (sender, sent, raw)


class FakeIMAP4SSL:
    """Stands in for imaplib.IMAP4_SSL."""

    server = FakeServer()

    def __init__(self, host: str, port: int, *, ssl_context=None, timeout=None) -> None:
        if not self.server.reachable:
            raise ConnectionRefusedError("unreachable")
        self._folder: dict | None = None

    def login(self, user: str, password: str):
        self.server.commands.append(("LOGIN", user))
        if password != self.server.password:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def select(self, mailbox: str, readonly: bool = False):
        self.server.commands.append(("EXAMINE" if readonly else "SELECT", mailbox))
        name = mailbox.strip('"')
        if name not in self.server.folders:
            return "NO", [b"[NONEXISTENT] Unknown Mailbox"]
        self._folder = self.server.folders[name]
        return "OK", [str(len(self._folder)).encode()]

    def response(self, code: str):
        return code, [str(self.server.uidvalidity).encode()]

    def uid(self, command: str, *args: str):
        self.server.commands.append((command, *args))
        assert self._folder is not None
        if command == "SEARCH":
            criteria = " ".join(args)
            sender = re.search(r'FROM "([^"]+)"', criteria)[1]
            day, month, year = re.search(r"SINCE (\d+)-(\w+)-(\d+)", criteria).groups()
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                      "Nov", "Dec"]  # fmt: skip
            since = date(int(year), months.index(month) + 1, int(day))
            uids = [
                str(uid)
                for uid, (mail_from, sent, _) in sorted(self._folder.items())
                if sender.lower() in mail_from.lower() and sent >= since
            ]
            return "OK", [" ".join(uids).encode()]
        if command == "FETCH":
            uid, spec = args
            raw = self._folder[int(uid)][2]
            return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(command)

    def logout(self):
        return "BYE", [b"bye"]
