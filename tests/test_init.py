"""Integration tests: config flow, inbox import, sensors and action."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grocery_tracker.const import (
    CONF_INBOX_PATH,
    DOMAIN,
    EVENT_RECEIPT_IMPORTED,
    SERVICE_IMPORT_RECEIPT,
    SERVICE_LIST_PRODUCTS,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from .conftest import make_text_pdf


@pytest.fixture
def inbox(hass: HomeAssistant, tmp_path: Path) -> Path:
    # Isolate the database and inbox of each test.
    hass.config.config_dir = str(tmp_path)
    hass.config.allowlist_external_dirs = {str(tmp_path / "www")}
    return tmp_path / "grocery_tracker" / "inbox"


async def _setup(hass: HomeAssistant, inbox: Path) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_INBOX_PATH: str(inbox)})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant, inbox: Path) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({})[CONF_INBOX_PATH] == str(inbox)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_INBOX_PATH: "relative/inbox"}
    )
    assert result["errors"] == {CONF_INBOX_PATH: "path_not_absolute"}

    with patch("custom_components.grocery_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_INBOX_PATH: str(inbox)}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_INBOX_PATH: str(inbox)}


async def test_inbox_import(hass: HomeAssistant, inbox: Path, rewe_ebon_text: str) -> None:
    inbox.mkdir(parents=True)
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    (inbox / "broken.pdf").write_bytes(make_text_pdf("nothing to see here"))
    events = []
    hass.bus.async_listen(EVENT_RECEIPT_IMPORTED, events.append)

    await _setup(hass, inbox)

    assert (inbox / "archive" / "ebon.pdf").exists()
    assert (inbox / "failed" / "broken.pdf").exists()
    assert len(events) == 1
    assert events[0].data["total"] == 10.60

    last = hass.states.get("sensor.grocery_tracker_last_receipt")
    assert last is not None
    assert last.state == "10.60"
    assert last.attributes["store"] == "REWE"
    assert last.attributes["item_count"] == 7
    # The sample receipt is from 2024, so it does not count for this month.
    assert hass.states.get("sensor.grocery_tracker_spending_this_month").state == "0.00"
    assert hass.states.get("sensor.grocery_tracker_spending_last_month") is not None


async def test_import_action(hass: HomeAssistant, inbox: Path, rewe_ebon_text: str) -> None:
    await _setup(hass, inbox)
    www = Path(hass.config.path("www"))
    www.mkdir()
    pdf = www / "ebon.pdf"
    pdf.write_bytes(make_text_pdf(rewe_ebon_text))

    response = await hass.services.async_call(
        DOMAIN, SERVICE_IMPORT_RECEIPT, {"path": str(pdf)}, blocking=True, return_response=True
    )
    assert response["imported"] is True
    assert response["total"] == 10.60

    response = await hass.services.async_call(
        DOMAIN, SERVICE_IMPORT_RECEIPT, {"path": str(pdf)}, blocking=True, return_response=True
    )
    assert response == {"imported": False}

    for path, error in (
        ("/etc/passwd", "path_not_allowed"),
        (str(inbox / "missing.pdf"), "file_not_found"),
    ):
        with pytest.raises(ServiceValidationError) as exc_info:
            await hass.services.async_call(
                DOMAIN, SERVICE_IMPORT_RECEIPT, {"path": path}, blocking=True
            )
        assert exc_info.value.translation_key == error


async def test_list_products(hass: HomeAssistant, inbox: Path, rewe_ebon_text: str) -> None:
    inbox.mkdir(parents=True)
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    await _setup(hass, inbox)

    response = await hass.services.async_call(
        DOMAIN, SERVICE_LIST_PRODUCTS, {}, blocking=True, return_response=True
    )
    assert len(response["products"]) == 6
    assert response["products"][0] == {
        "name": "BANANE CHIQUITA",
        "purchases": 1,
        "last_price": 1.49,
        "unit": "kg",
        "last_seen": "2024-03-12T18:23:00",
    }

    response = await hass.services.async_call(
        DOMAIN, SERVICE_LIST_PRODUCTS, {"search": "wasser"}, blocking=True, return_response=True
    )
    assert [p["name"] for p in response["products"]] == ["MINERALWASSER"]


async def test_unload(hass: HomeAssistant, inbox: Path) -> None:
    entry = await _setup(hass, inbox)
    assert await hass.config_entries.async_unload(entry.entry_id)
