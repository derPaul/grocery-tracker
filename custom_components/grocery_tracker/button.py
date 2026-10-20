"""Button to check the mailboxes right away."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GroceryTrackerConfigEntry, GroceryTrackerCoordinator
from .sensor import _device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroceryTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([CheckMailboxesButton(entry.runtime_data)])


class CheckMailboxesButton(ButtonEntity):
    """Check all mailboxes for new eBons now."""

    _attr_has_entity_name = True
    _attr_translation_key = "check_mailboxes"

    def __init__(self, coordinator: GroceryTrackerCoordinator) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_check_mailboxes"
        self._attr_device_info = _device_info(entry_id)

    async def async_press(self) -> None:
        """Check the mailboxes."""
        await self._coordinator.async_check_mailboxes()
