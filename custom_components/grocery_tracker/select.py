"""Product and category selection for managing Grocery Tracker from a dashboard."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .categories import CATEGORIES
from .coordinator import GroceryTrackerConfigEntry, GroceryTrackerCoordinator
from .sensor import _device_info

SELECTED_PRODUCT = "product"
SELECTED_CATEGORY = "category"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroceryTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    coordinator = entry.runtime_data
    async_add_entities([ProductSelect(coordinator), CategorySelect(coordinator)])


class _SelectionSelect(CoordinatorEntity[GroceryTrackerCoordinator], SelectEntity, RestoreEntity):
    """A select whose choice is kept in the coordinator for the buttons."""

    _attr_has_entity_name = True
    _selection_key: str

    def __init__(self, coordinator: GroceryTrackerCoordinator) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_select_{self._selection_key}"
        self._attr_device_info = _device_info(entry_id)

    @property
    def current_option(self) -> str | None:
        """Return the chosen option while it still exists."""
        option = self.coordinator.selection.get(self._selection_key)
        return option if option in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Remember the choice."""
        self.coordinator.selection[self._selection_key] = option
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the choice; the entry reloads when a product is watched."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self.coordinator.selection.setdefault(self._selection_key, state.state)


class ProductSelect(_SelectionSelect):
    """All purchased products, most frequently bought first."""

    _attr_translation_key = "product"
    _selection_key = SELECTED_PRODUCT

    @property
    def options(self) -> list[str]:
        """Return the product names."""
        return self.coordinator.data.product_names


class CategorySelect(_SelectionSelect):
    """Built-in categories (translated) and custom categories (by name)."""

    _attr_translation_key = "category"
    _selection_key = SELECTED_CATEGORY

    @property
    def options(self) -> list[str]:
        """Return built-in category keys and custom category names."""
        return [
            *CATEGORIES,
            *(category.name for category in self.coordinator.store.custom_categories),
        ]
