"""The Grocery Tracker integration."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
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
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .ai import ai_task_available, async_categorize
from .categories import CATEGORIES, CategoryResolver
from .const import (
    ATTR_CATEGORY,
    ATTR_END,
    ATTR_ENTITY_ID,
    ATTR_MONTHS,
    ATTR_PATH,
    ATTR_PRODUCT,
    ATTR_RECEIPTS,
    ATTR_SEARCH,
    ATTR_START,
    ATTR_TOP,
    DATABASE_FILE,
    DOMAIN,
    MAIL_SCAN_INTERVAL,
    SERVICE_CATEGORIZE_PRODUCTS,
    SERVICE_CHECK_MAILBOXES,
    SERVICE_GET_STATISTICS,
    SERVICE_IMPORT_RECEIPT,
    SERVICE_LIST_PRODUCTS,
    SERVICE_SET_CATEGORY,
    SUBENTRY_CATEGORY,
)
from .coordinator import (
    GroceryTrackerConfigEntry,
    GroceryTrackerCoordinator,
    local_isoformat,
)
from .parsers import ReceiptParseError
from .storage import ReceiptStore

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

IMPORT_RECEIPT_SCHEMA = vol.Schema({vol.Required(ATTR_PATH): cv.string})
LIST_PRODUCTS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_SEARCH): cv.string,
        vol.Optional(ATTR_CATEGORY): cv.string,
    }
)
SET_CATEGORY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRODUCT): cv.string,
        vol.Required(ATTR_CATEGORY): cv.string,
    }
)
CATEGORIZE_PRODUCTS_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_id})
GET_STATISTICS_SCHEMA = vol.Schema(
    {
        vol.Exclusive(ATTR_MONTHS, "period"): vol.All(vol.Coerce(int), vol.Range(min=1, max=36)),
        vol.Exclusive(ATTR_START, "period"): cv.date,
        vol.Optional(ATTR_END): cv.date,
        vol.Optional(ATTR_TOP, default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional(ATTR_RECEIPTS, default=False): cv.boolean,
    }
)

MAX_STATISTICS_MONTHS = 36


def _month_start(value: date) -> datetime:
    return datetime(value.year, value.month, 1)


def _next_month(value: datetime) -> datetime:
    return datetime(value.year + value.month // 12, value.month % 12 + 1, 1)


def _statistics_period(data: dict) -> tuple[datetime, datetime]:
    """Return [start, end) for get_statistics: a date range or the last n months."""
    today = dt_util.now().replace(tzinfo=None).date()
    end_date = data.get(ATTR_END)
    if (start_date := data.get(ATTR_START)) is not None:
        start = datetime.combine(start_date, time())
        end = datetime.combine((end_date or today) + timedelta(days=1), time())
    else:
        end = datetime.combine((end_date or today) + timedelta(days=1), time())
        start = _month_start((end - timedelta(days=1)).date())
        for _ in range(data.get(ATTR_MONTHS, 1) - 1):
            start = _month_start((start - timedelta(days=1)).date())
    if end <= start:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_period")
    return start, end


def _category_key(resolver: CategoryResolver, value: str) -> str:
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
            "timestamp": local_isoformat(receipt.timestamp),
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
        store = coordinator.store
        products = await hass.async_add_executor_job(store.products, call.data.get(ATTR_SEARCH))
        resolver = await hass.async_add_executor_job(store.resolver)
        result = [
            {
                "name": product.name,
                "category": resolver.resolve(product.name),
                "purchases": product.purchases,
                "last_price": float(product.last_price),
                "unit": product.unit,
                "last_seen": local_isoformat(product.last_seen),
            }
            for product in products
        ]
        if (value := call.data.get(ATTR_CATEGORY)) is not None:
            key = _category_key(resolver, value)
            result = [product for product in result if product["category"] == key]
        return {"products": result}

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_PRODUCTS,
        list_products,
        schema=LIST_PRODUCTS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def set_category(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        product = call.data[ATTR_PRODUCT]
        if not await hass.async_add_executor_job(coordinator.store.has_product, product):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_product",
                translation_placeholders={"product": product},
            )
        resolver = await hass.async_add_executor_job(coordinator.store.resolver)
        key = _category_key(resolver, call.data[ATTR_CATEGORY])
        await hass.async_add_executor_job(coordinator.store.set_category, product, key, "manual")
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_SET_CATEGORY, set_category, schema=SET_CATEGORY_SCHEMA
    )

    async def categorize_products(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        if not ai_task_available(hass):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="ai_task_unavailable"
            )
        store = coordinator.store
        products = await hass.async_add_executor_job(store.products)
        resolver = await hass.async_add_executor_job(store.resolver)
        # Only products no rule knows and that were never categorized before.
        unknown = [product.name for product in products if resolver.is_unknown(product.name)]
        categorized = await async_categorize(hass, unknown, resolver, call.data.get(ATTR_ENTITY_ID))
        for name, category in categorized.items():
            await hass.async_add_executor_job(store.set_category, name, category, "ai")
        await coordinator.async_request_refresh()
        return {
            "categorized": categorized,
            "uncategorized": [name for name in unknown if name not in categorized],
        }

    async def check_mailboxes(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        statuses = await coordinator.async_check_mailboxes()
        entry = coordinator.config_entry
        return {
            "mailboxes": [
                {
                    "mailbox": entry.subentries[subentry_id].title,
                    "status": status.status,
                    "new_messages": status.new_messages,
                    "new_receipts": status.new_receipts,
                    "error": status.error,
                }
                for subentry_id, status in statuses.items()
                if subentry_id in entry.subentries
            ]
        }

    async def get_statistics(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        store = coordinator.store
        start, end = _statistics_period(call.data)

        def collect() -> dict:
            months = []
            month = _month_start(start.date())
            while month < end and len(months) < MAX_STATISTICS_MONTHS:
                lo, hi = max(month, start), min(_next_month(month), end)
                months.append(
                    {
                        "month": month.strftime("%Y-%m"),
                        "amount": float(store.spending_between(lo, hi)),
                        "receipts": store.receipt_count_between(lo, hi),
                        "by_category": {
                            category: float(amount)
                            for category, amount in store.spending_by_category(lo, hi).items()
                        },
                    }
                )
                month = _next_month(month)
            result = {
                "start": start.date().isoformat(),
                "end": (end - timedelta(days=1)).date().isoformat(),
                "total": float(store.spending_between(start, end)),
                "receipts": store.receipt_count_between(start, end),
                "by_category": {
                    category: float(amount)
                    for category, amount in store.spending_by_category(start, end).items()
                },
                "top_products": [
                    {
                        "name": product.name,
                        "category": product.category,
                        "amount": float(product.amount),
                        "purchases": product.purchases,
                    }
                    for product in store.top_products(start, end, call.data[ATTR_TOP])
                ],
                "months": months,
            }
            if call.data[ATTR_RECEIPTS]:
                result["receipt_list"] = [
                    {
                        "uid": receipt.uid,
                        "store": receipt.store,
                        "timestamp": local_isoformat(receipt.timestamp),
                        "total": float(receipt.total),
                        "item_count": receipt.item_count,
                    }
                    for receipt in store.receipts_between(start, end)
                ]
            return result

        return await hass.async_add_executor_job(collect)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_STATISTICS,
        get_statistics,
        schema=GET_STATISTICS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHECK_MAILBOXES,
        check_mailboxes,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CATEGORIZE_PRODUCTS,
        categorize_products,
        schema=CATEGORIZE_PRODUCTS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GroceryTrackerConfigEntry) -> bool:
    """Set up Grocery Tracker from a config entry."""
    _async_unlink_categories_from_main_device(hass, entry)
    store = ReceiptStore(hass.config.path(DATABASE_FILE))
    coordinator = GroceryTrackerCoordinator(hass, entry, store)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Repair issues of mailboxes that were removed.
    mailbox_issues = {f"mailbox_{subentry_id}" for subentry_id in entry.subentries}
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id.startswith("mailbox_") and issue_id not in mailbox_issues:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    async def check_mailboxes(_: datetime | None = None) -> None:
        await coordinator.async_check_mailboxes()

    entry.async_on_unload(async_track_time_interval(hass, check_mailboxes, MAIL_SCAN_INTERVAL))
    # The first scan may go back a long way; don't block startup with it.
    entry.async_create_background_task(hass, check_mailboxes(), f"{DOMAIN} mailbox check")
    # Options and mailboxes (subentries) changed: reload.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


@callback
def _async_unlink_categories_from_main_device(
    hass: HomeAssistant, entry: GroceryTrackerConfigEntry
) -> None:
    """Repair installations of 0.8.0.

    0.8.0 registered custom category sensors on the main device under their
    category subentry. That links the main device to the subentry, and the
    frontend then lists the device and all its entities under the category.
    Move the sensors to the main entry first (unlinking the device would
    otherwise remove them), then unlink the device.
    """
    categories = {
        subentry_id
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_CATEGORY
    }
    if not categories:
        return
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.config_subentry_id in categories:
            entity_registry.async_update_entity(entity.entity_id, config_subentry_id=None)
    device_registry = dr.async_get(hass)
    if device := device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)}):
        for subentry_id in categories & device.config_entries_subentries.get(entry.entry_id, set()):
            device_registry.async_update_device(
                device.id,
                remove_config_entry_id=entry.entry_id,
                remove_config_subentry_id=subentry_id,
            )


async def _async_reload(hass: HomeAssistant, entry: GroceryTrackerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GroceryTrackerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
