"""Config flow for Climate Timer integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import DOMAIN


class ClimateTimerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climate Timer."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — select a climate entity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            climate_entity = user_input["climate_entity"]

            # Use climate entity as unique ID to prevent duplicates
            await self.async_set_unique_id(climate_entity)
            self._abort_if_unique_id_configured()

            # Validate entity exists and is in climate domain
            state = self.hass.states.get(climate_entity)
            if state is None:
                errors["climate_entity"] = "entity_not_found"
            elif not climate_entity.startswith("climate."):
                errors["climate_entity"] = "invalid_domain"
            else:
                return self.async_create_entry(
                    title=state.attributes.get("friendly_name", climate_entity),
                    data={"climate_entity": climate_entity},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("climate_entity"): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="climate")
                    ),
                }
            ),
            errors=errors,
        )
