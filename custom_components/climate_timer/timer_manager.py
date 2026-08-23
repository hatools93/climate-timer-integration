"""Timer entity lifecycle management for Climate Timer integration.

Creates and removes timer helper entities using Home Assistant's public
helpers API. Uses multiple strategies in order of reliability:
1. async_create_item on the timer StorageCollection (immediate, no restart)
2. Direct storage file write (fallback, requires HA restart)
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
        _LOGGER.debug(
            "async_ensure_timer called for %s → expected timer: %s",
            climate_entity,
            timer_entity_id,
        )

        # Check if timer already exists in entity registry
        entity_reg = er.async_get(self.hass)
        entry = entity_reg.async_get(timer_entity_id)

        if entry is not None:
            _LOGGER.debug("Managed timer %s already exists in registry, reusing", timer_entity_id)
            return timer_entity_id

        # Also check hass.states in case it exists but isn't in registry yet
        if self.hass.states.get(timer_entity_id) is not None:
            _LOGGER.debug(
                "Managed timer %s found in states, reusing", timer_entity_id
            )
            return timer_entity_id

        # Create the timer
        _LOGGER.info("Creating managed timer %s for %s", timer_entity_id, climate_entity)
        try:
            await self._async_create_timer(climate_entity)
            _LOGGER.info("Successfully created managed timer %s", timer_entity_id)
        except Exception:
            _LOGGER.exception("Failed to create managed timer %s", timer_entity_id)
            raise

        return timer_entity_id

    async def _async_create_timer(self, climate_entity: str) -> None:
        """Create a timer helper entity.

        Strategy:
        1. Try the timer integration's StorageCollection via the component
           data (the official integration data pattern).
        2. Fall back to writing the .storage/timer file directly. This persists
           the timer but requires an HA restart to load it into memory.
        """
        slug = climate_entity.replace(".", "_")
        timer_id = f"{TIMER_PREFIX}{slug}"
        timer_name = f"Climate Timer - {_friendly_climate_name(self.hass, climate_entity)}"

        _LOGGER.debug(
            "Attempting to create timer id=%s, name=%s", timer_id, timer_name
        )

        # Strategy 1: Access StorageCollection via timer component data
        collection = self._get_timer_storage_collection()
        if collection is not None:
            _LOGGER.debug("Found timer StorageCollection, attempting creation")
            # Check if our timer ID already exists in the collection
            if timer_id in collection.data:
                _LOGGER.debug(
                    "Timer %s already exists in collection, skipping", timer_id
                )
                return

            try:
                await collection.async_create_item(
                    {
                        "id": timer_id,
                        "name": timer_name,
                        "duration": DEFAULT_DURATION,
                        "restore": True,
                    }
                )
                _LOGGER.info("Created timer %s via StorageCollection", timer_id)
                return
            except Exception:
                _LOGGER.warning(
                    "async_create_item failed for %s, trying fallback strategies",
                    timer_id,
                    exc_info=True,
                )

        # Strategy 2: Write directly to storage file (requires restart)
        _LOGGER.warning(
            "Timer StorageCollection not accessible for %s. Writing to storage file — "
            "a Home Assistant restart is required for the timer to appear.",
            timer_id,
        )
        await self._async_write_timer_to_storage(climate_entity, timer_name)

    def _get_timer_storage_collection(self) -> Any | None:
        """Try to get the timer StorageCollection.

        Attempts multiple known patterns across HA versions:
        1. hass.data["timer"] with a storage_collection attribute (modern HA)
        2. Websocket API registry introspection (older HA versions)

        Returns the StorageCollection if found, None otherwise.
        """
        # Pattern 1: Direct component data access (HA 2023.x+)
        # The timer integration stores its component data in hass.data["timer"]
        try:
            timer_data = self.hass.data.get("timer")
            if timer_data is not None:
                # In modern HA, timer_data is the StorageCollection directly
                # or a dict containing the collection
                collection = None

                if hasattr(timer_data, "async_create_item"):
                    collection = timer_data
                elif isinstance(timer_data, dict):
                    # Some versions store it under a key
                    for key in ("storage_collection", "collection"):
                        candidate = timer_data.get(key)
                        if candidate and hasattr(candidate, "async_create_item"):
                            collection = candidate
                            break

                if collection is not None:
                    _LOGGER.debug("Found timer StorageCollection via component data")
                    return collection
        except Exception:
            _LOGGER.debug("Could not access timer component data", exc_info=True)

        # Pattern 2: Websocket API introspection (fallback for older HA)
        try:
            ws_handlers = self.hass.data.get("websocket_api")
            if not ws_handlers:
                _LOGGER.debug("No websocket_api in hass.data")
                return None

            # Try both possible key formats
            handler_info = None
            for key in ("timer/create", "timer/list"):
                if key in ws_handlers:
                    handler_info = ws_handlers[key]
                    break

            if handler_info is None:
                _LOGGER.debug("No timer websocket handlers found")
                return None

            handler = handler_info[0] if isinstance(handler_info, tuple) else handler_info

            # Unwrap decorator layers (require_admin -> async_response -> bound method)
            unwrapped = handler
            for _ in range(10):
                inner = getattr(unwrapped, "__wrapped__", None)
                if inner is None:
                    break
                unwrapped = inner

            # unwrapped should now be the bound method
            ws_instance = getattr(unwrapped, "__self__", None)
            if ws_instance is None:
                _LOGGER.debug("Could not find __self__ on unwrapped handler")
                return None

            collection = getattr(ws_instance, "storage_collection", None)
            if collection is None:
                _LOGGER.debug("No storage_collection on websocket instance")
                return None

            # Verify it has the methods we need
            if not hasattr(collection, "async_create_item"):
                _LOGGER.debug("Collection missing async_create_item method")
                return None

            _LOGGER.debug("Found timer StorageCollection via websocket introspection")
            return collection
        except Exception:
            _LOGGER.debug("Could not access timer StorageCollection via websocket", exc_info=True)
            return None

    async def _async_write_timer_to_storage(
        self, climate_entity: str, timer_name: str
    ) -> None:
        """Write a timer entry directly to the .storage/timer file.

        This is the fallback when we can't access the in-memory collection.
        The timer will appear after the next HA restart.
        """
        slug = climate_entity.replace(".", "_")
        timer_id = f"{TIMER_PREFIX}{slug}"

        store: Store[dict[str, Any]] = Store(
            self.hass, _TIMER_STORAGE_VERSION, _TIMER_STORAGE_KEY
        )
        data = await store.async_load() or {}
        items: list[dict[str, Any]] = data.get("items", [])

        # Check if already present
        for item in items:
            if item.get("id") == timer_id:
                _LOGGER.debug(
                    "Timer %s already exists in storage file, skipping", timer_id
                )
                return

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
        _LOGGER.info(
            "Timer %s written to storage file. Restart HA for it to appear.", timer_id
        )

    async def async_remove_timer(self, timer_entity_id: str) -> None:
        """Remove a managed timer entity."""
        item_id = timer_entity_id.removeprefix("timer.")
        _LOGGER.debug("Removing managed timer: %s (item_id=%s)", timer_entity_id, item_id)

        # Strategy 1: Remove via StorageCollection
        collection = self._get_timer_storage_collection()
        if collection is not None:
            if item_id in collection.data:
                try:
                    await collection.async_delete_item(item_id)
                    _LOGGER.info("Removed timer %s via StorageCollection", timer_entity_id)
                    return
                except Exception:
                    _LOGGER.warning(
                        "Failed to remove timer %s via collection, trying storage file",
                        timer_entity_id,
                        exc_info=True,
                    )

        # Strategy 2: Remove from storage file
        store: Store[dict[str, Any]] = Store(
            self.hass, _TIMER_STORAGE_VERSION, _TIMER_STORAGE_KEY
        )
        data = await store.async_load() or {}
        items: list[dict[str, Any]] = data.get("items", [])

        original_len = len(items)
        items = [item for item in items if item.get("id") != item_id]

        if len(items) < original_len:
            data["items"] = items
            await store.async_save(data)

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
