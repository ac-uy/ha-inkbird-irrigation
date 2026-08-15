"""Inkbird WiFi Irrigation Controller integration for Home Assistant.

Supports IIC-600 (6 zones) and IIC-800 (8 zones) models.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import Platform

from .api import InkbirdAPI
from .const import (
    CONF_CLOUD_API_KEY,
    CONF_CLOUD_API_REGION,
    CONF_CLOUD_API_SECRET,
    CONF_DEVICE_ID,
    CONF_DEVICE_IP,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    DOMAIN,
)
from .coordinator import InkbirdCoordinator
from .models import DeviceModel

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.NUMBER,
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
    """Set up Inkbird Irrigation from a config entry."""
    # Determine model — default to IIC-600 for backward compat with v1 entries
    model_str = entry.data.get(CONF_DEVICE_MODEL, DeviceModel.IIC_600.value)
    try:
        device_model = DeviceModel(model_str)
    except ValueError:
        device_model = DeviceModel.IIC_600

    api = InkbirdAPI(
        entry.data[CONF_DEVICE_ID],
        entry.data[CONF_LOCAL_KEY],
        entry.data[CONF_DEVICE_IP],
        cloud_api_key=entry.data.get(CONF_CLOUD_API_KEY, ""),
        cloud_api_secret=entry.data.get(CONF_CLOUD_API_SECRET, ""),
        cloud_api_region=entry.data.get(CONF_CLOUD_API_REGION, "eu"),
        device_model=device_model,
    )

    connected = await hass.async_add_executor_job(api.connect)
    if not connected:
        if api._has_cloud:
            cloud_ok = await hass.async_add_executor_job(api._cloud_update)
            if not cloud_ok:
                raise ConfigEntryNotReady(
                    f"Cannot connect to Inkbird {api.model.value} "
                    "(local and cloud both failed)"
                )
            _LOGGER.warning("Local connection failed, starting with cloud fallback")
            api._using_cloud = True
        else:
            raise ConfigEntryNotReady(
                f"Cannot connect to Inkbird {api.model.value}"
            )

    coordinator = InkbirdCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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
