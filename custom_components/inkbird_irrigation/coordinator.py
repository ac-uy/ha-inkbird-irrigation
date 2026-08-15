"""DataUpdateCoordinator for Inkbird Irrigation."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InkbirdAPI, InkbirdDevice

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_SECONDS = 30


class InkbirdCoordinator(DataUpdateCoordinator[InkbirdDevice]):
    """Coordinate controller state pushed over its persistent Tuya socket."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: InkbirdAPI,
        entry: ConfigEntry,
    ) -> None:
        self.api = api
        self.entry = entry
        self._listener_task: asyncio.Task[None] | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"Inkbird {api.model.value}",
            update_interval=None,
        )

    async def _async_update_data(self) -> InkbirdDevice:
        """Return the state obtained during initial connection or from pushes."""
        success = await self.hass.async_add_executor_job(self.api.update)
        if not success:
            raise UpdateFailed(
                f"Failed to fetch state from Inkbird {self.api.model.value}"
            )
        return self.api.device

    async def async_start_listener(self) -> None:
        """Start consuming controller-pushed DP updates."""
        if self._listener_task is None:
            self._listener_task = self.hass.async_create_task(
                self._async_listen(), name=f"inkbird_listener_{self.entry.entry_id}"
            )

    async def async_stop_listener(self) -> None:
        """Stop the listener and close its persistent controller socket."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None
        await self.hass.async_add_executor_job(self.api.close)

    async def _async_listen(self) -> None:
        """Publish every received local DP update and reconnect after failures."""
        while True:
            changed = await self.hass.async_add_executor_job(
                self.api.receive_push_update
            )
            if changed:
                self.async_set_updated_data(self.api.device)
                continue
            if self.api.device.online:
                continue

            recovered = await self.hass.async_add_executor_job(self.api.connect)
            if recovered:
                self.async_set_updated_data(self.api.device)
                continue

            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
