"""Tests for managing products and categories from a dashboard."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.grocery_tracker.const import (
    DOMAIN,
    SERVICE_CREATE_CATEGORY,
    SERVICE_LIST_PRODUCTS,
    SERVICE_UNWATCH_PRODUCT,
    SERVICE_WATCH_PRODUCT,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import make_text_pdf
from .test_init import _setup, inbox  # noqa: F401


def _entity(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    return entity_id


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.fixture
async def entry_id(hass: HomeAssistant, inbox: Path, rewe_ebon_text: str) -> str:  # noqa: F811
    inbox.mkdir(parents=True)
    (inbox / "ebon.pdf").write_bytes(make_text_pdf(rewe_ebon_text))
    return (await _setup(hass, inbox)).entry_id


async def test_watch_and_assign_from_dashboard(hass: HomeAssistant, entry_id: str) -> None:
    product = _entity(hass, "select", f"{entry_id}_select_product")
    category = _entity(hass, "select", f"{entry_id}_select_category")
    watch = _entity(hass, "button", f"{entry_id}_watch_product")
    unwatch = _entity(hass, "button", f"{entry_id}_unwatch_product")
    assign = _entity(hass, "button", f"{entry_id}_assign_category")
    price = f"{entry_id}_price_GOUDA JUNG"

    assert "GOUDA JUNG" in hass.states.get(product).attributes["options"]
    assert hass.states.get(category).attributes["options"][:2] == [
        "fruit_vegetables",
        "dairy_eggs",
    ]
    with pytest.raises(ServiceValidationError) as exc_info:
        await _press(hass, watch)
    assert exc_info.value.translation_key == "no_product"

    await hass.services.async_call(
        "select", "select_option", {"entity_id": product, "option": "GOUDA JUNG"}, blocking=True
    )
    await _press(hass, watch)
    # The entry reloaded: the price sensor exists and the selection was kept.
    assert hass.states.get(_entity(hass, "sensor", price)).state == "2.29"
    assert hass.states.get(product).state == "GOUDA JUNG"

    with pytest.raises(ServiceValidationError) as exc_info:
        await _press(hass, assign)
    assert exc_info.value.translation_key == "no_category"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": category, "option": "frozen"}, blocking=True
    )
    await _press(hass, assign)
    response = await hass.services.async_call(
        DOMAIN, SERVICE_LIST_PRODUCTS, {"search": "GOUDA"}, blocking=True, return_response=True
    )
    assert response["products"][0]["category"] == "frozen"

    await _press(hass, unwatch)
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, price) is None


async def test_create_category_from_dashboard(hass: HomeAssistant, entry_id: str) -> None:
    name = _entity(hass, "text", f"{entry_id}_text_new_category_name")
    keywords = _entity(hass, "text", f"{entry_id}_text_new_category_keywords")
    create = _entity(hass, "button", f"{entry_id}_create_category")

    with pytest.raises(ServiceValidationError) as exc_info:
        await _press(hass, create)
    assert exc_info.value.translation_key == "no_new_category_name"

    await hass.services.async_call(
        "text", "set_value", {"entity_id": name, "value": "Käse"}, blocking=True
    )
    await hass.services.async_call(
        "text", "set_value", {"entity_id": keywords, "value": "gouda"}, blocking=True
    )
    await _press(hass, create)

    entry = hass.config_entries.async_get_entry(entry_id)
    (subentry,) = entry.subentries.values()
    assert subentry.title == "Käse"
    assert dict(subentry.data)["keywords"] == "gouda"
    sensor = _entity(hass, "sensor", f"{entry_id}_spending_this_month_custom_kase")
    assert hass.states.get(sensor) is not None
    # The inputs are cleared and the new category can be chosen.
    assert hass.states.get(name).state == ""
    assert hass.states.get(keywords).state == ""
    category = _entity(hass, "select", f"{entry_id}_select_category")
    assert "Käse" in hass.states.get(category).attributes["options"]

    await hass.services.async_call(
        "text", "set_value", {"entity_id": name, "value": "KÄSE"}, blocking=True
    )
    with pytest.raises(ServiceValidationError) as exc_info:
        await _press(hass, create)
    assert exc_info.value.translation_key == "category_name_exists"


async def test_actions(hass: HomeAssistant, entry_id: str) -> None:
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE_CATEGORY,
        {"name": "Baby", "keywords": "hipp", "description": "Babynahrung"},
        blocking=True,
        return_response=True,
    )
    assert response == {"key": "custom_baby"}
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _entity(hass, "sensor", f"{entry_id}_spending_this_month_custom_baby")

    await hass.services.async_call(
        DOMAIN, SERVICE_WATCH_PRODUCT, {"product": "MINERALWASSER"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _entity(hass, "sensor", f"{entry_id}_price_MINERALWASSER")
    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN, SERVICE_WATCH_PRODUCT, {"product": "WASSER"}, blocking=True
        )
    assert exc_info.value.translation_key == "unknown_product"

    await hass.services.async_call(
        DOMAIN, SERVICE_UNWATCH_PRODUCT, {"product": "MINERALWASSER"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry_id}_price_MINERALWASSER")
        is None
    )
