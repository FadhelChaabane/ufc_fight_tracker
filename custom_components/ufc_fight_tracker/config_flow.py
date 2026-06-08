"""Config flow for UFC Fight Tracker integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)

def get_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("stats_mode", default=defaults.get("stats_mode", "Lite")): vol.In(["Lite", "Full Stats"]),
        vol.Required("keep_days", default=defaults.get("keep_days", 3)): vol.All(vol.Coerce(int), vol.Range(min=1, max=7)),
    })

class UFCConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UFC Fight Tracker."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return UFCOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title=DEFAULT_NAME, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=get_schema({})
        )


class UFCOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for UFC Fight Tracker."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get existing options or fallback to data
        defaults = self.config_entry.options or self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=get_schema(defaults),
        )
