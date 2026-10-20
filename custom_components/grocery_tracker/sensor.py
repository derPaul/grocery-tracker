"""Sensors for the Grocery Tracker integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GroceryStats, GroceryTrackerConfigEntry, GroceryTrackerCoordinator


@dataclass(frozen=True, kw_only=True)
class GrocerySensorEntityDescription(SensorEntityDescription):
    """Describes a Grocery Tracker sensor."""

    value_fn: Callable[[GroceryStats], Decimal | int | None]
    attrs_fn: Callable[[GroceryStats], dict[str, Any] | None] = lambda _: None


def _last_receipt_attrs(stats: GroceryStats) -> dict[str, Any] | None:
    if (last := stats.last_receipt) is None:
        return None
    return {
        "store": last.store,
        "timestamp": last.timestamp.isoformat(),
        "item_count": last.item_count,
    }


SENSORS: tuple[GrocerySensorEntityDescription, ...] = (
    GrocerySensorEntityDescription(
        key="spending_this_week",
        translation_key="spending_this_week",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda s: s.spending_this_week,
    ),
    GrocerySensorEntityDescription(
        key="spending_this_month",
        translation_key="spending_this_month",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda s: s.spending_this_month,
    ),
    GrocerySensorEntityDescription(
        key="spending_last_month",
        translation_key="spending_last_month",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda s: s.spending_last_month,
    ),
    GrocerySensorEntityDescription(
        key="receipts_this_month",
        translation_key="receipts_this_month",
        value_fn=lambda s: s.receipts_this_month,
    ),
    GrocerySensorEntityDescription(
        key="last_receipt_total",
        translation_key="last_receipt_total",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda s: s.last_receipt.total if s.last_receipt else None,
        attrs_fn=_last_receipt_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroceryTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(GrocerySensor(coordinator, description) for description in SENSORS)


class GrocerySensor(CoordinatorEntity[GroceryTrackerCoordinator], SensorEntity):
    """A Grocery Tracker statistic."""

    _attr_has_entity_name = True
    entity_description: GrocerySensorEntityDescription

    def __init__(
        self,
        coordinator: GroceryTrackerCoordinator,
        description: GrocerySensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Grocery Tracker",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Decimal | int | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attrs_fn(self.coordinator.data)
