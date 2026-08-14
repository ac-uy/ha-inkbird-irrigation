"""Switch platform for Inkbird Irrigation — zone valves and system switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InkbirdCoordinator
from .entity import InkbirdEntity
from .models import DeviceModel

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inkbird zone switches."""
    coordinator: InkbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    profile = coordinator.api.profile
    model = coordinator.api.model

    entities: list[SwitchEntity] = []

    # Zone switches (both models)
    for zone in range(1, profile.num_zones + 1):
        entities.append(InkbirdZoneSwitch(coordinator, zone))

    # System switches — model-dependent
    if model == DeviceModel.IIC_600:
        entities.append(InkbirdMainValveSwitch(coordinator))
        entities.append(InkbirdPowerSwitch(coordinator))
        entities.append(InkbirdRainSensorSwitch(coordinator))
        entities.append(InkbirdSkipScheduleSwitch(coordinator))
    elif model == DeviceModel.IIC_800:
        entities.append(InkbirdRainSensorSwitch800(coordinator))
        entities.append(InkbirdTimerAlarmSwitch(coordinator))
        entities.append(InkbirdCancelAlarmVoiceSwitch(coordinator))

    async_add_entities(entities)


class InkbirdZoneSwitch(InkbirdEntity, SwitchEntity):
    """Switch entity for an irrigation zone valve."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator: InkbirdCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_zone_{zone}"
        self._attr_name = f"Zone {zone}"

    @property
    def is_on(self) -> bool:
        """Return True if the zone valve is open."""
        device = self.coordinator.api.device
        model = self.coordinator.api.model

        if model == DeviceModel.IIC_600:
            # The valve-status DPs are read-only and can remain True after the
            # controller has stopped watering. The countdown DPs are cleared
            # when irrigation ends, so they are the authoritative state source.
            return device.zone_countdown.get(self._zone, 0) > 0
        elif model == DeviceModel.IIC_800:
            # Use bitmask from DP 107
            return device.zone_active.get(self._zone, False)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Open the zone valve with the configured duration."""
        from .number import _zone_durations

        entry_id = self.coordinator.entry.entry_id
        duration = _zone_durations.get(entry_id, {}).get(self._zone, 30)
        _LOGGER.debug("Zone %d turn_on with duration=%d", self._zone, duration)
        await self.hass.async_add_executor_job(
            self.coordinator.api.turn_on_zone, self._zone, duration
        )
        # Optimistic update
        self.coordinator.api.device.zone_active[self._zone] = True
        self.coordinator.api.device.zone_countdown[self._zone] = duration
        self.coordinator.async_set_updated_data(self.coordinator.api.device)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close the zone valve."""
        await self.hass.async_add_executor_job(
            self.coordinator.api.turn_off_zone, self._zone
        )
        # Optimistic update
        self.coordinator.api.device.zone_active[self._zone] = False
        self.coordinator.api.device.zone_countdown[self._zone] = 0
        self.coordinator.async_set_updated_data(self.coordinator.api.device)
        await self.coordinator.async_request_refresh()


# ─── IIC-600 System Switches ──────────────────────────────────────────────────


class InkbirdMainValveSwitch(InkbirdEntity, SwitchEntity):
    """Switch for the main valve control (IIC-600)."""

    _attr_icon = "mdi:valve"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_main_valve"
        self._attr_name = "Main valve"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.device.system_power == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 40, "on")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 40, "off")
        await self.coordinator.async_request_refresh()


class InkbirdPowerSwitch(InkbirdEntity, SwitchEntity):
    """Switch for the power control (IIC-600)."""

    _attr_icon = "mdi:power"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_power"
        self._attr_name = "Power"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.device.power_switch

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 102, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 102, False)
        await self.coordinator.async_request_refresh()


class InkbirdRainSensorSwitch(InkbirdEntity, SwitchEntity):
    """Switch for the rain sensor (IIC-600)."""

    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_rain_sensor"
        self._attr_name = "Rain sensor"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.device.rain_sensor_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 107, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 107, False)
        await self.coordinator.async_request_refresh()


class InkbirdSkipScheduleSwitch(InkbirdEntity, SwitchEntity):
    """Switch to skip/pause scheduled irrigation (IIC-600)."""

    _attr_icon = "mdi:calendar-remove"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_skip_schedule"
        self._attr_name = "Skip schedule"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.device.skip_schedule

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 43, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self.coordinator.api.set_dp, 43, False)
        await self.coordinator.async_request_refresh()


# ─── IIC-800 System Switches ──────────────────────────────────────────────────


class InkbirdRainSensorSwitch800(InkbirdEntity, SwitchEntity):
    """Switch for the rain sensor (IIC-800, DP 102)."""

    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_rain_sensor"
        self._attr_name = "Rain sensor"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.device.rain_sensor_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_rain_sensor
        if dp:
            await self.hass.async_add_executor_job(self.coordinator.api.set_dp, dp, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_rain_sensor
        if dp:
            await self.hass.async_add_executor_job(self.coordinator.api.set_dp, dp, False)
        await self.coordinator.async_request_refresh()


class InkbirdTimerAlarmSwitch(InkbirdEntity, SwitchEntity):
    """Switch for timer error alarm (IIC-800, DP 106)."""

    _attr_icon = "mdi:alarm-light"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_timeerror_alarm"
        self._attr_name = "Timer error alarm"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.device.timeerror_alarm

    async def async_turn_on(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_timeerror_alarm
        if dp:
            await self.hass.async_add_executor_job(self.coordinator.api.set_dp, dp, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_timeerror_alarm
        if dp:
            await self.hass.async_add_executor_job(self.coordinator.api.set_dp, dp, False)
        await self.coordinator.async_request_refresh()


class InkbirdCancelAlarmVoiceSwitch(InkbirdEntity, SwitchEntity):
    """Switch to cancel alarm voice (IIC-800, DP 109)."""

    _attr_icon = "mdi:volume-off"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_cancel_alarm_voice"
        self._attr_name = "Cancel alarm voice"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.device.cancel_alarm_voice

    async def async_turn_on(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_cancel_alarm_voice
        if dp:
            await self.hass.async_add_executor_job(self.coordinator.api.set_dp, dp, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_cancel_alarm_voice
        if dp:
            await self.hass.async_add_executor_job(self.coordinator.api.set_dp, dp, False)
        await self.coordinator.async_request_refresh()
