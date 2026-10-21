"""Watch products and create categories from actions, buttons and the config flow."""

from __future__ import annotations

from types import MappingProxyType

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_DESCRIPTION, CONF_ICON, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import slugify

from .categories import CATEGORIES, CategoryResolver
from .const import CONF_KEY, CONF_KEYWORDS, CONF_WATCHED_PRODUCTS, DOMAIN, SUBENTRY_CATEGORY
from .coordinator import GroceryTrackerConfigEntry, GroceryTrackerCoordinator


def lookup_category(resolver: CategoryResolver, value: str) -> str:
    """Return the key for a category key or custom category name."""
    if (key := resolver.lookup(value)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_category",
            translation_placeholders={
                "category": value,
                "categories": ", ".join([*CATEGORIES, *(c.name for c in resolver.custom)]),
            },
        )
    return key


async def _async_check_product(
    hass: HomeAssistant, coordinator: GroceryTrackerCoordinator, product: str
) -> None:
    if not await hass.async_add_executor_job(coordinator.store.has_product, product):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_product",
            translation_placeholders={"product": product},
        )


async def async_assign_category(
    hass: HomeAssistant, coordinator: GroceryTrackerCoordinator, product: str, category: str
) -> None:
    """Assign a product to a category (key or custom name) manually."""
    await _async_check_product(hass, coordinator, product)
    resolver = await hass.async_add_executor_job(coordinator.store.resolver)
    key = lookup_category(resolver, category)
    await hass.async_add_executor_job(coordinator.store.set_category, product, key, "manual")
    await coordinator.async_request_refresh()


def category_key(name: str) -> str:
    """Return the stable key of a custom category; it never changes on rename."""
    return f"custom_{slugify(name)}"


def category_name_error(
    entry: ConfigEntry, name: str, own_subentry_id: str | None = None
) -> str | None:
    """Return an error key if ``name`` can't be used for a custom category."""
    if not any(char.isalnum() for char in name):
        return "invalid_name"
    folded = name.casefold()
    key = category_key(name)
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_CATEGORY or subentry.subentry_id == own_subentry_id:
            continue
        if subentry.data[CONF_NAME].casefold() == folded or (
            own_subentry_id is None and subentry.unique_id == key
        ):
            return "name_exists"
    return None


def create_category(
    hass: HomeAssistant,
    entry: GroceryTrackerConfigEntry,
    name: str,
    keywords: str = "",
    description: str = "",
    icon: str = "",
) -> str:
    """Add a custom category subentry and return its key; the entry reloads."""
    name = name.strip()
    icon = icon.strip()
    if (error := category_name_error(entry, name)) is not None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=f"category_{error}",
            translation_placeholders={"name": name},
        )
    if icon:
        try:
            cv.icon(icon)
        except vol.Invalid as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_icon",
                translation_placeholders={"icon": icon},
            ) from err
    key = category_key(name)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType(
                {
                    CONF_NAME: name,
                    CONF_KEYWORDS: keywords,
                    CONF_DESCRIPTION: description,
                    CONF_KEY: key,
                    **({CONF_ICON: icon} if icon else {}),
                }
            ),
            subentry_type=SUBENTRY_CATEGORY,
            title=name,
            unique_id=key,
        ),
    )
    return key


async def async_set_watched(
    hass: HomeAssistant, entry: GroceryTrackerConfigEntry, product: str, watched: bool
) -> None:
    """Start or stop tracking the price of a product; the entry reloads."""
    current: list[str] = list(entry.options.get(CONF_WATCHED_PRODUCTS, []))
    if watched == (product in current):
        return
    if watched:
        await _async_check_product(hass, entry.runtime_data, product)
        current.append(product)
    else:
        current.remove(product)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_WATCHED_PRODUCTS: current}
    )
