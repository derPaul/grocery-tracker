"""Buttons for checking mailboxes and managing products from a dashboard."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import GroceryTrackerConfigEntry, GroceryTrackerCoordinator
from .management import async_assign_category, async_set_watched, create_category
from .select import SELECTED_CATEGORY, SELECTED_PRODUCT
from .sensor import _device_info
from .text import NEW_CATEGORY_ICON, NEW_CATEGORY_KEYWORDS, NEW_CATEGORY_NAME


def _selected(coordinator: GroceryTrackerCoordinator, key: str) -> str:
    """Return what is chosen in a dashboard control, or explain what is missing."""
    if not (value := (coordinator.selection.get(key) or "").strip()):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key=f"no_{key}")
    return value


async def _watch(hass: HomeAssistant, coordinator: GroceryTrackerCoordinator) -> None:
    product = _selected(coordinator, SELECTED_PRODUCT)
    await async_set_watched(hass, coordinator.config_entry, product, True)


async def _unwatch(hass: HomeAssistant, coordinator: GroceryTrackerCoordinator) -> None:
    product = _selected(coordinator, SELECTED_PRODUCT)
    await async_set_watched(hass, coordinator.config_entry, product, False)


async def _assign(hass: HomeAssistant, coordinator: GroceryTrackerCoordinator) -> None:
    product = _selected(coordinator, SELECTED_PRODUCT)
    category = _selected(coordinator, SELECTED_CATEGORY)
    await async_assign_category(hass, coordinator, product, category)


async def _create(hass: HomeAssistant, coordinator: GroceryTrackerCoordinator) -> None:
    name = _selected(coordinator, NEW_CATEGORY_NAME)
    keywords = coordinator.selection.get(NEW_CATEGORY_KEYWORDS) or ""
    icon = coordinator.selection.get(NEW_CATEGORY_ICON) or ""
    # Clear the inputs first: creating the category starts the reload right
    # away, and the inputs restore whatever state they have at that moment.
    _set_inputs(coordinator, "", "", "")
    try:
        create_category(hass, coordinator.config_entry, name, keywords, icon=icon)
    except ServiceValidationError:
        _set_inputs(coordinator, name, keywords, icon)
        raise


def _set_inputs(
    coordinator: GroceryTrackerCoordinator, name: str, keywords: str, icon: str
) -> None:
    coordinator.selection[NEW_CATEGORY_NAME] = name
    coordinator.selection[NEW_CATEGORY_KEYWORDS] = keywords
    coordinator.selection[NEW_CATEGORY_ICON] = icon
    coordinator.async_update_listeners()


async def _check_mailboxes(hass: HomeAssistant, coordinator: GroceryTrackerCoordinator) -> None:
    await coordinator.async_check_mailboxes()


@dataclass(frozen=True, kw_only=True)
class GroceryButtonEntityDescription(ButtonEntityDescription):
    """Describes a Grocery Tracker button."""

    press_fn: Callable[[HomeAssistant, GroceryTrackerCoordinator], Awaitable[None]]


BUTTONS: tuple[GroceryButtonEntityDescription, ...] = (
    GroceryButtonEntityDescription(key="check_mailboxes", press_fn=_check_mailboxes),
    GroceryButtonEntityDescription(key="watch_product", press_fn=_watch),
    GroceryButtonEntityDescription(key="unwatch_product", press_fn=_unwatch),
    GroceryButtonEntityDescription(key="assign_category", press_fn=_assign),
    GroceryButtonEntityDescription(key="create_category", press_fn=_create),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroceryTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    async_add_entities(GroceryButton(entry.runtime_data, description) for description in BUTTONS)


class GroceryButton(ButtonEntity):
    """A Grocery Tracker button."""

    _attr_has_entity_name = True
    entity_description: GroceryButtonEntityDescription

    def __init__(
        self, coordinator: GroceryTrackerCoordinator, description: GroceryButtonEntityDescription
    ) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry_id)

    async def async_press(self) -> None:
        """Run the button's action."""
        await self.entity_description.press_fn(self.hass, self._coordinator)
