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
        self.config_entry = config_entry

    async def async_step_init(
        self,
        user_input=None
    ):

        if user_input is not None:

            new_data = {
                **self.config_entry.data,
                **user_input
            }

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data
            )

            return self.async_abort(
                reason="reconfigured"
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({})
        )
