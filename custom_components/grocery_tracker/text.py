"""Text inputs for creating a custom category from a dashboard."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import GroceryTrackerConfigEntry, GroceryTrackerCoordinator
from .sensor import _device_info

NEW_CATEGORY_NAME = "new_category_name"
NEW_CATEGORY_KEYWORDS = "new_category_keywords"
NEW_CATEGORY_ICON = "new_category_icon"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroceryTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the text inputs."""
    coordinator = entry.runtime_data
    async_add_entities(
        SelectionText(coordinator, key)
        for key in (NEW_CATEGORY_NAME, NEW_CATEGORY_KEYWORDS, NEW_CATEGORY_ICON)
    )


class SelectionText(TextEntity, RestoreEntity):
    """A text input whose value is kept in the coordinator for the buttons."""

    _attr_has_entity_name = True
    _attr_native_max = 255

    def __init__(self, coordinator: GroceryTrackerCoordinator, key: str) -> None:
        """Initialize the text input."""
        self._coordinator = coordinator
        self._key = key
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_text_{key}"
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> str:
        """Return the entered text."""
        return self._coordinator.selection.get(self._key) or ""

    async def async_set_value(self, value: str) -> None:
        """Remember the text."""
        self._coordinator.selection[self._key] = value
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the text and follow changes made by the buttons."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None and state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self._coordinator.selection.setdefault(self._key, state.state)
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))
