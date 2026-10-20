"""Config flow for the Grocery Tracker integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    CONF_DESCRIPTION,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import slugify
from homeassistant.util.ssl import client_context

from .const import (
    CONF_FOLDER,
    CONF_INBOX_PATH,
    CONF_KEY,
    CONF_KEYWORDS,
    CONF_SENDER,
    CONF_SERVER,
    CONF_SINCE,
    CONF_WATCHED_PRODUCTS,
    DEFAULT_INBOX_DIR,
    DOMAIN,
    SUBENTRY_CATEGORY,
    SUBENTRY_MAILBOX,
)
from .coordinator import GroceryTrackerConfigEntry, mailbox_config
from .mail import (
    DEFAULT_FOLDER,
    DEFAULT_PORT,
    DEFAULT_SENDER,
    DEFAULT_SERVER,
    MailAuthError,
    Mailbox,
    MailboxConfig,
    MailConnectionError,
    MailFolderError,
)


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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Mailboxes and custom categories are added as subentries."""
        return {SUBENTRY_MAILBOX: MailboxSubentryFlow, SUBENTRY_CATEGORY: CategorySubentryFlow}

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


class GroceryTrackerOptionsFlow(OptionsFlow):
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


def _mailbox_schema(defaults: Mapping[str, Any], password_required: bool) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SERVER, default=defaults.get(CONF_SERVER, DEFAULT_SERVER)): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, vol.UNDEFINED)): str,
            (vol.Required if password_required else vol.Optional)(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_FOLDER, default=defaults.get(CONF_FOLDER, DEFAULT_FOLDER)): str,
            vol.Required(CONF_SENDER, default=defaults.get(CONF_SENDER, DEFAULT_SENDER)): str,
            vol.Required(
                CONF_SINCE,
                default=defaults.get(CONF_SINCE, date(date.today().year, 1, 1).isoformat()),
            ): DateSelector(),
        }
    )


def _unique_id(data: Mapping[str, Any]) -> str:
    return f"{data[CONF_SERVER]}:{data[CONF_USERNAME]}:{data[CONF_FOLDER]}".lower()


def _title(data: Mapping[str, Any]) -> str:
    return f"{data[CONF_USERNAME]} ({data[CONF_FOLDER]})"


def _test_mailbox(config: MailboxConfig) -> None:
    with Mailbox(config, client_context()):
        pass


class MailboxSubentryFlow(ConfigSubentryFlow):
    """Add or change an IMAP mailbox that receives eBons."""

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, str]:
        try:
            await self.hass.async_add_executor_job(_test_mailbox, mailbox_config(data))
        except MailAuthError:
            return {"base": "invalid_auth"}
        except MailFolderError:
            return {CONF_FOLDER: "folder_not_found"}
        except MailConnectionError:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Ask for the mailbox settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**user_input, CONF_PORT: int(user_input[CONF_PORT])}
            unique_id = _unique_id(data)
            if any(sub.unique_id == unique_id for sub in self._get_entry().subentries.values()):
                return self.async_abort(reason="already_configured")
            if not (errors := await self._async_validate(data)):
                return self.async_create_entry(
                    title=_title(data),
                    data=data,
                    unique_id=unique_id,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _mailbox_schema({}, password_required=True), user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the mailbox settings; an empty password keeps the old one."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                **user_input,
                CONF_PORT: int(user_input[CONF_PORT]),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD) or subentry.data[CONF_PASSWORD],
            }
            unique_id = _unique_id(data)
            if any(
                sub.unique_id == unique_id and sub.subentry_id != subentry.subentry_id
                for sub in self._get_entry().subentries.values()
            ):
                return self.async_abort(reason="already_configured")
            if not (errors := await self._async_validate(data)):
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=_title(data),
                    data=data,
                    unique_id=unique_id,
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_mailbox_schema(subentry.data, password_required=False),
            errors=errors,
        )


def _category_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, vol.UNDEFINED)): str,
            vol.Optional(CONF_KEYWORDS, default=defaults.get(CONF_KEYWORDS, "")): str,
            vol.Optional(CONF_DESCRIPTION, default=defaults.get(CONF_DESCRIPTION, "")): str,
        }
    )


class CategorySubentryFlow(ConfigSubentryFlow):
    """Add or change a custom category."""

    def _name_taken(self, name: str, own_subentry_id: str | None = None) -> bool:
        folded = name.strip().casefold()
        return any(
            sub.subentry_type == SUBENTRY_CATEGORY
            and sub.subentry_id != own_subentry_id
            and sub.data[CONF_NAME].strip().casefold() == folded
            for sub in self._get_entry().subentries.values()
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Ask for name, keywords and description."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            # The key never changes, so assignments survive renaming the category.
            key = f"custom_{slugify(name)}"
            if not any(char.isalnum() for char in name):
                errors[CONF_NAME] = "invalid_name"
            elif self._name_taken(name) or any(
                sub.unique_id == key for sub in self._get_entry().subentries.values()
            ):
                errors[CONF_NAME] = "name_exists"
            else:
                return self.async_create_entry(
                    title=name,
                    data={**user_input, CONF_NAME: name, CONF_KEY: key},
                    unique_id=key,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_category_schema({}), user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change name, keywords or description."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not any(char.isalnum() for char in name):
                errors[CONF_NAME] = "invalid_name"
            elif self._name_taken(name, subentry.subentry_id):
                errors[CONF_NAME] = "name_exists"
            else:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=name,
                    data={**user_input, CONF_NAME: name, CONF_KEY: subentry.data[CONF_KEY]},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_category_schema(subentry.data),
            errors=errors,
        )
