"""Climate Timer integration for Home Assistant.

Automatically manages timer helpers for climate entities, handles HVAC mode
persistence, and turns off climate entities when timers finish.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_DURATION,
    DOMAIN,
    EVENT_TIMER_CANCELLED,
    EVENT_TIMER_FINISHED,
    EVENT_TIMER_STARTED,
    STORAGE_KEY,
    STORAGE_VERSION,
    get_timer_entity_id,
)
from .frontend import JSModuleRegistration
from .timer_manager import TimerManager

_LOGGER = logging.getLogger(__name__)

type ClimateTimerConfigEntry = ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Climate Timer integration."""
    hass.data.setdefault(DOMAIN, {
        "entries": {},
        "mode_store": None,
        "stored_modes": {},
        "listeners": {},
        "event_unsub": None,
    })

    # Register frontend
    async def _setup_frontend(_event: Event | None = None) -> None:
        module_register = JSModuleRegistration(hass)
        await module_register.async_register()

    if hass.state == CoreState.running:
        await _setup_frontend()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_frontend)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ClimateTimerConfigEntry) -> bool:
    """Set up Climate Timer from a config entry."""
    climate_entity = entry.data["climate_entity"]
    manager = TimerManager(hass)

    # Create managed timer if it doesn't exist
    timer_entity_id = await manager.async_ensure_timer(climate_entity)

    # Initialize mode storage (shared across entries, done once)
    if hass.data[DOMAIN]["mode_store"] is None:
        store: Store[dict[str, str]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        hass.data[DOMAIN]["mode_store"] = store
        hass.data[DOMAIN]["stored_modes"] = await store.async_load() or {}

    # Store entry data
    hass.data[DOMAIN]["entries"][entry.entry_id] = {
        "climate_entity": climate_entity,
        "timer_entity": timer_entity_id,
        "manager": manager,
    }

    # Register services (idempotent — only registers once)
    _async_register_services(hass)

    # Register event listener for timer.finished (idempotent)
    _async_register_event_listener(hass)

    # Track climate state changes for HVAC mode persistence
    _async_track_climate_state(hass, entry.entry_id, climate_entity)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClimateTimerConfigEntry) -> bool:
    """Unload a config entry — remove managed timer."""
    entry_data = hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    if entry_data:
        try:
            await entry_data["manager"].async_remove_timer(entry_data["timer_entity"])
        except Exception:
            _LOGGER.warning(
                "Failed to remove managed timer %s", entry_data["timer_entity"]
            )

    # Remove state listener
    unsub = hass.data[DOMAIN]["listeners"].pop(entry.entry_id, None)
    if unsub:
        unsub()

    # If no entries remain, clean up event listener
    if not hass.data[DOMAIN]["entries"]:
        event_unsub = hass.data[DOMAIN].get("event_unsub")
        if event_unsub:
            event_unsub()
            hass.data[DOMAIN]["event_unsub"] = None

    return True


