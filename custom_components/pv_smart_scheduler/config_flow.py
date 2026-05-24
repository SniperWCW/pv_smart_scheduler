import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN

class PVSmartSchedulerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Sorgt für die Einrichtung der Integration über die UI."""
    
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Erster Schritt bei der Einrichtung durch den User."""
        errors = {}

        if user_input is not None:
            # Erstellt den Eintrag in der HA-Einstellungsübersicht
            return self.async_create_entry(
                title=f"Smart Scheduler ({user_input['device_power_sensor'].split('.')[-1]})", 
                data=user_input
            )

        # Formular-Schema für die UI mit echten HA-Entitäten-Selectoren
        data_schema = vol.Schema({
            vol.Required("device_power_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Required("pv_forecast_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required("home_base_load_sensor"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Required("target_coverage", default=90): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100)
            ),
        })

        return self.show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
