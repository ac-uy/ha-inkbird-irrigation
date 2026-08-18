"""Transport-aware DataUpdateCoordinator for Inkbird Irrigation."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InkbirdAPI, InkbirdDevice
from .const import (
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_AUTO,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LOCAL,
    CONNECTION_MODES,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_SECONDS = 30
CLOUD_POLL_INTERVAL_SECONDS = 60
CLOUD_FAILURE_MAX_DELAY_SECONDS = 300
AUTO_LOCAL_RETRY_SECONDS = 300


class InkbirdCoordinator(DataUpdateCoordinator[InkbirdDevice]):
    """Coordinate local pushed updates and bounded cloud fallback polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: InkbirdAPI,
        entry: ConfigEntry,
    ) -> None:
        self.api = api
        self.entry = entry
        self._transport_task: asyncio.Task[None] | None = None
        self._transport_lock = asyncio.Lock()

        super().__init__(
            hass,
            _LOGGER,
            name=f"Inkbird {api.model.value}",
            update_interval=None,
        )

    async def _async_update_data(self) -> InkbirdDevice:
        """Return cached local state or refresh cloud state when it is active."""
        success = await self.hass.async_add_executor_job(self.api.update)
        if not success:
            raise UpdateFailed(
                f"Failed to fetch state from Inkbird {self.api.model.value}"
            )
        return self.api.device

    async def async_set_connection_preference(self, preference: str) -> None:
        """Verify a requested transport, then persist and publish the policy."""
        if preference not in CONNECTION_MODES:
            raise ValueError(f"Unsupported connection preference: {preference}")

        async with self._transport_lock:
            if preference == CONNECTION_MODE_LOCAL:
                success = await self.hass.async_add_executor_job(self.api.activate_local)
            elif preference == CONNECTION_MODE_CLOUD:
                success = await self.hass.async_add_executor_job(self.api.activate_cloud)
            else:
                success = await self.hass.async_add_executor_job(self.api.activate_local)
                if not success and self.api.has_cloud:
                    success = await self.hass.async_add_executor_job(
                        self.api.activate_cloud
                    )

            if not success:
                raise UpdateFailed(
                    f"Cannot activate {preference} connection mode for Inkbird "
                    f"{self.api.model.value}"
                )

            self.api.set_connection_preference(preference)
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={**self.entry.options, CONF_CONNECTION_MODE: preference},
            )
            self.async_set_updated_data(self.api.device)

    async def async_start_listener(self) -> None:
        """Start the long-running transport loop outside HA startup tracking."""
        if self._transport_task is None:
            self._transport_task = self.hass.async_create_background_task(
                self._async_run_transport(),
                name=f"inkbird_transport_{self.entry.entry_id}",
            )

    async def async_stop_listener(self) -> None:
        """Stop all polling/listening and close the local socket on unload."""
        if self._transport_task is not None:
            self._transport_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._transport_task
            self._transport_task = None
        await self.hass.async_add_executor_job(self.api.close)

    async def _async_run_transport(self) -> None:
        """Serve the selected policy without polling a local persistent socket."""
        next_local_attempt = 0.0
        local_failure_delay = RECONNECT_DELAY_SECONDS
        cloud_failure_delay = RECONNECT_DELAY_SECONDS

        while True:
            preference = self.api.connection_preference
            transport = self.api.active_transport

            if transport == CONNECTION_MODE_LOCAL:
                changed = await self.hass.async_add_executor_job(
                    self.api.receive_push_update
                )
                if changed:
                    local_failure_delay = RECONNECT_DELAY_SECONDS
                    self.async_set_updated_data(self.api.device)
                    continue
                if self.api.active_transport == CONNECTION_MODE_LOCAL:
                    continue

                # The persistent session failed. Do not reconnect immediately:
                # this controller can reject rapid successive local handshakes.
                next_local_attempt = time.monotonic() + local_failure_delay
                continue

            if transport == CONNECTION_MODE_CLOUD:
                cloud_ok = await self.hass.async_add_executor_job(self.api.poll_cloud)
                if cloud_ok:
                    cloud_failure_delay = RECONNECT_DELAY_SECONDS
                    self.async_set_updated_data(self.api.device)
                else:
                    self.api.device.online = False
                    self.async_set_updated_data(self.api.device)

                if preference == CONNECTION_MODE_AUTO:
                    if not next_local_attempt:
                        next_local_attempt = (
                            time.monotonic() + AUTO_LOCAL_RETRY_SECONDS
                        )
                    if time.monotonic() >= next_local_attempt:
                        next_local_attempt = (
                            time.monotonic() + AUTO_LOCAL_RETRY_SECONDS
                        )
                        recovered = await self.hass.async_add_executor_job(
                            self.api.recover_local
                        )
                        if recovered:
                            local_failure_delay = RECONNECT_DELAY_SECONDS
                            self.async_set_updated_data(self.api.device)
                            continue

                delay = CLOUD_POLL_INTERVAL_SECONDS if cloud_ok else cloud_failure_delay
                cloud_failure_delay = min(
                    cloud_failure_delay * 2, CLOUD_FAILURE_MAX_DELAY_SECONDS
                )
                await asyncio.sleep(delay)
                continue

            # No active transport. Local-only keeps trying local; Auto can use
            # a verified cloud status response as a bounded fallback.
            if preference == CONNECTION_MODE_CLOUD:
                recovered = await self.hass.async_add_executor_job(
                    self.api.activate_cloud
                )
            else:
                wait_seconds = next_local_attempt - time.monotonic()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                    continue

                recovered = await self.hass.async_add_executor_job(
                    self.api.recover_local
                )
                if (
                    not recovered
                    and preference == CONNECTION_MODE_AUTO
                    and self.api.has_cloud
                ):
                    recovered = await self.hass.async_add_executor_job(
                        self.api.activate_cloud
                    )

            if recovered:
                local_failure_delay = RECONNECT_DELAY_SECONDS
                self.async_set_updated_data(self.api.device)
                if self.api.active_transport == CONNECTION_MODE_CLOUD:
                    next_local_attempt = time.monotonic() + AUTO_LOCAL_RETRY_SECONDS
                continue

            next_local_attempt = time.monotonic() + local_failure_delay
            local_failure_delay = min(
                local_failure_delay * 2, CLOUD_FAILURE_MAX_DELAY_SECONDS
            )
