"""Base entity for Inkbird Irrigation."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InkbirdCoordinator
from .models import DeviceModel


class InkbirdEntity(CoordinatorEntity[InkbirdCoordinator]):
    """Base class for Inkbird entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._device_id = coordinator.entry.data["device_id"]

    async def async_set_dp(self, dp: int, value: object) -> None:
        """Set a controller data point and surface transport failures to HA."""
        success = await self.hass.async_add_executor_job(
            self.coordinator.api.set_dp, dp, value
        )
        if not success:
            raise HomeAssistantError(
                f"Controller cannot set DP {dp} using the active connection mode"
            )
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        model = self.coordinator.api.model
        model_name = {
            DeviceModel.IIC_600: "IIC-600-WIFI",
            DeviceModel.IIC_600_V35: "IIC-600-WIFI (v3.5 / DP45)",
            DeviceModel.IIC_800: "IIC-800-WIFI",
        }.get(model, model.value)

        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self.coordinator.entry.data.get("device_name", f"Inkbird {model.value}"),
            manufacturer="Inkbird",
            model=model_name,
        )
