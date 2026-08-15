"""Config flow for Inkbird Irrigation."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

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
from .models import DeviceModel

_LOGGER = logging.getLogger(__name__)

MODEL_OPTIONS = {
    "auto": "Auto-detect",
    DeviceModel.IIC_400.value: "IIC-400 (4 zones)",
    DeviceModel.IIC_600.value: "IIC-600 (6 zones)",
    DeviceModel.IIC_800.value: "IIC-800 (8 zones)",
}

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME, default="Inkbird Irrigation"): str,
        vol.Required(CONF_DEVICE_MODEL, default="auto"): vol.In(MODEL_OPTIONS),
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Required(CONF_DEVICE_IP): str,
        vol.Optional(CONF_CLOUD_API_KEY): str,
        vol.Optional(CONF_CLOUD_API_SECRET): str,
        vol.Optional(CONF_CLOUD_API_REGION, default="eu"): str,
    }
)


class InkbirdIrrigationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Inkbird Irrigation."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Determine model for initial connection attempt
            model_choice = user_input.get(CONF_DEVICE_MODEL, "auto")
            if model_choice == "auto":
                # Default to IIC-600 for connection; auto-detect will override
                initial_model = DeviceModel.IIC_600
            else:
                initial_model = DeviceModel(model_choice)

            api = InkbirdAPI(
                user_input[CONF_DEVICE_ID],
                user_input[CONF_LOCAL_KEY],
                user_input[CONF_DEVICE_IP],
                cloud_api_key=user_input.get(CONF_CLOUD_API_KEY, ""),
                cloud_api_secret=user_input.get(CONF_CLOUD_API_SECRET, ""),
                cloud_api_region=user_input.get(CONF_CLOUD_API_REGION, "eu"),
                device_model=initial_model,
            )
            connected = await self.hass.async_add_executor_job(api.connect)

            if not connected and api.has_cloud:
                cloud_ok = await self.hass.async_add_executor_job(api._cloud_update)
                if cloud_ok:
                    connected = True
                    _LOGGER.warning(
                        "Local connection failed, but cloud API works. "
                        "Setting up with cloud fallback."
                    )

            if connected:
                await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()

                # Store the detected/chosen model in config data
                user_input[CONF_DEVICE_MODEL] = api.model.value

                return self.async_create_entry(
                    title=user_input[CONF_DEVICE_NAME],
                    data=user_input,
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Offer safe, separately validated connection reconfiguration paths."""
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["reconfigure_local", "reconfigure_cloud"],
        )

    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Replace Local Key or IP after a read-only local status verification."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            # The controller accepts only one local persistent connection. Unload
            # the active listener before opening the temporary read-only session.
            # If validation fails, reload the unchanged entry to restore it.
            was_loaded = entry.entry_id in self.hass.data.get(DOMAIN, {})
            if was_loaded and not await self.hass.config_entries.async_unload(
                entry.entry_id
            ):
                errors["base"] = "cannot_prepare_local"
            else:
                model_str = entry.data.get(CONF_DEVICE_MODEL, DeviceModel.IIC_600.value)
                try:
                    device_model = DeviceModel(model_str)
                except ValueError:
                    device_model = DeviceModel.IIC_600

                api = InkbirdAPI(
                    entry.data[CONF_DEVICE_ID],
                    user_input[CONF_LOCAL_KEY],
                    user_input[CONF_DEVICE_IP],
                    device_model=device_model,
                )
                try:
                    connected = await self.hass.async_add_executor_job(api.connect)
                finally:
                    await self.hass.async_add_executor_job(api.close)

                if connected:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY],
                            CONF_DEVICE_IP: user_input[CONF_DEVICE_IP],
                            CONF_DEVICE_MODEL: api.model.value,
                        },
                        reason="reconfigure_successful",
                    )

                if was_loaded:
                    await self.hass.config_entries.async_reload(entry.entry_id)
                errors["base"] = "cannot_connect_local"

        schema = vol.Schema(
            {
                vol.Required(CONF_LOCAL_KEY): str,
                vol.Required(
                    CONF_DEVICE_IP,
                    default=entry.data.get(CONF_DEVICE_IP, ""),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure_local", data_schema=schema, errors=errors
        )

    async def async_step_reconfigure_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Replace Tuya Cloud credentials after a read-only cloud-status verification."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            model_str = entry.data.get(CONF_DEVICE_MODEL, DeviceModel.IIC_600.value)
            try:
                device_model = DeviceModel(model_str)
            except ValueError:
                device_model = DeviceModel.IIC_600

            api = InkbirdAPI(
                entry.data[CONF_DEVICE_ID],
                entry.data[CONF_LOCAL_KEY],
                entry.data[CONF_DEVICE_IP],
                cloud_api_key=user_input[CONF_CLOUD_API_KEY],
                cloud_api_secret=user_input[CONF_CLOUD_API_SECRET],
                cloud_api_region=user_input[CONF_CLOUD_API_REGION],
                device_model=device_model,
            )
            cloud_ok = await self.hass.async_add_executor_job(api._cloud_update)
            if cloud_ok:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_CLOUD_API_KEY: user_input[CONF_CLOUD_API_KEY],
                        CONF_CLOUD_API_SECRET: user_input[CONF_CLOUD_API_SECRET],
                        CONF_CLOUD_API_REGION: user_input[CONF_CLOUD_API_REGION],
                    },
                    reason="reconfigure_successful",
                )
            errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CLOUD_API_KEY,
                    default=entry.data.get(CONF_CLOUD_API_KEY, ""),
                ): str,
                vol.Required(CONF_CLOUD_API_SECRET): str,
                vol.Required(
                    CONF_CLOUD_API_REGION,
                    default=entry.data.get(CONF_CLOUD_API_REGION, "eu"),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure_cloud", data_schema=schema, errors=errors
        )
