"""Config flow for the Grocery Tracker integration."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_INBOX_PATH, DEFAULT_INBOX_DIR, DOMAIN


class GroceryTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of Grocery Tracker."""

    VERSION = 1

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
