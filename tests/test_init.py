"""Integration tests: config flow, inbox import, sensors and action."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grocery_tracker.const import (
    CONF_INBOX_PATH,
    CONF_WATCHED_PRODUCTS,
    DOMAIN,
    EVENT_PRICE_CHANGED,
    EVENT_RECEIPT_IMPORTED,
    SERVICE_CATEGORIZE_PRODUCTS,
    SERVICE_GET_STATISTICS,
    SERVICE_IMPORT_RECEIPT,
    SERVICE_LIST_PRODUCTS,
    SERVICE_SET_CATEGORY,
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

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
        "last_seen": "2024-03-12T18:23:00-07:00",  # test time zone is US/Pacific
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


async def test_item_attributes(
    hass: HomeAssistant, inbox: Path, rewe_ebon_text: str, freezer
) -> None:
    freezer.move_to("2024-03-20 12:00:00")
    inbox.mkdir(parents=True)
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    await _setup(hass, inbox)

    items = hass.states.get("sensor.grocery_tracker_last_receipt").attributes["items"]
    assert len(items) == 7
    assert items[3] == {
        "name": "BANANE CHIQUITA",
        "category": "fruit_vegetables",
        "quantity": 0.994,
        "unit": "kg",
        "unit_price": 1.49,
        "total": 1.48,
    }
    top = hass.states.get("sensor.grocery_tracker_spending_this_month").attributes["top_products"]
    assert top[0] == {
        "name": "MINERALWASSER",
        "category": "beverages",
        "amount": 3.54,
        "purchases": 1,
    }


async def test_watched_products(
    hass: HomeAssistant, inbox: Path, rewe_ebon_text: str, rewe_ebon_text_later: str
) -> None:
    inbox.mkdir(parents=True)
    (inbox / "ebon1.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    entry = await _setup(hass, inbox)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WATCHED_PRODUCTS: ["BIO H-MILCH 1,5%", "BANANE CHIQUITA"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    milk = "sensor.grocery_tracker_price_bio_h_milch_15"
    state = hass.states.get(milk)
    assert state is not None
    assert state.state == "1.19"
    assert state.attributes["unit_of_measurement"] == "€"
    assert state.attributes["previous_price"] is None
    banana = hass.states.get("sensor.grocery_tracker_price_banane_chiquita")
    assert banana.state == "1.49"
    assert banana.attributes["unit_of_measurement"] == "€/kg"

    # A new receipt with a higher milk price updates the sensor and fires an event.
    events = []
    hass.bus.async_listen(EVENT_PRICE_CHANGED, events.append)
    (inbox / "ebon2.pdf").write_bytes(make_text_pdf(rewe_ebon_text_later))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(milk)
    assert state.state == "1.29"
    assert state.attributes["previous_price"] == 1.19
    assert state.attributes["change_percent"] == 8.4
    assert [event.data for event in events] == [
        {
            "product": "BIO H-MILCH 1,5%",
            "category": "dairy_eggs",
            "old_price": 1.19,
            "new_price": 1.29,
            "change_percent": 8.4,
            "unit": "Stk",
        }
    ]

    # Unwatching a product removes its sensor.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WATCHED_PRODUCTS: ["BANANE CHIQUITA"]}
    )
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(milk) is None
    assert hass.states.get("sensor.grocery_tracker_price_banane_chiquita") is not None


async def test_year_total_and_monthly_overview(
    hass: HomeAssistant,
    inbox: Path,
    rewe_ebon_text: str,
    rewe_ebon_text_later: str,
    freezer,
) -> None:
    freezer.move_to("2024-03-20 12:00:00")
    inbox.mkdir(parents=True)
    (inbox / "1.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    (inbox / "2.pdf").write_bytes(make_text_pdf(rewe_ebon_text_later))
    (inbox / "3.pdf").write_bytes(make_text_pdf(rewe_ebon_text.replace("12.03.2024", "28.12.2023")))
    (inbox / "4.pdf").write_bytes(make_text_pdf(rewe_ebon_text.replace("12.03.2024", "02.01.2023")))
    await _setup(hass, inbox)

    assert hass.states.get("sensor.grocery_tracker_receipts_total").state == "4"
    year = hass.states.get("sensor.grocery_tracker_spending_this_year")
    assert year.state == "21.30"
    months = year.attributes["last_12_months"]
    assert len(months) == 12
    assert months[0] == {"month": "2023-04", "amount": 0.0, "receipts": 0}
    assert months[8] == {"month": "2023-12", "amount": 10.6, "receipts": 1}
    assert months[-1] == {"month": "2024-03", "amount": 21.3, "receipts": 2}


async def test_get_statistics(
    hass: HomeAssistant,
    inbox: Path,
    rewe_ebon_text: str,
    rewe_ebon_text_later: str,
    freezer,
) -> None:
    freezer.move_to("2024-03-20 12:00:00")
    inbox.mkdir(parents=True)
    (inbox / "1.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    (inbox / "2.pdf").write_bytes(make_text_pdf(rewe_ebon_text_later))
    (inbox / "3.pdf").write_bytes(make_text_pdf(rewe_ebon_text.replace("12.03.2024", "28.01.2024")))
    await _setup(hass, inbox)

    async def stats(**data):
        return await hass.services.async_call(
            DOMAIN, SERVICE_GET_STATISTICS, data, blocking=True, return_response=True
        )

    # Default: this month
    response = await stats()
    assert (response["start"], response["end"]) == ("2024-03-01", "2024-03-20")
    assert (response["total"], response["receipts"]) == (21.3, 2)
    assert [m["month"] for m in response["months"]] == ["2024-03"]
    month = response["months"][0]
    assert response["by_category"]["dairy_eggs"] == month["by_category"]["dairy_eggs"]
    assert response["top_products"][0]["purchases"] == 2
    assert "receipt_list" not in response

    # Three months, per month and in total
    response = await stats(months=3, top=3, receipts=True)
    assert response["start"] == "2024-01-01"
    assert [(m["month"], m["amount"], m["receipts"]) for m in response["months"]] == [
        ("2024-01", 10.6, 1),
        ("2024-02", 0.0, 0),
        ("2024-03", 21.3, 2),
    ]
    assert response["total"] == 31.9
    assert sum(response["by_category"].values()) == pytest.approx(31.9)
    assert len(response["top_products"]) == 3
    assert [r["timestamp"][:10] for r in response["receipt_list"]] == [
        "2024-03-19",
        "2024-03-12",
        "2024-01-28",
    ]

    # Date range
    response = await stats(start="2024-03-15", end="2024-03-31")
    assert (response["total"], response["receipts"]) == (10.7, 1)
    assert [m["month"] for m in response["months"]] == ["2024-03"]

    with pytest.raises(ServiceValidationError):
        await stats(start="2024-03-15", end="2024-03-01")
