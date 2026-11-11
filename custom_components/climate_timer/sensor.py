"""Climate Timer sensor platform.

Provides a custom timer entity for each managed climate entity. This replaces
the dependency on HA's built-in timer helper, giving us full control over
entity creation, state, and lifecycle.

Each sensor entity exposes:
  - state: "idle" | "active" | "paused"
  - attributes: duration, remaining, finishes_at, friendly_name, restore

The timer state is restored across Home Assistant restarts and config entry
reloads (RestoreEntity): an active timer reschedules its finish, and a timer
that expired while Home Assistant was down turns the climate entity off as
soon as the system is running again.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DEFAULT_DURATION, DOMAIN, get_timer_entity_id

_LOGGER = logging.getLogger(__name__)

# Timer states (mirrors HA timer states for frontend compatibility)
STATE_IDLE = "idle"
STATE_ACTIVE = "active"
STATE_PAUSED = "paused"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Climate Timer sensor entities from a config entry."""
    climate_entity = entry.data["climate_entity"]

    entity = ClimateTimerSensor(
        climate_entity=climate_entity,
        entry_id=entry.entry_id,
    )

    async_add_entities([entity])

    # Store reference to the sensor entity in hass.data for service handlers
    hass.data[DOMAIN]["entries"][entry.entry_id]["timer_sensor"] = entity
    _LOGGER.info(
        "Climate Timer sensor created: %s for %s",
        entity.entity_id,
        climate_entity,
    )


