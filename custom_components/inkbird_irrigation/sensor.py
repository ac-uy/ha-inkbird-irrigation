"""Sensor platform for Inkbird Irrigation — zone countdowns and system status."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUM_ZONES
from .coordinator import InkbirdCoordinator
from .entity import InkbirdEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inkbird sensors."""
    coordinator: InkbirdCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    # Zone countdown sensors
    for zone in range(1, NUM_ZONES + 1):
        entities.append(InkbirdZoneCountdownSensor(coordinator, zone))

    # Zone elapsed time sensors
    for zone in range(1, NUM_ZONES + 1):
        entities.append(InkbirdZoneElapsedSensor(coordinator, zone))

    # System sensors
    entities.append(InkbirdModeSensor(coordinator))
    entities.append(InkbirdConnectionModeSensor(coordinator))

    async_add_entities(entities)


class InkbirdZoneCountdownSensor(InkbirdEntity, SensorEntity):
    """Sensor showing remaining time for a zone."""

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

    The device reports elapsed time via the use_time_N DPs (25-30), which only
    tick once per minute on the firmware side.  To give sub-minute resolution
    the sensor also tracks a HA-side start timestamp and computes elapsed time
    locally while a zone is running, falling back to the device value when the
    zone is stopped.
    """

    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-check-outline"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: InkbirdCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_zone_{zone}_elapsed"
        self._attr_name = f"Zone {zone} time elapsed"
        self._zone_start_time: float | None = None  # monotonic clock at zone start

    @property
    def native_value(self) -> float:
        """Return elapsed time in minutes.

        While the zone is active, compute elapsed time from the HA-side start
        timestamp so the value updates every coordinator cycle (~15 s) instead
        of every device firmware minute.  When the zone is off, return the
        device-reported use_time value (DPs 25-30, stored in zone_duration).
        """
        import time

        countdown = self.coordinator.api.device.zone_countdown.get(self._zone, 0)
        switch_active = self.coordinator.api.device.zone_active.get(self._zone, False)
        is_running = switch_active or countdown > 0

        if is_running:
            if self._zone_start_time is None:
                # Zone just started — record the start time
                self._zone_start_time = time.monotonic()
            elapsed_sec = time.monotonic() - self._zone_start_time
            return round(elapsed_sec / 60, 1)
        else:
            # Zone is off — reset the tracker and return the device value
            self._zone_start_time = None
            # zone_duration holds DPs 25-30 (use_time_N = elapsed minutes
            # reported by device firmware, updated in 1-min increments)
            return self.coordinator.api.device.zone_duration.get(self._zone, 0)


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
        """Return the current connection mode."""
        if self.coordinator.api._using_cloud:
            return "cloud"
        return "local"

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        return {
            "fail_count": self.coordinator.api._fail_count,
            "cloud_available": self.coordinator.api._has_cloud,
        }
