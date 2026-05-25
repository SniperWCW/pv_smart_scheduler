import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PVSmartSchedulerConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN
):
    VERSION = 2

    @staticmethod
    def async_get_options_flow(config_entry):
        return PVSmartSchedulerOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):

        existing_entries = self._async_current_entries()

        if user_input is not None:

            if existing_entries:

                entry = existing_entries[0]

                current_devices = list(
                    entry.data.get("devices", [])
                )

                current_devices.append({
                    "device_power_sensor": user_input["device_power_sensor"],
                    "target_coverage": user_input["target_coverage"],
                    "priority": user_input["priority"]
                })

                new_data = {
                    **entry.data,
                    "pv_forecast_sensor":
                        user_input["pv_forecast_sensor"],
                    "home_base_load_sensor":
                        user_input["home_base_load_sensor"],
                    "pv_current_power_sensor":
                        user_input.get("pv_current_power_sensor")
                        or entry.options.get("pv_current_power_sensor")
                        or entry.data.get("pv_current_power_sensor"),
                    "battery_soc_sensor":
                        user_input.get("battery_soc_sensor")
                        or entry.options.get("battery_soc_sensor")
                        or entry.data.get("battery_soc_sensor"),
                    "battery_energy_sensor":
                        user_input.get("battery_energy_sensor")
                        or entry.options.get("battery_energy_sensor")
                        or entry.data.get("battery_energy_sensor"),
                    "battery_min_soc":
                        user_input.get("battery_min_soc")
                        or entry.options.get("battery_min_soc")
                        or entry.data.get("battery_min_soc")
                        or 25,
                    "devices": current_devices
                }

                self.hass.config_entries.async_update_entry(
                    entry,
                    data=new_data
                )

                await self.hass.config_entries.async_reload(
                    entry.entry_id
                )

                return self.async_abort(
                    reason="device_added"
                )

            device_entity = user_input["device_power_sensor"]

            state = self.hass.states.get(device_entity)

            device_name = (
                state.attributes.get("friendly_name")
                if state
                else "Gerät"
            )

            data = {
                "pv_forecast_sensor":
                    user_input["pv_forecast_sensor"],

                "home_base_load_sensor":
                    user_input["home_base_load_sensor"],

                "pv_current_power_sensor":
                    user_input.get("pv_current_power_sensor"),

                "battery_soc_sensor":
                    user_input.get("battery_soc_sensor"),

                "battery_energy_sensor":
                    user_input.get("battery_energy_sensor"),

                "battery_min_soc":
                    user_input.get("battery_min_soc", 25),

                "devices": [
                    {
                        "device_power_sensor":
                            user_input["device_power_sensor"],

                        "target_coverage":
                            user_input["target_coverage"],

                        "priority":
                            user_input["priority"]
                    }
                ]
            }

            return self.async_create_entry(
                title="PV Smart Scheduler",
                data=data
            )

        defaults = {}

        if existing_entries:
            entry = existing_entries[0]

            defaults = {
                "pv_forecast_sensor":
                    entry.data.get("pv_forecast_sensor"),

                "home_base_load_sensor":
                    entry.data.get("home_base_load_sensor")
                    or entry.options.get("home_base_load_sensor"),

                "pv_current_power_sensor":
                    entry.data.get("pv_current_power_sensor")
                    or entry.options.get("pv_current_power_sensor"),

                "battery_soc_sensor":
                    entry.data.get("battery_soc_sensor")
                    or entry.options.get("battery_soc_sensor"),

                "battery_energy_sensor":
                    entry.data.get("battery_energy_sensor")
                    or entry.options.get("battery_energy_sensor"),

                "battery_min_soc":
                    entry.data.get("battery_min_soc")
                    or entry.options.get("battery_min_soc")
                    or 25
            }

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(defaults)
        )

    def _build_schema(self, defaults=None):

        defaults = defaults or {}

        return vol.Schema({

            vol.Required(
                "device_power_sensor"
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Required(
                "pv_forecast_sensor",
                default=defaults.get(
                    "pv_forecast_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor"
                )
            ),

            vol.Required(
                "home_base_load_sensor",
                default=defaults.get(
                    "home_base_load_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "pv_current_power_sensor",
                default=defaults.get(
                    "pv_current_power_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "battery_soc_sensor",
                default=defaults.get(
                    "battery_soc_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="battery"
                )
            ),

            vol.Optional(
                "battery_energy_sensor",
                default=defaults.get(
                    "battery_energy_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Required(
                "battery_min_soc",
                default=defaults.get("battery_min_soc", 25)
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=0, max=100)
            ),

            vol.Required(
                "target_coverage",
                default=90
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=1, max=100)
            ),

            vol.Required(
                "priority",
                default=1
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=1, max=10)
            )
        })


class PVSmartSchedulerOptionsFlowHandler(
    config_entries.OptionsFlow
):

    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "global_sensors",
                "remove_device"
            ]
        )

    async def async_step_global_sensors(self, user_input=None):

        if user_input is not None:

            return self.async_create_entry(
                title="",
                data=user_input
            )

        return self.async_show_form(
            step_id="global_sensors",
            data_schema=self._build_options_schema()
        )

    async def async_step_remove_device(self, user_input=None):
        devices = self._config_entry.data.get("devices", [])

        if user_input is not None:
            remove_entity_id = user_input["device_power_sensor"]
            new_devices = [
                device for device in devices
                if device.get("device_power_sensor") != remove_entity_id
            ]

            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data={
                    **self._config_entry.data,
                    "devices": new_devices
                }
            )

            return self.async_create_entry(
                title="",
                data=dict(self._config_entry.options)
            )

        if not devices:
            return self.async_abort(reason="no_devices")

        device_options = {
            device["device_power_sensor"]: self._device_label(device["device_power_sensor"])
            for device in devices
            if device.get("device_power_sensor")
        }

        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({
                vol.Required("device_power_sensor"): vol.In(device_options)
            })
        )

    def _build_options_schema(self):
        data = {
            **self._config_entry.data,
            **self._config_entry.options
        }

        return vol.Schema({
            vol.Required(
                "pv_forecast_sensor",
                default=data.get("pv_forecast_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor"
                )
            ),

            vol.Required(
                "home_base_load_sensor",
                default=data.get("home_base_load_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "pv_current_power_sensor",
                default=data.get("pv_current_power_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "battery_soc_sensor",
                default=data.get("battery_soc_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="battery"
                )
            ),

            vol.Optional(
                "battery_energy_sensor",
                default=data.get("battery_energy_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Required(
                "battery_min_soc",
                default=data.get("battery_min_soc", 25)
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=0, max=100)
            )
        })

    def _device_label(self, entity_id):
        state = self.hass.states.get(entity_id)
        if state:
            return state.attributes.get("friendly_name") or entity_id

        return entity_id
