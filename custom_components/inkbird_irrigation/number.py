"""Number platform for Inkbird Irrigation — zone duration settings."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InkbirdCoordinator
from .entity import InkbirdEntity
from .models import DeviceModel

# Store duration preferences locally (not on device)
_zone_durations: dict[str, dict[int, int]] = {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Inkbird duration number entities."""
    coordinator: InkbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    profile = coordinator.api.profile
    model = coordinator.api.model
    num_zones = profile.num_zones

    _zone_durations.setdefault(entry.entry_id, {z: 30 for z in range(1, num_zones + 1)})

    entities: list[NumberEntity] = []

    # Per-zone duration setting (both models)
    for zone in range(1, num_zones + 1):
        entities.append(InkbirdZoneDuration(coordinator, zone))

    # Seasonal adjustment (both models, different ranges)
    entities.append(InkbirdSeasonalAdjust(coordinator))

    async_add_entities(entities)


class InkbirdZoneDuration(InkbirdEntity, NumberEntity):
    """Number entity for setting zone watering duration (used on next turn-on)."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 1
    _attr_native_max_value = 180
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, coordinator: InkbirdCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_zone_{zone}_duration"
        self._attr_name = f"Zone {zone} duration"

    @property
    def native_value(self) -> float:
        """Return the current duration setting."""
        entry_id = self.coordinator.entry.entry_id
        return _zone_durations.get(entry_id, {}).get(self._zone, 30)

    async def async_set_native_value(self, value: float) -> None:
        """Set the zone duration (used on next turn-on)."""
        entry_id = self.coordinator.entry.entry_id
        _zone_durations.setdefault(entry_id, {})[self._zone] = int(value)
        self.async_write_ha_state()


class InkbirdSeasonalAdjust(InkbirdEntity, NumberEntity):
    """Number entity for seasonal adjustment percentage."""

    _attr_native_unit_of_measurement = "%"
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_seasonal_adjust"
        self._attr_name = "Seasonal adjustment"

        # IIC-800 has range -90 to 100 (step 10); IIC-600 has 0-100 (step 1)
        if coordinator.api.model == DeviceModel.IIC_800:
            self._attr_native_min_value = -90
            self._attr_native_max_value = 100
            self._attr_native_step = 10
        else:
            self._attr_native_min_value = 0
            self._attr_native_max_value = 100
            self._attr_native_step = 1

    @property
    def native_value(self) -> float:
        """Return the current seasonal adjustment."""
        return self.coordinator.api.device.seasonal_adjust

    async def async_set_native_value(self, value: float) -> None:
        """Set the seasonal adjustment."""
        dp = self.coordinator.api.profile.dp_seasonal_adjust
        if dp is not None:
            await self.async_set_dp(dp, int(value))
