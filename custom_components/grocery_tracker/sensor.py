"""Sensors for the Grocery Tracker integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME, CURRENCY_EURO, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .categories import CATEGORIES
from .const import CONF_KEY, DOMAIN, SUBENTRY_CATEGORY, SUBENTRY_MAILBOX
from .coordinator import (
    MAILBOX_STATES,
    GroceryStats,
    GroceryTrackerConfigEntry,
    GroceryTrackerCoordinator,
    MailboxStatus,
    local_isoformat,
)


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
        "timestamp": local_isoformat(last.timestamp),
        "item_count": last.item_count,
        "items": [
            {
                "name": item.name,
                "category": item.category,
                "quantity": float(item.quantity),
                "unit": item.unit,
                "unit_price": None if item.unit_price is None else float(item.unit_price),
                "total": float(item.total),
            }
            for item in stats.last_receipt_items
        ],
    }


def _spending_this_month_attrs(stats: GroceryStats) -> dict[str, Any]:
    return {
        "top_products": [
            {
                "name": product.name,
                "category": product.category,
                "amount": float(product.amount),
                "purchases": product.purchases,
            }
            for product in stats.top_products_this_month
        ]
    }


def _device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="Grocery Tracker",
        entry_type=DeviceEntryType.SERVICE,
    )


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
        attrs_fn=_spending_this_month_attrs,
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
        key="spending_this_year",
        translation_key="spending_this_year",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda s: s.spending_this_year,
        attrs_fn=lambda s: {
            "last_12_months": [
                {"month": month, "amount": float(amount), "receipts": receipts}
                for month, amount, receipts in s.last_12_months
            ]
        },
    ),
    GrocerySensorEntityDescription(
        key="receipts_total",
        translation_key="receipts_total",
        value_fn=lambda s: s.receipts_total,
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

CATEGORY_SENSORS: tuple[GrocerySensorEntityDescription, ...] = tuple(
    GrocerySensorEntityDescription(
        key=f"spending_this_month_{category}",
        translation_key=f"spending_this_month_{category}",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda s, category=category: s.spending_by_category_this_month[category],
    )
    for category in CATEGORIES
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GroceryTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    watched = coordinator.watched_products

    # Remove price sensors of products that are no longer watched.
    registry = er.async_get(hass)
    price_prefix = f"{entry.entry_id}_price_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.unique_id.startswith(price_prefix)
            and entity.unique_id.removeprefix(price_prefix) not in watched
        ):
            registry.async_remove(entity.entity_id)

    async_add_entities(
        [
            *(
                GrocerySensor(coordinator, description)
                for description in (*SENSORS, *CATEGORY_SENSORS)
            ),
            *(PriceSensor(coordinator, product) for product in watched),
        ]
    )
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_MAILBOX:
            async_add_entities(
                [
                    MailboxSensor(coordinator, subentry.subentry_id, subentry.title, description)
                    for description in MAILBOX_SENSORS
                ],
                config_subentry_id=subentry.subentry_id,
            )
        elif subentry.subentry_type == SUBENTRY_CATEGORY:
            async_add_entities(
                [GrocerySensor(coordinator, _custom_category_description(subentry.data))],
                config_subentry_id=subentry.subentry_id,
            )


def _custom_category_description(data: Mapping[str, Any]) -> GrocerySensorEntityDescription:
    key = data[CONF_KEY]
    return GrocerySensorEntityDescription(
        key=f"spending_this_month_{key}",
        translation_key="spending_this_month_custom",
        translation_placeholders={"category": data[CONF_NAME]},
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda s: s.spending_by_category_this_month.get(key, Decimal("0.00")),
    )


class GrocerySensor(CoordinatorEntity[GroceryTrackerCoordinator], SensorEntity):
    """A Grocery Tracker statistic."""

    _attr_has_entity_name = True
    # Item lists change with every receipt; keep them out of the recorder.
    _unrecorded_attributes = frozenset({"items", "top_products", "last_12_months"})
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
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> Decimal | int | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attrs_fn(self.coordinator.data)


class PriceSensor(CoordinatorEntity[GroceryTrackerCoordinator], SensorEntity):
    """Latest price of a watched product (per piece or per kg)."""

    _attr_has_entity_name = True
    _attr_translation_key = "price"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: GroceryTrackerCoordinator, product: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._product = product
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_price_{product}"
        self._attr_translation_placeholders = {"product": product}
        self._attr_device_info = _device_info(entry_id)

    @property
    def native_value(self) -> Decimal | None:
        """Return the latest price."""
        if (stats := self.coordinator.data.prices.get(self._product)) is None:
            return None
        return stats.last

    @property
    def native_unit_of_measurement(self) -> str:
        """Return EUR, or EUR/kg for products sold by weight."""
        stats = self.coordinator.data.prices.get(self._product)
        if stats is not None and stats.unit == "kg":
            return f"{CURRENCY_EURO}/kg"
        return CURRENCY_EURO

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the condensed price history."""
        if (stats := self.coordinator.data.prices.get(self._product)) is None:
            return None
        return {
            "product": self._product,
            "previous_price": None if stats.previous is None else float(stats.previous),
            "change_percent": stats.change_percent,
            "min_price": float(stats.minimum),
            "max_price": float(stats.maximum),
            "average_price": float(stats.average),
            "purchases": stats.purchases,
            "last_seen": local_isoformat(stats.last_seen),
        }


@dataclass(frozen=True, kw_only=True)
class MailboxSensorEntityDescription(SensorEntityDescription):
    """Describes a mailbox sensor."""

    value_fn: Callable[[MailboxStatus], datetime | str]


MAILBOX_SENSORS: tuple[MailboxSensorEntityDescription, ...] = (
    MailboxSensorEntityDescription(
        key="last_check",
        translation_key="mailbox_last_check",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.last_check,
    ),
    MailboxSensorEntityDescription(
        key="status",
        translation_key="mailbox_status",
        device_class=SensorDeviceClass.ENUM,
        options=MAILBOX_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.status,
    ),
)


class MailboxSensor(CoordinatorEntity[GroceryTrackerCoordinator], SensorEntity):
    """Result of the last check of one mailbox."""

    _attr_has_entity_name = True
    entity_description: MailboxSensorEntityDescription

    def __init__(
        self,
        coordinator: GroceryTrackerCoordinator,
        subentry_id: str,
        title: str,
        description: MailboxSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._subentry_id = subentry_id
        self._attr_unique_id = f"{subentry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry_id)},
            name=title,
            entry_type=DeviceEntryType.SERVICE,
            via_device=(DOMAIN, coordinator.config_entry.entry_id),
        )

    @property
    def _status(self) -> MailboxStatus | None:
        return self.coordinator.mailbox_status.get(self._subentry_id)

    @property
    def native_value(self) -> datetime | str | None:
        """Return the value; unknown until the first check finished."""
        if (status := self._status) is None:
            return None
        return self.entity_description.value_fn(status)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return what the last check found."""
        if (status := self._status) is None:
            return None
        return {
            "new_messages": status.new_messages,
            "new_receipts": status.new_receipts,
            "error": status.error,
        }
