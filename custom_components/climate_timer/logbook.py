"""Logbook support for Climate Timer integration.

Describes how Climate Timer events appear in the Home Assistant logbook.
"""

from __future__ import annotations

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_TIMER_CANCELLED,
    EVENT_TIMER_FINISHED,
    EVENT_TIMER_STARTED,
)

LOGBOOK_EVENTS = {
    EVENT_TIMER_STARTED,
    EVENT_TIMER_FINISHED,
    EVENT_TIMER_CANCELLED,
}


@callback
def async_describe_events(hass: HomeAssistant, async_describe_event) -> None:  # noqa: ANN001
    """Describe Climate Timer logbook events."""

    @callback
    def async_describe_climate_timer_event(event: Event) -> dict[str, str]:
        """Describe a Climate Timer event for the logbook."""
        entity_id = event.data.get("entity_id", "unknown")
        friendly_name = _get_friendly_name(hass, entity_id)

        if event.event_type == EVENT_TIMER_STARTED:
            duration = event.data.get("duration", "unknown")
            return {
                LOGBOOK_ENTRY_NAME: "Climate Timer",
                LOGBOOK_ENTRY_MESSAGE: (
                    f"started timer for {friendly_name} with duration {duration}"
                ),
            }

        if event.event_type == EVENT_TIMER_FINISHED:
            return {
                LOGBOOK_ENTRY_NAME: "Climate Timer",
                LOGBOOK_ENTRY_MESSAGE: (
                    f"timer finished — turned off {friendly_name}"
                ),
            }

        if event.event_type == EVENT_TIMER_CANCELLED:
            return {
                LOGBOOK_ENTRY_NAME: "Climate Timer",
                LOGBOOK_ENTRY_MESSAGE: (
                    f"timer cancelled — turned off {friendly_name}"
                ),
            }

        return {
            LOGBOOK_ENTRY_NAME: "Climate Timer",
            LOGBOOK_ENTRY_MESSAGE: f"event for {friendly_name}",
        }

    for event_type in LOGBOOK_EVENTS:
        async_describe_event(DOMAIN, event_type, async_describe_climate_timer_event)


def _get_friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Get the friendly name for an entity, falling back to entity_id."""
    state = hass.states.get(entity_id)
    if state and state.attributes.get("friendly_name"):
        return state.attributes["friendly_name"]
    return entity_id
