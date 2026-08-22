"""Constants for the Climate Timer integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

# Read version from manifest.json
MANIFEST_PATH = Path(__file__).parent / "manifest.json"
with open(MANIFEST_PATH, encoding="utf-8") as _f:
    INTEGRATION_VERSION: Final[str] = json.load(_f).get("version", "0.0.0")

DOMAIN: Final[str] = "climate_timer"

# Timer entity naming convention
TIMER_PREFIX: Final[str] = "climate_timer_"
DEFAULT_DURATION: Final[str] = "00:30:00"

# Frontend serving
URL_BASE: Final[str] = "/climate-timer"
JSMODULES: Final[list[dict[str, str]]] = [
    {
        "name": "Climate Timer Card",
        "filename": "climate-timer-card.js",
        "version": INTEGRATION_VERSION,
    },
]

# Storage
STORAGE_KEY: Final[str] = f"{DOMAIN}.modes"
STORAGE_VERSION: Final[int] = 1

# Logbook events
EVENT_TIMER_STARTED: Final[str] = f"{DOMAIN}_started"
EVENT_TIMER_FINISHED: Final[str] = f"{DOMAIN}_finished"
EVENT_TIMER_CANCELLED: Final[str] = f"{DOMAIN}_cancelled"


def get_timer_entity_id(climate_entity: str) -> str:
    """Get the managed timer entity_id for a climate entity.

    Naming convention: timer.climate_timer_{entity_slug}
    where entity_slug is the climate entity_id with dots replaced by underscores.

    Example: climate.living_room_ac -> timer.climate_timer_climate_living_room_ac
    """
    slug = climate_entity.replace(".", "_")
    return f"timer.{TIMER_PREFIX}{slug}"
