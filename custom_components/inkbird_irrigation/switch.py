"""Switch platform for Inkbird Irrigation — zone valves and system switches."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InkbirdCoordinator
from .entity import InkbirdEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inkbird zone switches."""
    coordinator: InkbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    profile = coordinator.api.profile

    entities: list[SwitchEntity] = []

    # Zone switches (both models)
    for zone in range(1, profile.num_zones + 1):
        entities.append(InkbirdZoneSwitch(coordinator, zone))

    # System switches depend on the controller DP layout.
    if profile.zone_control_method == "countdown":
        entities.append(InkbirdMainValveSwitch(coordinator))
        entities.append(InkbirdPowerSwitch(coordinator))
        entities.append(InkbirdRainSensorSwitch(coordinator))
        entities.append(InkbirdSkipScheduleSwitch(coordinator))
    else:
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
        if self.coordinator.api.profile.zone_control_method == "countdown":
            # DP 110 is the controller's active-zone bitmask and clears when
            # the valve closes. Countdown DPs can linger after watering stops.
            return bool(device.active_zone & (1 << (self._zone - 1)))
        # DP45 controllers use the DP 107 bitmask.
        return device.zone_active.get(self._zone, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Open the zone valve with the configured duration."""
        from .number import _zone_durations

        entry_id = self.coordinator.entry.entry_id
        duration = _zone_durations.get(entry_id, {}).get(self._zone, 30)
        _LOGGER.debug("Zone %d turn_on with duration=%d", self._zone, duration)
        success = await self.hass.async_add_executor_job(
            self.coordinator.api.turn_on_zone, self._zone, duration
        )
        if not success:
            raise HomeAssistantError(f"Failed to start Zone {self._zone}")
        # Optimistic update after the controller accepts the command.
        device = self.coordinator.api.device
        device.zone_active[self._zone] = True
        device.zone_countdown[self._zone] = duration
        device.active_zone |= 1 << (self._zone - 1)
        self.coordinator.async_set_updated_data(device)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close the zone valve."""
        success = await self.hass.async_add_executor_job(
            self.coordinator.api.turn_off_zone, self._zone
        )
        if not success:
            raise HomeAssistantError(f"Failed to stop Zone {self._zone}")
        # Optimistic update after the controller accepts the command.
        device = self.coordinator.api.device
        device.zone_active[self._zone] = False
        device.zone_countdown[self._zone] = 0
        device.active_zone &= ~(1 << (self._zone - 1))
        self.coordinator.async_set_updated_data(device)
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
        await self.async_set_dp(40, "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_dp(40, "off")


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
        await self.async_set_dp(102, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_dp(102, False)


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
        await self.async_set_dp(107, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_dp(107, False)


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
        await self.async_set_dp(43, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_dp(43, False)


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
            await self.async_set_dp(dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_rain_sensor
        if dp:
            await self.async_set_dp(dp, False)


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
            await self.async_set_dp(dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_timeerror_alarm
        if dp:
            await self.async_set_dp(dp, False)


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
            await self.async_set_dp(dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        dp = self.coordinator.api.profile.dp_cancel_alarm_voice
        if dp:
            await self.async_set_dp(dp, False)
