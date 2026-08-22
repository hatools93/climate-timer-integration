"""Timer entity lifecycle management for Climate Timer integration.

Creates and removes timer helper entities by writing directly to the timer
integration's storage collection (.storage/timer) and reloading.  This is
the same mechanism the HA UI uses — the timer integration exposes CRUD via
websocket commands that read/write this storage file.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DEFAULT_DURATION, TIMER_PREFIX, get_timer_entity_id

_LOGGER = logging.getLogger(__name__)

# Timer integration storage constants (mirrors homeassistant/components/timer)
_TIMER_STORAGE_KEY = "timer"
_TIMER_STORAGE_VERSION = 1


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

        # Create the timer by writing to the timer storage collection
        _LOGGER.info("Creating managed timer %s", timer_entity_id)
        try:
            await self._async_create_timer_in_storage(climate_entity)
        except Exception:
            _LOGGER.exception("Failed to create managed timer %s", timer_entity_id)
            raise

        return timer_entity_id

    async def _async_create_timer_in_storage(self, climate_entity: str) -> None:
        """Create a timer helper by writing to the timer storage and reloading.

        This writes directly to .storage/timer (the same store the timer
        integration uses) and then triggers a reload so the new entity is
        picked up immediately.
        """
        slug = climate_entity.replace(".", "_")
        timer_id = f"{TIMER_PREFIX}{slug}"
        timer_name = f"Climate Timer - {_friendly_climate_name(self.hass, climate_entity)}"

        store: Store[dict[str, Any]] = Store(
            self.hass, _TIMER_STORAGE_VERSION, _TIMER_STORAGE_KEY
        )
        data = await store.async_load() or {}
        items: list[dict[str, Any]] = data.get("items", [])

        # Check if already present (e.g. from a previous failed setup)
        for item in items:
            if item.get("id") == timer_id:
                _LOGGER.debug(
                    "Timer %s already exists in storage, skipping creation", timer_id
                )
                return

        # Append the new timer entry
        items.append(
            {
                "id": timer_id,
                "name": timer_name,
                "duration": DEFAULT_DURATION,
                "restore": True,
            }
        )
        data["items"] = items
        await store.async_save(data)

        # Reload the timer integration so it picks up the new entity
        await self.hass.services.async_call(
            "timer", "reload", {}, blocking=True
        )

    async def async_remove_timer(self, timer_entity_id: str) -> None:
        """Remove a managed timer entity.

        Removes the timer from the storage collection and reloads.
        """
        # Derive the storage item ID from the entity_id
        # timer.climate_timer_climate_xxx -> climate_timer_climate_xxx
        item_id = timer_entity_id.removeprefix("timer.")

        store: Store[dict[str, Any]] = Store(
            self.hass, _TIMER_STORAGE_VERSION, _TIMER_STORAGE_KEY
        )
        data = await store.async_load() or {}
        items: list[dict[str, Any]] = data.get("items", [])

        # Find and remove the item
        original_len = len(items)
        items = [item for item in items if item.get("id") != item_id]

        if len(items) == original_len:
            _LOGGER.debug(
                "Timer %s not found in storage, nothing to remove", timer_entity_id
            )
            return

        data["items"] = items
        await store.async_save(data)

        # Reload timer integration to reflect the removal
        try:
            await self.hass.services.async_call(
                "timer", "reload", {}, blocking=True
            )
        except Exception:
            _LOGGER.warning(
                "Failed to reload timer integration after removing %s",
                timer_entity_id,
                exc_info=True,
            )

        # Also remove from entity registry if still present
        entity_reg = er.async_get(self.hass)
        if entity_reg.async_get(timer_entity_id):
            entity_reg.async_remove(timer_entity_id)

        _LOGGER.info("Removed managed timer %s", timer_entity_id)


def _friendly_climate_name(hass: HomeAssistant, climate_entity: str) -> str:
    """Get a friendly name for the climate entity, falling back to the entity_id."""
    state = hass.states.get(climate_entity)
    if state and state.attributes.get("friendly_name"):
        return state.attributes["friendly_name"]
    # Strip domain prefix for a reasonable default
    return climate_entity.removeprefix("climate.").replace("_", " ").title()
