"""Read receipt PDFs from an IMAP mailbox.

The mailbox is opened read-only and messages are fetched with BODY.PEEK, so
nothing in the mailbox changes (no "seen" flag, no moving or deleting).
Progress is tracked by IMAP UID: only messages with a UID above the last
processed one are fetched.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
import email
from email.message import EmailMessage
import email.policy
import imaplib
import ssl

DEFAULT_SERVER = "imap.gmail.com"
DEFAULT_PORT = 993
DEFAULT_FOLDER = "INBOX"
DEFAULT_SENDER = "ebon@mailing.rewe.de"
TIMEOUT = 30

# IMAP dates use English month names regardless of the system locale.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class MailError(Exception):
    """Base class for mailbox errors."""


class MailAuthError(MailError):
    """Login was rejected."""


class MailConnectionError(MailError):
    """The server could not be reached or answered with an error."""


class MailFolderError(MailError):
    """The folder does not exist."""


@dataclass(frozen=True, slots=True)
class MailboxConfig:
    """Connection settings of a mailbox."""

    server: str
    port: int
    username: str
    password: str
    folder: str
    sender: str
    since: date

    @property
    def search_key(self) -> str:
        """Identify what is searched; progress is stored per search."""
        return "|".join(
            (self.server, self.username, self.folder, self.sender, self.since.isoformat())
        ).lower()


@dataclass(frozen=True, slots=True)
class MailMessage:
    """A matching message and its PDF attachments."""

    uid: int
    subject: str
    pdfs: list[tuple[str, bytes]]


def _imap_date(value: date) -> str:
    return f"{value.day:02d}-{_MONTHS[value.month - 1]}-{value.year}"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _pdf_attachments(raw: bytes) -> list[tuple[str, bytes]]:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    pdfs = []
    for part in message.iter_attachments():
        filename = part.get_filename() or "receipt.pdf"
        if part.get_content_type() == "application/pdf" or filename.lower().endswith(".pdf"):
            pdfs.append((filename, part.get_payload(decode=True)))
    return pdfs


class Mailbox:
    """A read-only connection to one IMAP folder.

    Use as a context manager; all methods are blocking.
    """

    def __init__(self, config: MailboxConfig, ssl_context: ssl.SSLContext | None = None) -> None:
        """Initialize the mailbox; nothing is connected yet."""
        self._config = config
        self._ssl_context = ssl_context
        self._conn: imaplib.IMAP4_SSL | None = None
        self.uidvalidity: int | None = None

    def __enter__(self) -> Mailbox:
        """Connect, log in and select the folder read-only."""
        config = self._config
        try:
            self._conn = imaplib.IMAP4_SSL(
                config.server, config.port, ssl_context=self._ssl_context, timeout=TIMEOUT
            )
        except OSError as err:
            raise MailConnectionError(str(err)) from err
        try:
            self._conn.login(config.username, config.password)
        except imaplib.IMAP4.error as err:
            self._logout()
            raise MailAuthError(str(err)) from err
        except OSError as err:
            self._logout()
            raise MailConnectionError(str(err)) from err
        try:
            status, _ = self._conn.select(_quote(config.folder), readonly=True)
            if status != "OK":
                raise MailFolderError(config.folder)
            _, values = self._conn.response("UIDVALIDITY")
            self.uidvalidity = int(values[0]) if values and values[0] else None
        except (imaplib.IMAP4.error, OSError) as err:
            self._logout()
            raise MailConnectionError(str(err)) from err
        except MailFolderError:
            self._logout()
            raise
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Log out."""
        self._logout()

    def _logout(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
            self._conn = None

    def search(self, after_uid: int = 0) -> list[int]:
        """Return the UIDs of matching messages above ``after_uid``, oldest first."""
        assert self._conn is not None
        config = self._config
        try:
            status, data = self._conn.uid(
                "SEARCH", "FROM", _quote(config.sender), "SINCE", _imap_date(config.since)
            )
        except (imaplib.IMAP4.error, OSError) as err:
            raise MailConnectionError(str(err)) from err
        if status != "OK":
            raise MailConnectionError(f"SEARCH failed: {data!r}")
        uids = sorted(int(uid) for uid in (data[0] or b"").split())
        return [uid for uid in uids if uid > after_uid]

    def fetch(self, uid: int) -> MailMessage:
        """Fetch one message without marking it as seen."""
        assert self._conn is not None
        try:
            status, data = self._conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        except (imaplib.IMAP4.error, OSError) as err:
            raise MailConnectionError(str(err)) from err
        raw = next((item[1] for item in data if isinstance(item, tuple)), None)
        if status != "OK" or raw is None:
            raise MailConnectionError(f"FETCH {uid} failed: {data!r}")
        subject = email.message_from_bytes(raw, policy=email.policy.default)["subject"] or ""
        return MailMessage(uid=uid, subject=str(subject), pdfs=_pdf_attachments(raw))

    def messages(self, after_uid: int = 0) -> Iterator[MailMessage]:
        """Yield all matching messages above ``after_uid``, oldest first."""
        for uid in self.search(after_uid):
            yield self.fetch(uid)
