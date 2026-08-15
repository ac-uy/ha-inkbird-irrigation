"""Connection preference selector for Inkbird Irrigation."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONNECTION_MODE_AUTO,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LOCAL,
    DOMAIN,
)
from .coordinator import InkbirdCoordinator
from .entity import InkbirdEntity

_OPTIONS = {
    CONNECTION_MODE_AUTO: "Auto",
    CONNECTION_MODE_LOCAL: "Local",
    CONNECTION_MODE_CLOUD: "Cloud",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connection preference selector."""
    coordinator: InkbirdCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([InkbirdConnectionPreferenceSelect(coordinator)])


class InkbirdConnectionPreferenceSelect(InkbirdEntity, SelectEntity):
    """Select the requested controller transport policy."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:connection"
    _attr_options = list(_OPTIONS.values())

    def __init__(self, coordinator: InkbirdCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_connection_preference"
        self._attr_name = "Connection preference"

    @property
    def current_option(self) -> str:
        """Return the policy that was successfully activated."""
        return _OPTIONS[self.coordinator.api.connection_preference]

    async def async_select_option(self, option: str) -> None:
        """Verify the requested transport before persisting the selection."""
        preferences = {label: value for value, label in _OPTIONS.items()}
        preference = preferences.get(option)
        if preference is None:
            raise HomeAssistantError(f"Unsupported connection preference: {option}")
        try:
            await self.coordinator.async_set_connection_preference(preference)
        except Exception as exc:
            raise HomeAssistantError(
                f"Could not activate {option} connection mode"
            ) from exc
        self.async_write_ha_state()
