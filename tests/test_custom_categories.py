"""Integration tests for custom categories."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.grocery_tracker.const import (
    DOMAIN,
    SERVICE_CATEGORIZE_PRODUCTS,
    SERVICE_LIST_PRODUCTS,
    SERVICE_SET_CATEGORY,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import make_text_pdf
from .test_init import _setup, inbox  # noqa: F401


async def _add_category(hass: HomeAssistant, entry_id: str, data: dict) -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry_id, "category"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    await hass.async_block_till_done(wait_background_tasks=True)
    return result


async def _products(hass: HomeAssistant, **data) -> dict[str, str]:
    response = await hass.services.async_call(
        DOMAIN, SERVICE_LIST_PRODUCTS, data, blocking=True, return_response=True
    )
    return {p["name"]: p["category"] for p in response["products"]}


async def test_custom_category(
    hass: HomeAssistant,
    inbox: Path,  # noqa: F811
    rewe_ebon_text: str,
    freezer,
) -> None:
    freezer.move_to("2024-03-20 12:00:00")
    inbox.mkdir(parents=True)
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    entry = await _setup(hass, inbox)

    result = await _add_category(hass, entry.entry_id, {"name": "!!!"})
    assert result["errors"] == {"name": "invalid_name"}
    result = await _add_category(hass, entry.entry_id, {"name": " Käse ", "keywords": "gouda"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Käse"
    assert result["data"]["key"] == "custom_kase"
    result = await _add_category(hass, entry.entry_id, {"name": "KÄSE"})
    assert result["errors"] == {"name": "name_exists"}

    # The keyword moves the gouda out of the built-in dairy category.
    registry = er.async_get(hass)
    sensor = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_spending_this_month_custom_kase"
    )
    assert hass.states.get(sensor).state == "2.29"
    assert hass.states.get(sensor).name == "Grocery Tracker Käse this month"
    assert hass.states.get("sensor.grocery_tracker_dairy_eggs_this_month").state == "1.19"
    assert await _products(hass, category="käse") == {"GOUDA JUNG": "custom_kase"}

    # Products can be assigned by category name; unknown names are refused.
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_CATEGORY,
        {"product": "MINERALWASSER", "category": "Käse"},
        blocking=True,
    )
    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_CATEGORY,
            {"product": "MINERALWASSER", "category": "Kaffee"},
            blocking=True,
        )
    assert exc_info.value.translation_key == "unknown_category"
    assert "Käse" in exc_info.value.translation_placeholders["categories"]

    # Renaming keeps the key and all assignments.
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    (subentry,) = entry.subentries.values()
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "category"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Käse & Wasser", "keywords": "gouda", "description": ""}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await _products(hass, category="Käse & Wasser") == {
        "GOUDA JUNG": "custom_kase",
        "MINERALWASSER": "custom_kase",
    }
    assert hass.states.get(sensor).name == "Grocery Tracker Käse & Wasser this month"
    # 2.29 gouda + 3.54 water - 0.35 discount below the water
    assert hass.states.get(sensor).state == "5.48"

    # Removing the category removes its sensor; its products fall back to the rules.
    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert registry.async_get(sensor) is None
    products = await _products(hass)
    assert products["GOUDA JUNG"] == "dairy_eggs"
    assert products["MINERALWASSER"] == "beverages"


async def test_ai_knows_custom_categories(
    hass: HomeAssistant,
    inbox: Path,  # noqa: F811
    rewe_ebon_text: str,
) -> None:
    inbox.mkdir(parents=True)
    text = rewe_ebon_text.replace("SPUELMITTEL", "HIPP GLAESCHEN")
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(text))
    entry = await _setup(hass, inbox)
    await _add_category(
        hass, entry.entry_id, {"name": "Baby", "description": "Babynahrung und Windeln"}
    )

    calls: list[ServiceCall] = []

    async def generate_data(call: ServiceCall) -> dict:
        calls.append(call)
        return {"data": dict.fromkeys(call.data["structure"], "custom_baby")}

    hass.services.async_register(
        "ai_task", "generate_data", generate_data, supports_response=SupportsResponse.ONLY
    )
    response = await hass.services.async_call(
        DOMAIN, SERVICE_CATEGORIZE_PRODUCTS, {}, blocking=True, return_response=True
    )

    assert response["categorized"] == {"HIPP GLAESCHEN": "custom_baby"}
    (call,) = calls
    assert "- custom_baby: Babynahrung und Windeln" in call.data["instructions"]
    (field,) = call.data["structure"].values()
    assert "custom_baby" in field["selector"]["select"]["options"]


async def test_category_does_not_take_over_main_device(
    hass: HomeAssistant,
    inbox: Path,  # noqa: F811
) -> None:
    """Regression: 0.8.0 linked the main device to the category subentry.

    The frontend then showed the main device and all its entities under the
    category instead of under the integration.
    """
    entry = await _setup(hass, inbox)
    await _add_category(hass, entry.entry_id, {"name": "Baby"})

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.config_entries_subentries[entry.entry_id] == {None}
    registry = er.async_get(hass)
    sensor = registry.async_get(
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_spending_this_month_custom_baby"
        )
    )
    assert sensor.config_subentry_id is None
    assert sensor.device_id == device.id


async def test_repair_installations_of_0_8_0(
    hass: HomeAssistant,
    inbox: Path,  # noqa: F811
) -> None:
    entry = await _setup(hass, inbox)
    await _add_category(hass, entry.entry_id, {"name": "Baby"})
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    (subentry,) = entry.subentries.values()
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    sensor_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_spending_this_month_custom_baby"
    )
    device = devices.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    # Recreate what 0.8.0 left behind.
    devices.async_update_device(
        device.id, add_config_entry_id=entry.entry_id, add_config_subentry_id=subentry.subentry_id
    )
    registry.async_update_entity(sensor_id, config_subentry_id=subentry.subentry_id)
    before = {e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    device = devices.async_get(device.id)
    assert device.config_entries_subentries[entry.entry_id] == {None}
    assert registry.async_get(sensor_id).config_subentry_id is None
    after = {e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert after == before
    assert all(hass.states.get(entity_id) for entity_id in after)
