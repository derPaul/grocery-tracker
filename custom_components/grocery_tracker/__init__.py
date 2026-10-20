"""The Grocery Tracker integration."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_PATH,
    ATTR_SEARCH,
    DATABASE_FILE,
    DOMAIN,
    SERVICE_IMPORT_RECEIPT,
    SERVICE_LIST_PRODUCTS,
)
from .coordinator import GroceryTrackerConfigEntry, GroceryTrackerCoordinator
from .parsers import ReceiptParseError
from .storage import ReceiptStore

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

IMPORT_RECEIPT_SCHEMA = vol.Schema({vol.Required(ATTR_PATH): cv.string})
LIST_PRODUCTS_SCHEMA = vol.Schema({vol.Optional(ATTR_SEARCH): cv.string})


@callback
def _get_coordinator(hass: HomeAssistant) -> GroceryTrackerCoordinator:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""

    async def import_receipt(call: ServiceCall) -> ServiceResponse:
        path = Path(call.data[ATTR_PATH])
        coordinator = _get_coordinator(hass)

        def check_path() -> str | None:
            """Return a translation key if the file must not be imported."""
            if not (
                path.resolve().is_relative_to(coordinator.inbox.resolve())
                or hass.config.is_allowed_path(str(path))
            ):
                return "path_not_allowed"
            if not path.is_file():
                return "file_not_found"
            return None

        if (error := await hass.async_add_executor_job(check_path)) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=error,
                translation_placeholders={"path": str(path)},
            )
        try:
            receipt = await coordinator.async_import_file(path)
        except ReceiptParseError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="parse_error",
                translation_placeholders={"path": str(path), "error": str(err)},
            ) from err
        await coordinator.async_request_refresh()
        if receipt is None:
            return {"imported": False}
        return {
            "imported": True,
            "uid": receipt.uid,
            "store": receipt.store,
            "timestamp": receipt.timestamp.isoformat(),
            "total": float(receipt.total),
            "item_count": len(receipt.items),
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_RECEIPT,
        import_receipt,
        schema=IMPORT_RECEIPT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def list_products(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        products = await hass.async_add_executor_job(
            coordinator.store.products, call.data.get(ATTR_SEARCH)
        )
        return {
            "products": [
                {
                    "name": product.name,
                    "purchases": product.purchases,
                    "last_price": float(product.last_price),
                    "unit": product.unit,
                    "last_seen": product.last_seen.isoformat(),
                }
                for product in products
            ]
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_PRODUCTS,
        list_products,
        schema=LIST_PRODUCTS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GroceryTrackerConfigEntry) -> bool:
    """Set up Grocery Tracker from a config entry."""
    store = ReceiptStore(hass.config.path(DATABASE_FILE))
    coordinator = GroceryTrackerCoordinator(hass, entry, store)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GroceryTrackerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
