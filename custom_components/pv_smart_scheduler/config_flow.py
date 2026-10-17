import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_BATTERY_MIN_SOC = 25
DEFAULT_SCHEDULE_START_TIME = "05:00"
DEFAULT_SCHEDULE_END_TIME = "23:00"

# Globale Einstellungen, die für alle Geräte gelten.
GLOBAL_REQUIRED_KEYS = (
    "pv_forecast_sensor",
    "home_base_load_sensor",
    "battery_min_soc",
    "schedule_start_time",
    "schedule_end_time",
)
GLOBAL_OPTIONAL_KEYS = (
    "pv_forecast_tomorrow_sensor",
    "pv_current_power_sensor",
    "battery_soc_sensor",
    "battery_energy_sensor",
    "battery_capacity_sensor",
    "battery_charge_power_sensor",
    "battery_discharge_power_sensor",
    "grid_import_energy_sensor",
    "grid_export_energy_sensor",
    "night_consumption_sensor",
)
GLOBAL_KEYS = GLOBAL_REQUIRED_KEYS + GLOBAL_OPTIONAL_KEYS


def _merged_settings(entry):
    """Effektive Einstellungen: Optionen haben Vorrang vor den Eintragsdaten."""
    return {**entry.data, **entry.options}


def _without_none(values):
    return {key: value for key, value in values.items() if value is not None}


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
                    "device_state_sensor": user_input.get("device_state_sensor"),
                    "target_coverage": user_input["target_coverage"],
                    "priority": user_input["priority"],
                    "min_run_minutes": user_input.get("min_run_minutes", 0),
                    "min_pause_minutes": user_input.get("min_pause_minutes", 0),
                    "offpeak_start_time": user_input.get("offpeak_start_time")
                })

                merged = _merged_settings(entry)
                new_data = {**entry.data, "devices": current_devices}
                # Das Formular ist mit den aktuellen Werten vorbelegt. Ein
                # fehlendes optionales Feld bedeutet daher: bewusst geleert.
                for key in GLOBAL_OPTIONAL_KEYS:
                    new_data[key] = user_input.get(key)
                new_data["pv_forecast_sensor"] = user_input["pv_forecast_sensor"]
                new_data["home_base_load_sensor"] = user_input["home_base_load_sensor"]
                new_data["battery_min_soc"] = user_input.get(
                    "battery_min_soc",
                    merged.get("battery_min_soc", DEFAULT_BATTERY_MIN_SOC)
                )
                new_data["schedule_start_time"] = user_input.get(
                    "schedule_start_time",
                    merged.get("schedule_start_time", DEFAULT_SCHEDULE_START_TIME)
                )
                new_data["schedule_end_time"] = user_input.get(
                    "schedule_end_time",
                    merged.get("schedule_end_time", DEFAULT_SCHEDULE_END_TIME)
                )
                # Alte Options-Werte würden die neuen Eintragsdaten überstimmen.
                new_options = {
                    key: value for key, value in entry.options.items()
                    if key not in GLOBAL_KEYS
                }

                self.hass.config_entries.async_update_entry(
                    entry,
                    data=new_data,
                    options=new_options
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

                "pv_forecast_tomorrow_sensor":
                    user_input.get("pv_forecast_tomorrow_sensor"),

                "pv_current_power_sensor":
                    user_input.get("pv_current_power_sensor"),

                "battery_soc_sensor":
                    user_input.get("battery_soc_sensor"),

                "battery_energy_sensor":
                    user_input.get("battery_energy_sensor"),

                "battery_capacity_sensor":
                    user_input.get("battery_capacity_sensor"),

                "battery_charge_power_sensor":
                    user_input.get("battery_charge_power_sensor"),

                "battery_discharge_power_sensor":
                    user_input.get("battery_discharge_power_sensor"),

                "grid_import_energy_sensor":
                    user_input.get("grid_import_energy_sensor"),

                "grid_export_energy_sensor":
                    user_input.get("grid_export_energy_sensor"),

                "battery_min_soc":
                    user_input.get("battery_min_soc", 25),

                "night_consumption_sensor":
                    user_input.get("night_consumption_sensor"),

                "schedule_start_time":
                    user_input.get("schedule_start_time", "05:00"),

                "schedule_end_time":
                    user_input.get("schedule_end_time", "23:00"),

                "devices": [
                    {
                        "device_power_sensor":
                            user_input["device_power_sensor"],

                        "device_state_sensor":
                            user_input.get("device_state_sensor"),

                        "target_coverage":
                            user_input["target_coverage"],

                        "priority":
                            user_input["priority"],
                        "min_run_minutes": user_input.get("min_run_minutes", 0),
                        "min_pause_minutes": user_input.get("min_pause_minutes", 0),
                        "offpeak_start_time": user_input.get("offpeak_start_time")
                    }
                ]
            }

            return self.async_create_entry(
                title="PV Smart Scheduler",
                data=data
            )

        defaults = {}

        if existing_entries:
            defaults = _without_none(
                {
                    key: _merged_settings(existing_entries[0]).get(key)
                    for key in GLOBAL_KEYS
                }
            )

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

            vol.Optional(
                "device_state_sensor"
            ): selector.EntitySelector(
                selector.EntitySelectorConfig()
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

            vol.Optional(
                "pv_forecast_tomorrow_sensor",
                default=defaults.get(
                    "pv_forecast_tomorrow_sensor",
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

            vol.Optional(
                "battery_capacity_sensor",
                default=defaults.get(
                    "battery_capacity_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Optional(
                "battery_charge_power_sensor",
                default=defaults.get(
                    "battery_charge_power_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "battery_discharge_power_sensor",
                default=defaults.get(
                    "battery_discharge_power_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "grid_import_energy_sensor",
                default=defaults.get(
                    "grid_import_energy_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Optional(
                "grid_export_energy_sensor",
                default=defaults.get(
                    "grid_export_energy_sensor",
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

            vol.Optional(
                "night_consumption_sensor",
                default=defaults.get(
                    "night_consumption_sensor",
                    vol.UNDEFINED
                )
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Required(
                "schedule_start_time",
                default=defaults.get("schedule_start_time", "05:00")
            ): selector.TimeSelector(),

            vol.Required(
                "schedule_end_time",
                default=defaults.get("schedule_end_time", "23:00")
            ): selector.TimeSelector(),

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
            ),
            vol.Optional("min_run_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=720)),
            vol.Optional("min_pause_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=720)),
            vol.Optional("offpeak_start_time", default=vol.UNDEFINED): selector.TimeSelector()
        })


class PVSmartSchedulerOptionsFlowHandler(
    config_entries.OptionsFlow
):

    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._selected_device_id = None

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "global_sensors",
                "edit_device_select",
                "remove_device"
            ]
        )

    async def async_step_edit_device_select(self, user_input=None):
        """Schritt 1: Gerät zum Bearbeiten auswählen."""
        devices = self._config_entry.data.get("devices", [])
        
        if user_input is not None:
            self._selected_device_id = user_input["device_power_sensor"]
            return await self.async_step_edit_device_form()

        if not devices:
            return self.async_abort(reason="no_devices")

        device_options = {
            device["device_power_sensor"]: self._device_label(device["device_power_sensor"])
            for device in devices
        }

        return self.async_show_form(
            step_id="edit_device_select",
            data_schema=vol.Schema({
                vol.Required("device_power_sensor"): vol.In(device_options)
            })
        )

    async def async_step_edit_device_form(self, user_input=None):
        """Schritt 2: Die Daten des ausgewählten Geräts bearbeiten."""
        devices = list(self._config_entry.data.get("devices", []))
        current_device = next((d for d in devices if d.get("device_power_sensor") == self._selected_device_id), None)

        if user_input is not None:
            new_devices = []
            for device in devices:
                if device.get("device_power_sensor") == self._selected_device_id:
                    new_devices.append({
                        "device_power_sensor": user_input["device_power_sensor"],
                        "device_state_sensor": user_input.get("device_state_sensor"),
                        "target_coverage": user_input["target_coverage"],
                        "priority": user_input["priority"],
                        "min_run_minutes": user_input.get("min_run_minutes", 0),
                        "min_pause_minutes": user_input.get("min_pause_minutes", 0),
                        "offpeak_start_time": user_input.get("offpeak_start_time")
                    })
                else:
                    new_devices.append(device)

            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data={**self._config_entry.data, "devices": new_devices}
            )
            return self.async_create_entry(title="", data=dict(self._config_entry.options))

        schema = vol.Schema({
            vol.Required(
                "device_power_sensor", 
                default=current_device["device_power_sensor"]
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(
                "device_state_sensor",
                default=current_device.get("device_state_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig()
            ),
            vol.Required(
                "target_coverage", 
                default=current_device.get("target_coverage", 90)
            ): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100)
            ),
            vol.Required(
                "priority", 
                default=current_device.get("priority", 1)
            ): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=10)
            ),
            vol.Optional("min_run_minutes", default=current_device.get("min_run_minutes", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=720)),
            vol.Optional("min_pause_minutes", default=current_device.get("min_pause_minutes", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=720)),
            vol.Optional("offpeak_start_time", default=current_device.get("offpeak_start_time", vol.UNDEFINED)): selector.TimeSelector()
        })

        return self.async_show_form(
            step_id="edit_device_form",
            data_schema=schema
        )

    async def async_step_global_sensors(self, user_input=None):

        if user_input is not None:
            # Geleerte optionale Felder fehlen in user_input. Sie werden als None
            # gespeichert, damit sie den alten Wert aus entry.data überschreiben.
            new_options = {**self._config_entry.options}
            for key in GLOBAL_OPTIONAL_KEYS:
                new_options[key] = user_input.get(key)
            for key in GLOBAL_REQUIRED_KEYS:
                if key in user_input:
                    new_options[key] = user_input[key]

            return self.async_create_entry(
                title="",
                data=new_options
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
        data = _without_none(_merged_settings(self._config_entry))

        return vol.Schema({
            vol.Required(
                "pv_forecast_sensor",
                default=data.get("pv_forecast_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor"
                )
            ),

            vol.Optional(
                "pv_forecast_tomorrow_sensor",
                default=data.get("pv_forecast_tomorrow_sensor", vol.UNDEFINED)
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

            vol.Optional(
                "battery_capacity_sensor",
                default=data.get("battery_capacity_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Optional(
                "battery_charge_power_sensor",
                default=data.get("battery_charge_power_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "battery_discharge_power_sensor",
                default=data.get("battery_discharge_power_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="power"
                )
            ),

            vol.Optional(
                "grid_import_energy_sensor",
                default=data.get("grid_import_energy_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Optional(
                "grid_export_energy_sensor",
                default=data.get("grid_export_energy_sensor", vol.UNDEFINED)
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
            ),

            vol.Optional(
                "night_consumption_sensor",
                default=data.get("night_consumption_sensor", vol.UNDEFINED)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy"
                )
            ),

            vol.Required(
                "schedule_start_time",
                default=data.get("schedule_start_time", "05:00")
            ): selector.TimeSelector(),

            vol.Required(
                "schedule_end_time",
                default=data.get("schedule_end_time", "23:00")
            ): selector.TimeSelector()
        })

    def _device_label(self, entity_id):
        state = self.hass.states.get(entity_id)
        if state:
            return state.attributes.get("friendly_name") or entity_id

        return entity_id