class ClimateTimerSensor(RestoreEntity, SensorEntity):
    """A timer sensor entity managed by the Climate Timer integration.

    Mimics the behavior of HA's built-in timer helper but is fully owned
    by this integration, avoiding StorageCollection dependency issues.
    """

    _attr_should_poll = False
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self,
        climate_entity: str,
        entry_id: str,
    ) -> None:
        """Initialize the climate timer sensor."""
        self._climate_entity = climate_entity
        self._entry_id = entry_id

        # Suggest the deterministic entity id from the naming convention.
        # The entity registry may still rename it; the frontend card finds
        # this sensor via its climate_entity attribute instead.
        self.entity_id = get_timer_entity_id(climate_entity)
        self._attr_unique_id = self.entity_id.removeprefix("sensor.")

        # Timer state
        self._timer_state: str = STATE_IDLE
        self._duration: str = DEFAULT_DURATION
        self._remaining: str = "00:00:00"
        self._finishes_at: str = ""
        self._end_time: datetime | None = None
        self._pause_remaining: timedelta | None = None

        # Listener for timer expiry
        self._unsub_timer: callback | None = None

        # Friendly name
        friendly_climate = climate_entity.removeprefix("climate.").replace("_", " ").title()
        self._attr_name = f"Climate Timer - {friendly_climate}"

    async def async_added_to_hass(self) -> None:
        """Restore the timer state when the entity is added to hass."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None:
            return

        duration = last_state.attributes.get("duration") or DEFAULT_DURATION

        if last_state.state == STATE_ACTIVE:
            finishes_at = last_state.attributes.get("finishes_at")
            end_time = dt_util.parse_datetime(finishes_at) if finishes_at else None

            if end_time is not None and end_time > dt_util.utcnow():
                # The timer was still running — restore and reschedule it.
                self._duration = duration
                self._timer_state = STATE_ACTIVE
                self._end_time = end_time
                self._finishes_at = end_time.isoformat()
                self._remaining = _format_timedelta(end_time - dt_util.utcnow())
                self._pause_remaining = None
                self._unsub_timer = async_track_point_in_utc_time(
                    self.hass, self._async_timer_finished, end_time
                )
                self.async_write_ha_state()
                _LOGGER.debug(
                    "Restored active timer: %s, finishes_at=%s",
                    self.entity_id,
                    self._finishes_at,
                )
                return

            # The timer expired while Home Assistant was down or while the
            # entry was reloading — reset to idle and turn the climate off.
            self._duration = duration
            self._timer_state = STATE_IDLE
            self._remaining = "00:00:00"
            self._finishes_at = ""
            self._end_time = None
            self._pause_remaining = None
            self.async_write_ha_state()
            self._async_fire_timer_finished_when_running()
            return

        if last_state.state == STATE_PAUSED and last_state.attributes.get("remaining"):
            # Defensive: nothing sets paused today, but restore it properly.
            self._duration = duration
            self._timer_state = STATE_PAUSED
            self._remaining = last_state.attributes["remaining"]
            self._pause_remaining = _parse_duration(self._remaining)
            self.async_write_ha_state()
            return

        # Idle (or unknown) — keep the last-used duration pre-filled.
        self._duration = duration
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the current timer state."""
        return self._timer_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return timer attributes compatible with the frontend card."""
        remaining = self._remaining
        if self._timer_state == STATE_ACTIVE and self._end_time:
            # Compute remaining dynamically
            now = dt_util.utcnow()
            diff = self._end_time - now
            if diff.total_seconds() > 0:
                remaining = _format_timedelta(diff)
            else:
                remaining = "00:00:00"

        return {
            "duration": self._duration,
            "remaining": remaining,
            "finishes_at": self._finishes_at,
            "friendly_name": self._attr_name,
            "restore": True,
            "climate_entity": self._climate_entity,
        }

    # --- Timer Control Methods ---

    @callback
    def async_start(self, duration: str) -> None:
        """Start the timer with the given duration (HH:MM:SS format)."""
        self._cancel_scheduled_finish()

        self._duration = duration
        self._timer_state = STATE_ACTIVE
        self._pause_remaining = None

        # Parse duration to calculate end time
        delta = _parse_duration(duration)
        now = dt_util.utcnow()
        self._end_time = now + delta
        self._finishes_at = self._end_time.isoformat()
        self._remaining = duration

        # Schedule the finish callback
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._async_timer_finished, self._end_time
        )

        self.async_write_ha_state()
        _LOGGER.debug(
            "Timer started: %s, duration=%s, finishes_at=%s",
            self.entity_id,
            duration,
            self._finishes_at,
        )

    @callback
    def async_cancel(self) -> None:
        """Cancel the timer and reset to idle."""
        self._cancel_scheduled_finish()
        self._timer_state = STATE_IDLE
        self._remaining = "00:00:00"
        self._finishes_at = ""
        self._end_time = None
        self._pause_remaining = None
        self.async_write_ha_state()
        _LOGGER.debug("Timer cancelled: %s", self.entity_id)

    @callback
    def async_pause(self) -> None:
        """Pause the timer."""
        if self._timer_state != STATE_ACTIVE:
            return

        self._cancel_scheduled_finish()

        # Store remaining time
        if self._end_time:
            now = dt_util.utcnow()
            self._pause_remaining = self._end_time - now
            if self._pause_remaining.total_seconds() < 0:
                self._pause_remaining = timedelta(0)
            self._remaining = _format_timedelta(self._pause_remaining)
        
        self._timer_state = STATE_PAUSED
        self._finishes_at = ""
        self._end_time = None
        self.async_write_ha_state()
        _LOGGER.debug("Timer paused: %s, remaining=%s", self.entity_id, self._remaining)

    @callback
    def async_resume(self) -> None:
        """Resume a paused timer."""
        if self._timer_state != STATE_PAUSED or self._pause_remaining is None:
            return

        now = dt_util.utcnow()
        self._end_time = now + self._pause_remaining
        self._finishes_at = self._end_time.isoformat()
        self._timer_state = STATE_ACTIVE
        self._pause_remaining = None

        # Schedule the finish callback
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._async_timer_finished, self._end_time
        )

        self.async_write_ha_state()
        _LOGGER.debug("Timer resumed: %s, finishes_at=%s", self.entity_id, self._finishes_at)

    @callback
    def _async_timer_finished(self, _now: datetime) -> None:
        """Handle timer expiry."""
        self._timer_state = STATE_IDLE
        self._remaining = "00:00:00"
        self._finishes_at = ""
        self._end_time = None
        self._pause_remaining = None
        self._unsub_timer = None
        self.async_write_ha_state()

        # Fire the timer finished event so __init__.py can turn off climate
        self._async_fire_timer_finished_when_running()

    @callback
    def _async_fire_timer_finished(self) -> None:
        """Fire the internal timer finished event."""
        self.hass.bus.async_fire(
            f"{DOMAIN}_timer_finished",
            {
                "entity_id": self._climate_entity,
                "timer_entity_id": self.entity_id,
            },
        )
        _LOGGER.debug("Timer finished: %s", self.entity_id)

    @callback
    def _async_fire_timer_finished_when_running(self) -> None:
        """Fire the timer finished event, deferring until Home Assistant runs.

        During startup the climate integration may not be loaded yet and the
        integration's event listener is only armed while it sets up, so defer
        the turn-off until the homeassistant_started event.
        """
        if self.hass.is_running:
            self._async_fire_timer_finished()
            return

        if self.hass.is_stopping:
            # Shutting down — a turn-off can no longer be served.
            return

        @callback
        def _fire_when_started(_event: Event) -> None:
            """Fire the deferred finish event."""
            self._async_fire_timer_finished()

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _fire_when_started)

    def _cancel_scheduled_finish(self) -> None:
        """Cancel any scheduled timer finish callback."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        self._cancel_scheduled_finish()


# --- Helpers ---


def _parse_duration(duration_str: str) -> timedelta:
    """Parse HH:MM:SS duration string to timedelta."""
    parts = duration_str.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    elif len(parts) == 2:
        minutes, seconds = int(parts[0]), int(parts[1])
        return timedelta(minutes=minutes, seconds=seconds)
    # Fallback: try as total seconds
    return timedelta(seconds=int(duration_str))


def _format_timedelta(td: timedelta) -> str:
    """Format timedelta as HH:MM:SS string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
