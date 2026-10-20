"""Config flow for the Grocery Tracker integration."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_INBOX_PATH, CONF_WATCHED_PRODUCTS, DEFAULT_INBOX_DIR, DOMAIN
from .coordinator import GroceryTrackerConfigEntry


class GroceryTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of Grocery Tracker."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: GroceryTrackerConfigEntry,
    ) -> GroceryTrackerOptionsFlow:
        """Return the options flow."""
        return GroceryTrackerOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the inbox folder that receipts are dropped into."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Only admins can add integrations, so any absolute path is fine here.
            if os.path.isabs(user_input[CONF_INBOX_PATH]):
                return self.async_create_entry(title="Grocery Tracker", data=user_input)
            errors[CONF_INBOX_PATH] = "path_not_absolute"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INBOX_PATH, default=self.hass.config.path(DEFAULT_INBOX_DIR)
                    ): str,
                }
            ),
            errors=errors,
        )


class GroceryTrackerOptionsFlow(OptionsFlowWithReload):
    """Choose the products whose price is tracked as a sensor."""

    config_entry: GroceryTrackerConfigEntry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show all purchased products for selection."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")

        store = self.config_entry.runtime_data.store
        products = await self.hass.async_add_executor_job(store.products)
        watched = self.config_entry.options.get(CONF_WATCHED_PRODUCTS, [])
        names = sorted({product.name for product in products} | set(watched))
        purchases = {product.name: product.purchases for product in products}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_WATCHED_PRODUCTS, default=watched): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=name, label=f"{name} ({purchases.get(name, 0)}×)"
                                )
                                for name in names
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
