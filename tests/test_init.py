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
    SERVICE_CATEGORIZE_PRODUCTS,
    SERVICE_IMPORT_RECEIPT,
    SERVICE_LIST_PRODUCTS,
    SERVICE_SET_CATEGORY,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
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
        "category": "fruit_vegetables",
        "purchases": 1,
        "last_price": 1.49,
        "unit": "kg",
        "last_seen": "2024-03-12T18:23:00",
    }

    response = await hass.services.async_call(
        DOMAIN, SERVICE_LIST_PRODUCTS, {"search": "wasser"}, blocking=True, return_response=True
    )
    assert [p["name"] for p in response["products"]] == ["MINERALWASSER"]

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST_PRODUCTS,
        {"category": "dairy_eggs"},
        blocking=True,
        return_response=True,
    )
    assert [p["name"] for p in response["products"]] == ["BIO H-MILCH 1,5%", "GOUDA JUNG"]


async def test_category_sensors_and_set_category(
    hass: HomeAssistant, inbox: Path, rewe_ebon_text: str, freezer
) -> None:
    freezer.move_to("2024-03-20 12:00:00")
    inbox.mkdir(parents=True)
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    await _setup(hass, inbox)

    dairy = "sensor.grocery_tracker_dairy_eggs_this_month"
    assert hass.states.get(dairy).state == "3.48"
    assert hass.states.get("sensor.grocery_tracker_beverages_this_month").state == "3.19"
    assert hass.states.get("sensor.grocery_tracker_other_this_month").state == "0.00"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_CATEGORY,
        {"product": "GOUDA JUNG", "category": "other"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(dairy).state == "1.19"
    assert hass.states.get("sensor.grocery_tracker_other_this_month").state == "2.29"

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_CATEGORY,
            {"product": "GOUDA", "category": "other"},
            blocking=True,
        )
    assert exc_info.value.translation_key == "unknown_product"


async def test_categorize_products(hass: HomeAssistant, inbox: Path, rewe_ebon_text: str) -> None:
    inbox.mkdir(parents=True)
    text = rewe_ebon_text.replace("SPUELMITTEL", "GEM PFAN TOSKANA")
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(text))
    await _setup(hass, inbox)

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN, SERVICE_CATEGORIZE_PRODUCTS, {}, blocking=True, return_response=True
        )
    assert exc_info.value.translation_key == "ai_task_unavailable"

    calls: list[ServiceCall] = []

    async def generate_data(call: ServiceCall) -> dict:
        calls.append(call)
        return {"conversation_id": "1", "data": dict.fromkeys(call.data["structure"], "frozen")}

    hass.services.async_register(
        "ai_task", "generate_data", generate_data, supports_response=SupportsResponse.ONLY
    )

    response = await hass.services.async_call(
        DOMAIN, SERVICE_CATEGORIZE_PRODUCTS, {}, blocking=True, return_response=True
    )

    assert response == {"categorized": {"GEM PFAN TOSKANA": "frozen"}, "uncategorized": []}
    # Only the product no rule knows is sent to the AI.
    (call,) = calls
    assert [field["description"] for field in call.data["structure"].values()] == [
        "GEM PFAN TOSKANA"
    ]
    products = await hass.services.async_call(
        DOMAIN, SERVICE_LIST_PRODUCTS, {"search": "PFAN"}, blocking=True, return_response=True
    )
    assert products["products"][0]["category"] == "frozen"

    # Already categorized products are not sent again.
    await hass.services.async_call(
        DOMAIN, SERVICE_CATEGORIZE_PRODUCTS, {}, blocking=True, return_response=True
    )
    assert len(calls) == 1


async def test_unload(hass: HomeAssistant, inbox: Path) -> None:
    entry = await _setup(hass, inbox)
    assert await hass.config_entries.async_unload(entry.entry_id)
