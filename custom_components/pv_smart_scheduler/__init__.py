import logging
import datetime
import json
import os
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entry_health
from homeassistant.util import dt as dt_util
from homeassistant.components.recorder import history
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry):
    """Setup der Integration über ein UI Config Entry."""
    device_power_sensor = entry.data.get("device_power_sensor")
    
    configured_devices = {
        device_power_sensor: {
            "target_coverage": entry.data.get("target_coverage", 90),
            "pv_forecast_sensor": entry.data.get("pv_forecast_sensor"),
            "home_base_load_sensor": entry.data.get("home_base_load_sensor")
        }
    }

    coordinator = PVSmartSchedulerCoordinator(hass, configured_devices, entry.entry_id)
    await coordinator.async_load_learned_profiles()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Wird aufgerufen, wenn eine Instanz aus der UI gelöscht wird."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

class PVSmartSchedulerCoordinator(DataUpdateCoordinator):
    """Koordinator mit adaptiven Heuristiken."""

    def __init__(self, hass: HomeAssistant, devices, entry_id):
        super().__init__(
            hass, 
            _LOGGER, 
            name=DOMAIN, 
            update_interval=timedelta(minutes=15)
        )
        self.devices = devices
        self.learned_profiles = {}
        self.profile_path = hass.config.path(f"pv_smart_scheduler_profiles_{entry_id}.json")

    async def async_load_learned_profiles(self):
        """Lädt die gelernten Profile aus dem lokalen Speicher."""
        def load():
            if os.path.exists(self.profile_path):
                try:
                    with open(self.profile_path, "r") as f:
                        return json.load(f)
                except Exception as err:
                    _LOGGER.error(f"Fehler beim Laden der Profil-Datei: {err}")
            return {}
        self.learned_profiles = await self.hass.async_add_executor_job(load)

    def save_learned_profiles(self):
        """Speichert die gelernten Profile lokal ab."""
        try:
            os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
            with open(self.profile_path, "w") as f:
                json.dump(self.learned_profiles, f, indent=4)
        except Exception as err:
            _LOGGER.error(f"Fehler beim Speichern der Profile: {err}")

    async def _async_update_data(self):
        """Berechnet Empfehlungen basierend auf adaptiven Heuristiken."""
        results = {}

        for entity_id, config in self.devices.items():
            try:
                weather_stability_factor = self._calculate_weather_stability(config["pv_forecast_sensor"])
                profile = await self._get_adaptive_profile(entity_id)
                
                raw_forecast = self._get_pv_forecast(config["pv_forecast_sensor"])
                stable_forecast = [watt * weather_stability_factor for watt in raw_forecast]
                
                base_load_state = self.hass.states.get(config["home_base_load_sensor"])
                if base_load_state and base_load_state.state not in ("unknown", "unavailable"):
                    base_load = max(0.0, float(base_load_state.state))
                else:
                    base_load = 300.0
                    _LOGGER.warning(f"Basislast-Sensor {config['home_base_load_sensor']} nicht verfügbar.")

                best_start, max_coverage = self._calculate_best_window(
                    profile, stable_forecast, base_load
                )

                # Annäherung: Wenn die Liste z.B. 120 Einträge hat, gehen wir von ca. 120 Minuten aus
                avg_watts = sum(profile) / len(profile) if profile else 0
                estimated_hours = len(profile) / 60
                total_kwh = (avg_watts * estimated_hours) / 1000

                results[entity_id] = {
                    "recommendation": "ja" if max_coverage >= config["target_coverage"] and best_start == 0 else "warten",
                    "best_start_mins": best_start,
                    "coverage_percent": round(max_coverage, 1),
                    "total_kwh": round(total_kwh, 2),
                    "weather_stability": round(weather_stability_factor * 100, 0)
                }
            except Exception as err:
                _LOGGER.error(f"Kritischer Fehler bei Berechnung für {entity_id}: {err}")
                
        return results

    def _calculate_weather_stability(self, forecast_sensor_id) -> float:
        state = self.hass.states.get(forecast_sensor_id)
        if not state or state.state in ("unknown", "unavailable"):
            return 0.85
        try:
            forecast_val = float(state.state)
            if forecast_val < 500:
                return 0.75
            elif forecast_val < 1500:
                return 0.88
        except ValueError:
            pass
        return 0.95 

    async def _get_adaptive_profile(self, entity_id):
        if entity_id in self.learned_profiles and len(self.learned_profiles[entity_id]) > 0:
            return self.learned_profiles[entity_id]

        _LOGGER.info(f"Lerne neues Profil für {entity_id} aus der Historie...")
        now = dt_util.utcnow()
        start_time = now - timedelta(days=3)
        
        history_list = await self.hass.async_add_executor_job(
            history.get_significant_states, self.hass, start_time, now, [entity_id]
        )

        default_profile = [300] * 120

        if entity_id not in history_list or not history_list[entity_id]:
            return default_profile

        states = history_list[entity_id]
        active_phase = []
        for state in states:
            try:
                if state.state in ("unknown", "unavailable"):
                    continue
                val = float(state.state)
                if val > 15:
                    active_phase.append(val)
                elif len(active_phase) > 45: 
                    break
                else:
                    active_phase = []
            except (ValueError, TypeError):
                continue

        if len(active_phase) > 30:
            self.learned_profiles[entity_id] = active_phase
            await self.hass.async_add_executor_job(self.save_learned_profiles)
            return active_phase

        return default_profile

    def _get_pv_forecast(self, forecast_sensor_id):
        state = self.hass.states.get(forecast_forecast_id := forecast_sensor_id)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                current_forecast = float(state.state)
            except ValueError:
                current_forecast = 1200.0
        else:
            current_forecast = 1200.0
        return [max(0, current_forecast - (i * 3)) for i in range(240)]

    def _calculate_best_window(self, profile, forecast, base_load):
        profile_len = len(profile)
        forecast_len = len(forecast)
        if profile_len >= forecast_len:
            return 0, 0.0
        best_start_minute = 0
        max_coverage_found = 0.0

        for start_min in range(0, forecast_len - profile_len, 15):
            total_device_energy = 0
            covered_by_pv_energy = 0
            for t in range(profile_len):
                device_power = profile[t]
                forecast_power = forecast[start_min + t]
                available_excess = max(0, forecast_power - base_load)
                total_device_energy += device_power
                covered_by_pv_energy += min(device_power, available_excess)
            coverage_percent = (covered_by_pv_energy / total_device_energy) * 100 if total_device_energy > 0 else 0
            if coverage_percent > max_coverage_found:
                max_coverage_found = coverage_percent
                best_start_minute = start_min
        return best_start_minute, max_coverage_found