# --- Service Registration ---


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register climate_timer services (idempotent)."""
    if hass.services.has_service(DOMAIN, "start"):
        return

    async def _async_handle_start(call: ServiceCall) -> None:
        """Handle climate_timer.start service call."""
        climate_entity_id = call.data["entity_id"]
        duration = call.data["duration"]

        entry_data = _find_entry_by_climate(hass, climate_entity_id)
        if not entry_data:
            raise ServiceValidationError(
                f"No Climate Timer config entry for {climate_entity_id}. "
                "Please add it via Settings > Devices & Services > Climate Timer."
            )

        timer_entity_id = entry_data["timer_entity"]
        climate_state = hass.states.get(climate_entity_id)

        # Determine if climate is currently off
        entity_is_off = (
            climate_state is None
            or climate_state.state in ("off", "unavailable")
        )

        if entity_is_off:
            mode = _resolve_hvac_mode(hass, climate_entity_id)
            try:
                if mode:
                    await hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"hvac_mode": mode},
                        target={"entity_id": climate_entity_id},
                        blocking=True,
                    )
                else:
                    await hass.services.async_call(
                        "climate",
                        "turn_on",
                        {},
                        target={"entity_id": climate_entity_id},
                        blocking=True,
                    )
            except Exception as err:
                raise ServiceValidationError(
                    f"Failed to turn on {climate_entity_id}: {err}"
                ) from err

        # Start the managed timer
        try:
            await hass.services.async_call(
                "timer",
                "start",
                {"duration": duration},
                target={"entity_id": timer_entity_id},
                blocking=True,
            )
        except Exception as err:
            # Rollback: turn off climate if we turned it on
            if entity_is_off:
                try:
                    await hass.services.async_call(
                        "climate",
                        "turn_off",
                        {},
                        target={"entity_id": climate_entity_id},
                        blocking=True,
                    )
                except Exception:
                    _LOGGER.warning("Rollback: failed to turn off %s", climate_entity_id)
            raise ServiceValidationError(
                f"Failed to start timer {timer_entity_id}: {err}"
            ) from err

        # Fire logbook event for timer started
        hass.bus.async_fire(
            EVENT_TIMER_STARTED,
            {
                "entity_id": climate_entity_id,
                "duration": duration,
            },
        )

    async def _async_handle_cancel(call: ServiceCall) -> None:
        """Handle climate_timer.cancel service call."""
        climate_entity_id = call.data["entity_id"]

        entry_data = _find_entry_by_climate(hass, climate_entity_id)
        if not entry_data:
            raise ServiceValidationError(
                f"No Climate Timer config entry for {climate_entity_id}."
            )

        timer_entity_id = entry_data["timer_entity"]

        # Cancel the timer
        try:
            await hass.services.async_call(
                "timer",
                "cancel",
                {},
                target={"entity_id": timer_entity_id},
                blocking=True,
            )
        except Exception:
            _LOGGER.warning("Failed to cancel timer %s", timer_entity_id)

        # Turn off climate
        try:
            await hass.services.async_call(
                "climate",
                "turn_off",
                {},
                target={"entity_id": climate_entity_id},
                blocking=True,
            )
        except Exception:
            _LOGGER.warning("Failed to turn off %s", climate_entity_id)

        # Fire logbook event for timer cancelled
        hass.bus.async_fire(
            EVENT_TIMER_CANCELLED,
            {
                "entity_id": climate_entity_id,
            },
        )

    hass.services.async_register(
        DOMAIN,
        "start",
        _async_handle_start,
        schema=cv.make_entity_service_schema(
            {
                "entity_id": cv.entity_id,
                "duration": cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "cancel",
        _async_handle_cancel,
        schema=cv.make_entity_service_schema(
            {
                "entity_id": cv.entity_id,
            }
        ),
    )


# --- Event Listener ---


@callback
def _async_register_event_listener(hass: HomeAssistant) -> None:
    """Register listener for timer.finished events (idempotent)."""
    if hass.data[DOMAIN].get("event_unsub"):
        return

    async def _handle_timer_finished(event: Event) -> None:
        """Handle timer.finished event for managed timers."""
        timer_entity_id = event.data.get("entity_id")
        if not timer_entity_id:
            return

        # Find the climate entity paired with this timer
        for entry_data in hass.data[DOMAIN]["entries"].values():
            if entry_data["timer_entity"] == timer_entity_id:
                climate_entity_id = entry_data["climate_entity"]
                try:
                    await hass.services.async_call(
                        "climate",
                        "turn_off",
                        {},
                        target={"entity_id": climate_entity_id},
                        blocking=True,
                    )
                except Exception:
                    _LOGGER.warning(
                        "Failed to turn off %s after timer finished",
                        climate_entity_id,
                    )

                # Fire logbook event for timer finished
                hass.bus.async_fire(
                    EVENT_TIMER_FINISHED,
                    {
                        "entity_id": climate_entity_id,
                    },
                )
                break

    unsub = hass.bus.async_listen("timer.finished", _handle_timer_finished)
    hass.data[DOMAIN]["event_unsub"] = unsub


# --- HVAC Mode Tracking ---


@callback
def _async_track_climate_state(
    hass: HomeAssistant, entry_id: str, climate_entity_id: str
) -> None:
    """Track climate entity state changes to persist HVAC mode."""

    @callback
    def _state_changed(event: Event) -> None:
        """Handle climate entity state change."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        state_value = new_state.state
        if state_value and state_value not in ("off", "unavailable", "unknown"):
            # Persist the active HVAC mode
            hass.data[DOMAIN]["stored_modes"][climate_entity_id] = state_value
            # Schedule async save
            hass.async_create_task(_async_save_modes(hass))

    unsub = async_track_state_change_event(hass, [climate_entity_id], _state_changed)
    hass.data[DOMAIN]["listeners"][entry_id] = unsub


async def _async_save_modes(hass: HomeAssistant) -> None:
    """Save stored HVAC modes to disk."""
    store: Store | None = hass.data[DOMAIN].get("mode_store")
    if store:
        await store.async_save(hass.data[DOMAIN]["stored_modes"])


# --- HVAC Mode Resolution ---


def _resolve_hvac_mode(hass: HomeAssistant, climate_entity_id: str) -> str | None:
    """Resolve the HVAC mode to use when starting a climate entity.

    Priority order:
    1. Climate entity attributes.last_mode
    2. Climate entity attributes.hvac_mode
    3. Integration's internally stored last-active mode
    4. None (caller should use climate.turn_on without mode)
    """
    state = hass.states.get(climate_entity_id)
    if state:
        # Priority 1: entity attributes.last_mode
        last_mode = state.attributes.get("last_mode")
        if last_mode and last_mode not in ("off", "unavailable"):
            return last_mode

        # Priority 2: entity attributes.hvac_mode
        hvac_mode = state.attributes.get("hvac_mode")
        if hvac_mode and hvac_mode not in ("off", "unavailable"):
            return hvac_mode

    # Priority 3: integration's stored mode
    stored = hass.data[DOMAIN].get("stored_modes", {}).get(climate_entity_id)
    if stored:
        return stored

    # Priority 4: no mode found
    return None


# --- Helpers ---


def _find_entry_by_climate(
    hass: HomeAssistant, climate_entity_id: str
) -> dict[str, Any] | None:
    """Find entry data by climate entity_id."""
    for entry_data in hass.data[DOMAIN]["entries"].values():
        if entry_data["climate_entity"] == climate_entity_id:
            return entry_data
    return None
