"""Sensor platform for Inkbird Irrigation — zone countdowns and system status."""

from __future__ import annotations

import datetime as dt
import time as time_mod
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import InkbirdCoordinator
from .entity import InkbirdEntity
from .models import CYCLE_INTERVAL, CYCLE_WEEKLY

WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]  # bit 0 = Sunday

SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_REFRESH_SCHEDULES = "refresh_schedules"
SET_SCHEDULE_SCHEMA = {
    vol.Required("duration"): vol.All(vol.Coerce(int), vol.Range(min=0, max=180)),
    vol.Optional("start_times", default=[]): vol.All(
        cv.ensure_list, [cv.time], vol.Length(max=6)
    ),
    vol.Optional("interval_days"): vol.All(vol.Coerce(int), vol.Range(min=1, max=9)),
    vol.Optional("weekdays"): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
    vol.Optional("start_date"): cv.date,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inkbird sensors."""
    coordinator: InkbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    profile = coordinator.api.profile

    entities: list[SensorEntity] = []

    # Zone "time remaining" countdown sensors for both models. The IIC-600 reads
    # its per-zone countdown DPs directly; the IIC-800 derives remaining time from
    # the DP45 payload (configured duration minus minutes elapsed).
    for zone in range(1, profile.num_zones + 1):
        entities.append(InkbirdZoneCountdownSensor(coordinator, zone))

    # Zone elapsed time sensors (both models)
    for zone in range(1, profile.num_zones + 1):
        entities.append(InkbirdZoneElapsedSensor(coordinator, zone))

    # Legacy IIC-600: per-station schedule stored on the controller (DP 104)
    if profile.dp_schedule_menu:
        entities.append(InkbirdClockSensor(coordinator))
        for zone in range(1, profile.num_zones + 1):
            entities.append(InkbirdScheduleSensor(coordinator, zone))
        platform = entity_platform.async_get_current_platform()
        platform.async_register_entity_service(
            SERVICE_SET_SCHEDULE, SET_SCHEDULE_SCHEMA, "async_set_schedule"
        )
        platform.async_register_entity_service(
            SERVICE_REFRESH_SCHEDULES, {}, "async_refresh_schedules"
        )

    # System sensors
    entities.append(InkbirdModeSensor(coordinator))
    entities.append(InkbirdConnectionModeSensor(coordinator))

    # DP45 controller-specific sensors.
    if profile.zone_control_method == "bitmask_raw":
        entities.append(InkbirdIrrigationModeSensor(coordinator))
        entities.append(InkbirdActiveZoneBitmaskSensor(coordinator))
        entities.append(InkbirdQueuedZoneBitmaskSensor(coordinator))
        entities.append(InkbirdMergeHistorySensor(coordinator))

    async_add_entities(entities)


class InkbirdZoneCountdownSensor(InkbirdEntity, SensorEntity):
    """Sensor showing remaining time for a zone.

    IIC-600 reads its per-zone countdown DP directly. IIC-800 derives the
    remaining minutes from the DP45 payload (configured duration minus the
    minutes the zone has been running).
    """

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

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the DP45 split and raw payload on IIC-800 for diagnostics.

        These make it possible to confirm — from the entity's attributes, with
        no debug logging — whether the device's running field counts up
        (elapsed) or down, which determines the remaining-time derivation.
        """
        if self.coordinator.api.profile.zone_control_method != "bitmask_raw":
            return {}
        device = self.coordinator.api.device
        raw = device.irrigation_time_all
        return {
            "running_minutes": device.zone_running_time.get(self._zone, 0),
            "configured_duration_minutes": device.zone_config_duration.get(self._zone, 0),
            "dp45_raw_hex": raw.hex() if isinstance(raw, (bytes, bytearray)) and raw else "",
        }


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

        # IIC-800 reports per-run elapsed minutes directly in the DP45 payload,
        # so use that device value rather than an HA-side timer. (The legacy
        # per-zone "use_time" DP is a lifetime cumulative counter and must not be
        # shown here.)
        if self.coordinator.api.profile.zone_control_method == "bitmask_raw":
            return device.zone_running_time.get(self._zone, 0)

        # IIC-600 has no per-run elapsed DP, so measure it HA-side from when the
        # zone became active.
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
            "local_protocol": f"{self.coordinator.api.local_protocol:.1f}",
            "fail_count": self.coordinator.api.fail_count,
            "recovery_failures": self.coordinator.api.recovery_failures,
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


class InkbirdScheduleSensor(InkbirdEntity, SensorEntity):
    """Schedule stored on a legacy IIC-600 for one station (DP 104).

    The state summarises the schedule; attributes carry the decoded fields.
    Use the ``inkbird_irrigation.set_schedule`` service on this entity to
    write a new schedule to the controller.
    """

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: InkbirdCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_zone_{zone}_schedule"
        self._attr_name = f"Zone {zone} schedule"

    @property
    def _schedule(self) -> Any:
        return self.coordinator.api.device.schedules.get(self._zone)

    @property
    def native_value(self) -> str | None:
        """Return a short summary, e.g. '6 min at 21:00, every 1 day'."""
        s = self._schedule
        if s is None:
            return None
        if not s.enabled:
            return "off"
        times = ", ".join(f"{h:02d}:{m:02d}" for h, m in s.start_times)
        if s.cycle_mode == CYCLE_INTERVAL:
            repeat = f"every {s.days} day" + ("s" if s.days != 1 else "")
        elif s.cycle_mode == CYCLE_WEEKLY:
            repeat = ", ".join(
                d.capitalize() for i, d in enumerate(WEEKDAYS) if s.days & (1 << i)
            )
        else:
            repeat = f"cycle {s.cycle_mode}"
        return f"{s.duration_minutes} min at {times}, {repeat}"[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._schedule
        if s is None:
            return {}
        attrs: dict[str, Any] = {
            "duration": s.duration_minutes,
            "start_times": [f"{h:02d}:{m:02d}" for h, m in s.start_times],
            "cycle_mode": s.cycle_mode,
            "start_date": "%04d-%02d-%02d" % s.start_date,
            "flags": s.flags,
        }
        if s.cycle_mode == CYCLE_INTERVAL:
            attrs["interval_days"] = s.days
        elif s.cycle_mode == CYCLE_WEEKLY:
            attrs["weekdays"] = [d for i, d in enumerate(WEEKDAYS) if s.days & (1 << i)]
        return attrs

    async def async_refresh_schedules(self) -> None:
        """Ask the controller to report all stored schedules."""
        ok = await self.hass.async_add_executor_job(self.coordinator.api.query_schedules)
        if not ok:
            raise HomeAssistantError("Schedule query failed (local connection required)")

    async def async_set_schedule(
        self,
        duration: int,
        start_times: list[dt.time],
        interval_days: int | None = None,
        weekdays: list[str] | None = None,
        start_date: dt.date | None = None,
    ) -> None:
        """Write this station's schedule to the controller."""
        if (interval_days is None) == (weekdays is None):
            raise ServiceValidationError("Give either interval_days or weekdays")
        if duration > 0 and not start_times:
            raise ServiceValidationError("Give at least one start time")
        if weekdays is not None:
            cycle, days = CYCLE_WEEKLY, sum(1 << WEEKDAYS.index(d) for d in set(weekdays))
        else:
            cycle, days = CYCLE_INTERVAL, int(interval_days)
        date = start_date or dt_util.now().date()
        try:
            ok = await self.hass.async_add_executor_job(
                self.coordinator.api.set_schedule,
                self._zone,
                duration,
                [(t.hour, t.minute) for t in start_times],
                cycle,
                days,
                (date.year, date.month, date.day),
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        if not ok:
            raise HomeAssistantError("Schedule write failed (local connection required)")


class InkbirdClockSensor(InkbirdEntity, SensorEntity):
    """Clock state of a legacy IIC-600 (DP 106 ht1381a_timeerror).

    ``error`` means the controller's clock lost its time (typically after a
    power cut), so stored schedules may run at the wrong time or not at all.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "error"]
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_clock"
        self._attr_name = "Clock"

    @property
    def native_value(self) -> str:
        return "error" if self.coordinator.api.device.timeerror_alarm else "ok"
