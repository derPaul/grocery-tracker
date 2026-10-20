"""Integration tests for importing eBons from a mailbox."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.grocery_tracker.const import (
    DOMAIN,
    EVENT_RECEIPT_IMPORTED,
    SERVICE_CHECK_MAILBOXES,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .conftest import make_text_pdf
from .fake_imap import FakeIMAP4SSL, FakeServer, make_mail
from .test_init import _setup, inbox  # noqa: F401

SENDER = "REWE eBon <ebon@mailing.rewe.de>"
MAILBOX_INPUT = {
    "server": "imap.gmail.com",
    "port": 993,
    "username": "me@gmail.com",
    "password": "secret",
    "folder": "REWE",
    "sender": "ebon@mailing.rewe.de",
    "since": "2024-01-01",
}


@pytest.fixture
def server():
    server = FakeServer(folders={"REWE": {}})
    with (
        patch.object(FakeIMAP4SSL, "server", server),
        patch("custom_components.grocery_tracker.mail.imaplib.IMAP4_SSL", FakeIMAP4SSL),
    ):
        yield server


async def _add_mailbox(hass: HomeAssistant, entry_id: str, **changes) -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry_id, "mailbox"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**MAILBOX_INPUT, **changes}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    return result


async def test_import_from_mailbox(
    hass: HomeAssistant,
    inbox: Path,  # noqa: F811
    server: FakeServer,
    rewe_ebon_text: str,
    rewe_ebon_text_later: str,
) -> None:
    server.add(
        "REWE",
        10,
        SENDER,
        date(2024, 3, 12),
        make_mail(SENDER, "Dein eBon", date(2024, 3, 12), make_text_pdf(rewe_ebon_text)),
    )
    server.add(
        "REWE",
        11,
        SENDER,
        date(2024, 3, 13),
        make_mail(SENDER, "Kaputt", date(2024, 3, 13), make_text_pdf("kein Bon"), "../../evil.pdf"),
    )
    entry = await _setup(hass, inbox)
    events = []
    hass.bus.async_listen(EVENT_RECEIPT_IMPORTED, events.append)

    result = await _add_mailbox(hass, entry.entry_id, password="wrong")
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**MAILBOX_INPUT, "folder": "Missing"}
    )
    assert result["errors"] == {"folder": "folder_not_found"}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], MAILBOX_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "me@gmail.com (REWE)"
    await hass.async_block_till_done(wait_background_tasks=True)

    # The entry reloads and scans the mailbox in the background.
    assert len(events) == 1
    assert hass.states.get("sensor.grocery_tracker_last_receipt").state == "10.60"
    # The unparsable PDF is kept for inspection, under its base name only.
    assert (inbox / "failed" / "mail-11-evil.pdf").exists()
    assert not (inbox.parent / "evil.pdf").exists()

    # Only new messages are fetched on the next check.
    server.commands.clear()
    server.add(
        "REWE",
        12,
        SENDER,
        date(2024, 3, 19),
        make_mail(SENDER, "Dein eBon", date(2024, 3, 19), make_text_pdf(rewe_ebon_text_later)),
    )
    await entry.runtime_data.async_check_mailboxes()
    await hass.async_block_till_done()
    assert [c for c in server.commands if c[0] == "FETCH"] == [("FETCH", "12", "(BODY.PEEK[])")]
    assert len(events) == 2
    assert hass.states.get("sensor.grocery_tracker_last_receipt").state == "10.70"

    # Adding the same mailbox folder again is refused.
    result = await _add_mailbox(hass, entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_mailbox_auth_issue_and_reconfigure(
    hass: HomeAssistant,
    inbox: Path,  # noqa: F811
    server: FakeServer,
) -> None:
    entry = await _setup(hass, inbox)
    await _add_mailbox(hass, entry.entry_id)
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    (subentry,) = entry.subentries.values()
    issue_id = f"mailbox_{subentry.subentry_id}"

    # The app password was revoked: a repair issue tells the user.
    server.password = "new-secret"
    await entry.runtime_data.async_check_mailboxes()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "mailbox_auth_failed"

    # Reconfigure with the new password; an empty password keeps the old one.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "mailbox"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    data = {**MAILBOX_INPUT}
    del data["password"]
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**data, "password": "new-secret"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)

    entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert entry.subentries[subentry.subentry_id].data["password"] == "new-secret"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    # Removing the mailbox removes its issue too.
    server.password = "other"
    await entry.runtime_data.async_check_mailboxes()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


def _mailbox_entity(hass: HomeAssistant, subentry_id: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{subentry_id}_{key}")
    assert entity_id is not None
    return entity_id


async def test_check_mailboxes_button_action_and_status(
    hass: HomeAssistant,
    inbox: Path,  # noqa: F811
    server: FakeServer,
    rewe_ebon_text: str,
    freezer,
) -> None:
    freezer.move_to("2024-03-20 12:00:00+00:00")
    entry = await _setup(hass, inbox)
    await _add_mailbox(hass, entry.entry_id)
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    (subentry,) = entry.subentries.values()
    last_check = _mailbox_entity(hass, subentry.subentry_id, "last_check")
    status = _mailbox_entity(hass, subentry.subentry_id, "status")

    # The first check ran right after setup and found nothing.
    assert hass.states.get(status).state == "ok"
    assert hass.states.get(last_check).state == "2024-03-20T12:00:00+00:00"
    assert hass.states.get(last_check).attributes["new_messages"] == 0
    entity = er.async_get(hass).async_get(status)
    assert entity.config_subentry_id == subentry.subentry_id

    # A new eBon arrives; the button checks right away.
    freezer.move_to("2024-03-20 12:05:00+00:00")
    server.add(
        "REWE",
        10,
        SENDER,
        date(2024, 3, 12),
        make_mail(SENDER, "Dein eBon", date(2024, 3, 12), make_text_pdf(rewe_ebon_text)),
    )
    button = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_check_mailboxes"
    )
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(last_check).state == "2024-03-20T12:05:00+00:00"
    assert hass.states.get(last_check).attributes["new_receipts"] == 1
    assert hass.states.get("sensor.grocery_tracker_last_receipt").state == "10.60"

    # The action reports the outcome, here a revoked password.
    server.password = "revoked"
    response = await hass.services.async_call(
        DOMAIN, SERVICE_CHECK_MAILBOXES, {}, blocking=True, return_response=True
    )
    assert response["mailboxes"][0]["mailbox"] == "me@gmail.com (REWE)"
    assert response["mailboxes"][0]["status"] == "auth_failed"
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "auth_failed"
