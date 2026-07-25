"""DataUpdateCoordinator for Inkbird Irrigation."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InkbirdAPI, InkbirdDevice

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=15)


class InkbirdCoordinator(DataUpdateCoordinator[InkbirdDevice]):
    """Coordinator for Inkbird irrigation controllers."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: InkbirdAPI,
        entry: ConfigEntry,
    ) -> None:
        self.api = api
        self.entry = entry

        super().__init__(
            hass,
            _LOGGER,
            name=f"Inkbird {api.model.value}",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> InkbirdDevice:
        """Fetch latest state from the device."""
        success = await self.hass.async_add_executor_job(self.api.update)
        if not success:
            raise UpdateFailed(
                f"Failed to fetch state from Inkbird {self.api.model.value}"
            )
        return self.api.device
