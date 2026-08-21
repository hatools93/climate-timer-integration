"""Frontend module registration for Climate Timer integration.

Serves the Climate Timer Card JavaScript file and auto-registers it
as a Lovelace resource (storage mode only).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import JSMODULES, URL_BASE

_LOGGER = logging.getLogger(__name__)


class JSModuleRegistration:
    """Registers JavaScript modules in Home Assistant."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the registrar."""
        self.hass = hass
        self.lovelace = self.hass.data.get("lovelace")

    async def async_register(self) -> None:
        """Register frontend resources."""
        await self._async_register_path()

        # Only register modules if Lovelace is in storage mode
        if self.lovelace and getattr(
            self.lovelace,
            "mode",
            getattr(self.lovelace, "resource_mode", "yaml"),
        ) == "storage":
            await self._async_wait_for_lovelace_resources()

    async def _async_register_path(self) -> None:
        """Register the static HTTP path to serve frontend files."""
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, str(Path(__file__).parent), False)]
            )
            _LOGGER.debug(
                "Static path registered: %s -> %s", URL_BASE, Path(__file__).parent
            )
        except RuntimeError:
            _LOGGER.debug("Static path already registered: %s", URL_BASE)

    async def _async_wait_for_lovelace_resources(self) -> None:
        """Wait for Lovelace resources to be loaded before registering modules."""

        async def _check_loaded(_now: Any) -> None:
            if self.lovelace.resources.loaded:
                await self._async_register_modules()
            else:
                _LOGGER.debug("Lovelace resources not loaded, retrying in 5s")
                async_call_later(self.hass, 5, _check_loaded)

        await _check_loaded(None)

    async def _async_register_modules(self) -> None:
        """Register or update JavaScript modules as Lovelace resources."""
        _LOGGER.debug("Registering Climate Timer frontend modules")

        # Get existing resources from this integration
        existing_resources = [
            r
            for r in self.lovelace.resources.async_items()
            if r["url"].startswith(URL_BASE)
        ]

        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}"
            registered = False

            for resource in existing_resources:
                if self._get_path(resource["url"]) == url:
                    registered = True
                    # Check if version update needed
                    if self._get_version(resource["url"]) != module["version"]:
                        _LOGGER.info(
                            "Updating %s to version %s",
                            module["name"],
                            module["version"],
                        )
                        await self.lovelace.resources.async_update_item(
                            resource["id"],
                            {
                                "res_type": "module",
                                "url": f"{url}?v={module['version']}",
                            },
                        )
                    break

            if not registered:
                _LOGGER.info(
                    "Registering %s version %s", module["name"], module["version"]
                )
                await self.lovelace.resources.async_create_item(
                    {
                        "res_type": "module",
                        "url": f"{url}?v={module['version']}",
                    }
                )

    def _get_path(self, url: str) -> str:
        """Extract path without query parameters."""
        return url.split("?")[0]

    def _get_version(self, url: str) -> str:
        """Extract version from URL query parameter."""
        parts = url.split("?")
        if len(parts) > 1 and parts[1].startswith("v="):
            return parts[1].replace("v=", "")
        return "0"

    async def async_unregister(self) -> None:
        """Remove Lovelace resources registered by this integration."""
        if not self.lovelace or getattr(self.lovelace, "mode", "yaml") != "storage":
            return

        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}"
            resources = [
                r
                for r in self.lovelace.resources.async_items()
                if r["url"].startswith(url)
            ]
            for resource in resources:
                try:
                    await self.lovelace.resources.async_delete_item(resource["id"])
                except Exception:
                    _LOGGER.warning("Failed to unregister resource: %s", resource["url"])
