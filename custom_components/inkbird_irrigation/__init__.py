"""Inkbird WiFi Irrigation Controller integration for Home Assistant.

Supports IIC-600 (6 zones) and IIC-800 (8 zones) models.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import InkbirdAPI
from .const import (
    CONF_CLOUD_API_KEY,
    CONF_CLOUD_API_REGION,
    CONF_CLOUD_API_SECRET,
    CONF_CONNECTION_MODE,
    CONNECTION_MODE_AUTO,
    CONNECTION_MODE_CLOUD,
    CONNECTION_MODE_LOCAL,
    CONF_DEVICE_ID,
    CONF_DEVICE_IP,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    CONF_LOCAL_PROTOCOL,
    DOMAIN,
)
from .coordinator import InkbirdCoordinator
from .models import DeviceModel

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries to current version."""
    _LOGGER.debug(
        "Migrating config entry from version %s", config_entry.version
    )

    if config_entry.version == 1:
        # v2 added device_model field; default to IIC-600 for existing setups
        new_data = {**config_entry.data, CONF_DEVICE_MODEL: DeviceModel.IIC_600.value}
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=2
        )
        _LOGGER.info(
            "Migrated config entry %s from v1 to v2 (added device_model=IIC-600)",
            config_entry.title,
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Inkbird Irrigation from a config entry.

    A failed initial local connection leaves the entry loaded and its entities
    unavailable. The transport coordinator then performs bounded recovery,
    avoiding Home Assistant setup retries that repeatedly create fresh Tuya
    sessions while the controller is rejecting local handshakes.
    """
    model_str = entry.data.get(CONF_DEVICE_MODEL, DeviceModel.IIC_600.value)
    try:
        device_model = DeviceModel(model_str)
    except ValueError:
        device_model = DeviceModel.IIC_600

    preference = entry.options.get(CONF_CONNECTION_MODE, CONNECTION_MODE_AUTO)
    if preference not in {
        CONNECTION_MODE_AUTO,
        CONNECTION_MODE_CLOUD,
        CONNECTION_MODE_LOCAL,
    }:
        preference = CONNECTION_MODE_AUTO

    api = InkbirdAPI(
        entry.data[CONF_DEVICE_ID],
        entry.data[CONF_LOCAL_KEY],
        entry.data[CONF_DEVICE_IP],
        cloud_api_key=entry.data.get(CONF_CLOUD_API_KEY, ""),
        cloud_api_secret=entry.data.get(CONF_CLOUD_API_SECRET, ""),
        cloud_api_region=entry.data.get(CONF_CLOUD_API_REGION, "eu"),
        device_model=device_model,
        connection_preference=preference,
        local_protocol=entry.data.get(CONF_LOCAL_PROTOCOL),
    )
    connected = False
    connection_description = "unavailable"

    if preference == CONNECTION_MODE_CLOUD:
        connected = await hass.async_add_executor_job(api.activate_cloud)
        if connected:
            connection_description = "cloud"
    else:
        connected = await hass.async_add_executor_job(api.activate_local)
        if connected:
            connection_description = "local"
        elif preference == CONNECTION_MODE_AUTO and api.has_cloud:
            connected = await hass.async_add_executor_job(api.activate_cloud)
            if connected:
                connection_description = "cloud"

    coordinator = InkbirdCoordinator(
        hass, api, entry, initially_unavailable=not connected
    )
    if api.active_transport == CONNECTION_MODE_LOCAL:
        await coordinator._persist_local_protocol()

    if connected:
        _LOGGER.info(
            "Starting Inkbird %s using %s transport",
            api.model.value,
            connection_description,
        )
        await coordinator.async_config_entry_first_refresh()
    else:
        api.device.online = False
        coordinator.async_set_updated_data(api.device)
        _LOGGER.warning(
            "Starting Inkbird %s unavailable; bounded background recovery will "
            "retry the local transport without re-running entry setup",
            api.model.value,
        )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    api.freeze_model()
    await coordinator.async_start_listener()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Inkbird Irrigation config entry."""
    coordinator: InkbirdCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator:
        await coordinator.async_stop_listener()
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
