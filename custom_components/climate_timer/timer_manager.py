"""Timer entity lifecycle management for Climate Timer integration.

Creates and removes timer helper entities by interacting with the timer
integration's StorageCollection. The collection is accessed via the
websocket command registry where it is exposed as ``timer/create``.

Falls back to writing directly to .storage/timer if the collection is
not accessible (which requires a single HA restart to take effect).
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

        # Create the timer
        _LOGGER.info("Creating managed timer %s", timer_entity_id)
        try:
            await self._async_create_timer(climate_entity)
        except Exception:
            _LOGGER.exception("Failed to create managed timer %s", timer_entity_id)
            raise

        return timer_entity_id

    async def _async_create_timer(self, climate_entity: str) -> None:
        """Create a timer helper entity.

        Strategy:
        1. Try to access the timer StorageCollection via the websocket command
           registry and inject the item directly (works immediately, no restart
           needed, and gives us control over the entity ID).
        2. Fall back to writing the .storage/timer file directly. This persists
           the timer but requires an HA restart to load it into memory.
        """
        slug = climate_entity.replace(".", "_")
        timer_id = f"{TIMER_PREFIX}{slug}"
        timer_name = f"Climate Timer - {_friendly_climate_name(self.hass, climate_entity)}"

        # Strategy 1: Access the StorageCollection via websocket registry
        collection = self._get_timer_storage_collection()
        if collection is not None:
            # Check if our timer ID already exists in the collection
            if timer_id in collection.data:
                _LOGGER.debug(
                    "Timer %s already exists in collection, skipping", timer_id
                )
                return

            # Inject directly into the collection with our chosen ID.
            # We validate the data the same way the collection would, then
            # insert it and trigger change notifications so the entity is
            # created immediately.
            from homeassistant.helpers.collection import CHANGE_ADDED, CollectionChange

            validated_data = await collection._process_create_data(
                {
                    "name": timer_name,
                    "duration": DEFAULT_DURATION,
                    "restore": True,
                }
            )
            item = collection._create_item(timer_id, validated_data)
            collection.data[timer_id] = item
            collection._async_schedule_save()

            # Compute the item hash for entity registry change detection
            serialized = collection._serialize_item(timer_id, item)
            item_hash = collection._hash_item(serialized) if hasattr(collection, "_hash_item") else None

            await collection.notify_changes(
                [CollectionChange(CHANGE_ADDED, timer_id, item, item_hash)]
            )
            _LOGGER.info("Created timer via StorageCollection (no restart needed)")
            return

        # Strategy 2: Write directly to storage file (requires restart)
        _LOGGER.warning(
            "Timer StorageCollection not accessible. Writing to storage file — "
            "a Home Assistant restart is required for the timer to appear."
        )
        await self._async_write_timer_to_storage(climate_entity, timer_name)

    def _get_timer_storage_collection(self) -> Any | None:
        """Try to get the timer StorageCollection from the websocket registry.

        The timer integration registers a DictStorageCollectionWebsocket which
        exposes 'timer/create' as a websocket command. The handler chain is:
            require_admin(async_response(self.ws_create_item))
        Each decorator uses @wraps, so we follow __wrapped__ to reach the
        bound method, then access __self__.storage_collection.

        Returns the StorageCollection if found, None otherwise.
        """
        try:
            ws_handlers = self.hass.data.get("websocket_api")
            if not ws_handlers or "timer/create" not in ws_handlers:
                return None

            handler, _schema = ws_handlers["timer/create"]

            # Unwrap decorator layers (require_admin -> async_response -> bound method)
            unwrapped = handler
            for _ in range(10):
                inner = getattr(unwrapped, "__wrapped__", None)
                if inner is None:
                    break
                unwrapped = inner

            # unwrapped should now be the bound method ws_create_item
            ws_instance = getattr(unwrapped, "__self__", None)
            if ws_instance is None:
                return None

            collection = getattr(ws_instance, "storage_collection", None)
            if collection is None:
                return None

            # Verify it has the methods we need
            if not hasattr(collection, "async_create_item"):
                return None

            return collection
        except Exception:
            _LOGGER.debug("Could not access timer StorageCollection", exc_info=True)
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

    async def async_remove_timer(self, timer_entity_id: str) -> None:
        """Remove a managed timer entity."""
        item_id = timer_entity_id.removeprefix("timer.")

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
