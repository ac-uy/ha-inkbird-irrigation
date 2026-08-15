"""Sensor platform for Inkbird Irrigation — zone countdowns and system status."""

from __future__ import annotations

import time as time_mod

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InkbirdCoordinator
from .entity import InkbirdEntity
from .models import DeviceModel


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inkbird sensors."""
    coordinator: InkbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    profile = coordinator.api.profile
    model = coordinator.api.model

    entities: list[SensorEntity] = []

    # Zone countdown sensors (IIC-600 only — 800 doesn't have per-zone countdown DPs)
    if model == DeviceModel.IIC_600:
        for zone in range(1, profile.num_zones + 1):
            entities.append(InkbirdZoneCountdownSensor(coordinator, zone))

    # Zone elapsed time sensors (both models)
    for zone in range(1, profile.num_zones + 1):
        entities.append(InkbirdZoneElapsedSensor(coordinator, zone))

    # System sensors
    entities.append(InkbirdModeSensor(coordinator))
    entities.append(InkbirdConnectionModeSensor(coordinator))

    # IIC-800 specific sensors
    if model == DeviceModel.IIC_800:
        entities.append(InkbirdIrrigationModeSensor(coordinator))
        entities.append(InkbirdActiveZoneBitmaskSensor(coordinator))
        entities.append(InkbirdQueuedZoneBitmaskSensor(coordinator))
        entities.append(InkbirdMergeHistorySensor(coordinator))

    async_add_entities(entities)


class InkbirdZoneCountdownSensor(InkbirdEntity, SensorEntity):
    """Sensor showing remaining time for a zone (IIC-600)."""

    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-outline"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: InkbirdCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_zone_{zone}_countdown"
        self._attr_name = f"Zone {zone} time remaining"

    @property
    def native_value(self) -> int:
        """Return the countdown in minutes."""
        return self.coordinator.api.device.zone_countdown.get(self._zone, 0)


class InkbirdZoneElapsedSensor(InkbirdEntity, SensorEntity):
    """Sensor showing elapsed time for a zone.

    Uses HA-side start timestamp for sub-minute resolution while running.
    """

    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-check-outline"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: InkbirdCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_zone_{zone}_elapsed"
        self._attr_name = f"Zone {zone} time elapsed"
        self._zone_start_time: float | None = None

    @property
    def native_value(self) -> float:
        """Return elapsed time in minutes."""
        device = self.coordinator.api.device
        countdown = device.zone_countdown.get(self._zone, 0)
        switch_active = device.zone_active.get(self._zone, False)
        is_running = switch_active or countdown > 0

        if is_running:
            if self._zone_start_time is None:
                self._zone_start_time = time_mod.monotonic()
            elapsed_sec = time_mod.monotonic() - self._zone_start_time
            return round(elapsed_sec / 60, 1)
        else:
            self._zone_start_time = None
            return device.zone_duration.get(self._zone, 0)


class InkbirdModeSensor(InkbirdEntity, SensorEntity):
    """Sensor showing the current operating mode."""

    _attr_icon = "mdi:water-pump"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_mode"
        self._attr_name = "Mode"

    @property
    def native_value(self) -> str:
        """Return the current mode."""
        return self.coordinator.api.device.mode


class InkbirdConnectionModeSensor(InkbirdEntity, SensorEntity):
    """Sensor showing whether the integration is using local or cloud connection."""

    _attr_icon = "mdi:connection"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_connection_mode"
        self._attr_name = "Connection mode"

    @property
    def native_value(self) -> str:
        """Return the transport currently serving integration state."""
        return self.coordinator.api.active_transport

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the requested policy separately from the active transport."""
        return {
            "selected_preference": self.coordinator.api.connection_preference,
            "active_transport": self.coordinator.api.active_transport,
            "fail_count": self.coordinator.api.fail_count,
            "cloud_available": self.coordinator.api.has_cloud,
            "device_model": self.coordinator.api.model.value,
        }


# ─── IIC-800 Specific Sensors ─────────────────────────────────────────────────


class InkbirdIrrigationModeSensor(InkbirdEntity, SensorEntity):
    """Sensor showing irrigation mode (order/together) on IIC-800."""

    _attr_icon = "mdi:format-list-numbered"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_irrigation_mode"
        self._attr_name = "Irrigation mode"

    @property
    def native_value(self) -> str:
        return self.coordinator.api.device.irrigation_mode


class InkbirdActiveZoneBitmaskSensor(InkbirdEntity, SensorEntity):
    """Sensor showing active zone bitmask (IIC-800 DP 107)."""

    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_active_zones"
        self._attr_name = "Active zones"

    @property
    def native_value(self) -> str:
        """Return comma-separated list of active zone numbers."""
        bitmask = self.coordinator.api.device.active_zone
        zones = [
            str(z) for z in range(1, self.coordinator.api.profile.num_zones + 1)
            if bitmask & (1 << (z - 1))
        ]
        return ", ".join(zones) if zones else "None"

    @property
    def extra_state_attributes(self) -> dict:
        return {"bitmask": self.coordinator.api.device.active_zone}


class InkbirdQueuedZoneBitmaskSensor(InkbirdEntity, SensorEntity):
    """Sensor showing queued zone bitmask (IIC-800 DP 108)."""

    _attr_icon = "mdi:playlist-play"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_queued_zones"
        self._attr_name = "Queued zones"

    @property
    def native_value(self) -> str:
        """Return comma-separated list of queued zone numbers."""
        bitmask = self.coordinator.api.device.queued_zone
        zones = [
            str(z) for z in range(1, self.coordinator.api.profile.num_zones + 1)
            if bitmask & (1 << (z - 1))
        ]
        return ", ".join(zones) if zones else "None"

    @property
    def extra_state_attributes(self) -> dict:
        return {"bitmask": self.coordinator.api.device.queued_zone}



class InkbirdMergeHistorySensor(InkbirdEntity, SensorEntity):
    """Sensor showing last irrigation history entry (IIC-800 DP 104).

    DP 104 (Merge_History) is 4 bytes:
        Bytes 2-3 (big-endian): total irrigation time in minutes
        Byte 1: irrigation channel number
        Byte 0 bits 7-4: auto(0) or manual(1)
        Byte 0 bits 3-0: valve state
    """

    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_merge_history"
        self._attr_name = "Last irrigation time"

    @property
    def native_value(self) -> int:
        """Return total irrigation time in minutes from last history entry."""
        parsed = self.coordinator.api.device.merge_history_parsed
        if parsed:
            return parsed.total_time_minutes
        return 0

    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed history attributes."""
        parsed = self.coordinator.api.device.merge_history_parsed
        if parsed:
            return {
                "channel": parsed.channel,
                "is_manual": parsed.is_manual,
                "valve_state": parsed.valve_state,
                "total_time_minutes": parsed.total_time_minutes,
                "raw_hex": self.coordinator.api.device.merge_history_raw.hex()
                if self.coordinator.api.device.merge_history_raw else "",
            }
        return {}
