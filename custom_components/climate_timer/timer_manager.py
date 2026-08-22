"""Timer entity lifecycle management for Climate Timer integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_DURATION, get_timer_entity_id

_LOGGER = logging.getLogger(__name__)


class TimerManager:
    """Manages creation and deletion of timer helper entities."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the timer manager."""
        self.hass = hass

    async def async_ensure_timer(self, climate_entity: str) -> str:
        """Ensure a managed timer entity exists for the given climate entity.

        Creates the timer helper if it doesn't already exist.
        Returns the timer entity_id.
        """
        timer_entity_id = get_timer_entity_id(climate_entity)

        # Check if timer already exists in entity registry
        entity_reg = er.async_get(self.hass)
        entry = entity_reg.async_get(timer_entity_id)

        if entry is not None:
            _LOGGER.debug("Managed timer %s already exists, reusing", timer_entity_id)
            return timer_entity_id

        # Also check hass.states in case it exists but isn't in registry yet
        if self.hass.states.get(timer_entity_id) is not None:
            _LOGGER.debug(
                "Managed timer %s found in states, reusing", timer_entity_id
            )
            return timer_entity_id

        # Create the timer via the timer integration's helper collection
        _LOGGER.info("Creating managed timer %s", timer_entity_id)
        try:
            # Use the timer integration's websocket/service API to create a helper
            # The timer helpers are managed via hass.helpers collection
            timer_collection = self.hass.data.get("timer")
            if timer_collection and hasattr(timer_collection, "async_create_item"):
                # Timer integration exposes a collection for CRUD
                slug = climate_entity.replace(".", "_")
                await timer_collection.async_create_item(
                    {
                        "id": f"climate_timer_{slug}",
                        "name": f"Climate Timer - {climate_entity}",
                        "duration": DEFAULT_DURATION,
                        "restore": True,
                    }
                )
            else:
                # Fallback: use the input helper creation via config entries
                # This creates a timer helper through the standard HA mechanism
                from homeassistant.components.timer import (
                    DOMAIN as TIMER_DOMAIN,
                )

                await self.hass.services.async_call(
                    "homeassistant",
                    "reload_config_entry",
                    {},
                    blocking=True,
                )
                _LOGGER.warning(
                    "Timer collection not available. Timer %s may need manual creation.",
                    timer_entity_id,
                )
        except Exception:
            _LOGGER.exception("Failed to create managed timer %s", timer_entity_id)
            raise

        return timer_entity_id

    async def async_remove_timer(self, timer_entity_id: str) -> None:
        """Remove a managed timer entity.

        Logs a warning if removal fails but does not raise.
        """
        entity_reg = er.async_get(self.hass)
        entry = entity_reg.async_get(timer_entity_id)

        if entry is None:
            _LOGGER.debug("Timer %s not found in registry, nothing to remove", timer_entity_id)
            return

        try:
            # Remove from the timer collection if available
            timer_collection = self.hass.data.get("timer")
            if timer_collection and hasattr(timer_collection, "async_delete_item"):
                # The item ID is stored in the unique_id or we derive it
                config_entry_id = entry.config_entry_id
                if config_entry_id:
                    await timer_collection.async_delete_item(entry.unique_id)
                else:
                    # For helpers without config entries, remove from entity registry
                    entity_reg.async_remove(timer_entity_id)
            else:
                entity_reg.async_remove(timer_entity_id)

            _LOGGER.info("Removed managed timer %s", timer_entity_id)
        except Exception:
            _LOGGER.warning(
                "Failed to remove managed timer %s", timer_entity_id, exc_info=True
            )
