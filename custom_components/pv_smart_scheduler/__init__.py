import logging
import json
import os
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.recorder import history
from homeassistant.util import dt as dt_util
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PROFILE_LOOKBACK_DAYS = 14
DEFAULT_BATTERY_MIN_SOC = 25

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Wird beim allgemeinen Starten von Home Assistant aufgerufen."""
    # Pfad zum frontend-Ordner innerhalb deiner Custom Component
    local_path = hass.config.path("custom_components/pv_smart_scheduler/frontend")
    
    if not os.path.exists(local_path):
        os.makedirs(local_path, exist_ok=True)

    # Schaltet den Ordner im HA-Webserver unter '/pv_smart_scheduler' freigeschaltet
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            url_path="/pv_smart_scheduler",
            path=local_path
        )
    ])

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {**entry.data, **entry.options}
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    if "global_coordinator" not in hass.data[DOMAIN]:
        coordinator = PVSmartSchedulerCoordinator(hass)
        hass.data[DOMAIN]["global_coordinator"] = coordinator
        # NUR hier beim ERSTEN Erstellen der Instanz den Refresh machen
        await coordinator.async_refresh_devices_config()
        await coordinator.async_config_entry_first_refresh()
    else:
        coordinator = hass.data[DOMAIN]["global_coordinator"]
        # Bei weiteren Instanzen reicht ein Refresh der Konfiguration
        await coordinator.async_refresh_devices_config()

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Aktualisiert die Konfiguration, wenn Optionen geändert wurden."""
    hass.data[DOMAIN][entry.entry_id] = {**entry.data, **entry.options}
    coordinator = hass.data[DOMAIN]["global_coordinator"]
    await coordinator.async_refresh_devices_config()
    await coordinator.async_refresh()

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Wird aufgerufen, wenn eine Instanz gelöscht wird."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        coordinator = hass.data[DOMAIN].get("global_coordinator")
        if coordinator:
            await coordinator.async_refresh_devices_config()
    return unload_ok


class PVSmartSchedulerCoordinator(DataUpdateCoordinator):
    """Zentraler Koordinator, der alle Geräte sammelt und kaskadierend priorisiert."""

    def __init__(self, hass):
        super().__init__(
            hass, 
            _LOGGER, 
            name=DOMAIN, 
            update_interval=timedelta(minutes=15)
        )
        self.devices_config = {}
        self.learned_profiles = {}
        self.last_context = {}
        self.profile_path = hass.config.path("pv_smart_scheduler_profiles_v3.json")

    async def async_refresh_devices_config(self):
        new_config = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            value = {**entry.data, **entry.options}
            devices = entry.data.get("devices", [])

            for device in devices:

                entity_id = device.get("device_power_sensor")

                if entity_id:
                    new_config[entity_id] = {
                        "target_coverage":
                            device.get("target_coverage", 90),

                        "priority":
                            device.get("priority", 1),

                        "pv_forecast_sensor":
                            value.get("pv_forecast_sensor"),

                        "home_base_load_sensor":
                            value.get("home_base_load_sensor"),

                        "pv_current_power_sensor":
                            value.get("pv_current_power_sensor"),

                        "battery_soc_sensor":
                            value.get("battery_soc_sensor"),

                        "battery_energy_sensor":
                            value.get("battery_energy_sensor"),

                        "battery_min_soc":
                            value.get("battery_min_soc", DEFAULT_BATTERY_MIN_SOC)
                    }
        self.devices_config = new_config
        await self.async_load_learned_profiles()

    async def async_load_learned_profiles(self):
        def load():
            if os.path.exists(self.profile_path):
                try:
                    with open(self.profile_path, "r") as f:
                        return json.load(f)
                except Exception as err:
                    _LOGGER.error(f"Fehler beim Laden der Profile: {err}")
            return {}
        self.learned_profiles = await self.hass.async_add_executor_job(load)

    def save_learned_profiles(self):
        try:
            with open(self.profile_path, "w") as f:
                json.dump(self.learned_profiles, f, indent=4)
        except Exception as err:
            _LOGGER.error(f"Fehler beim Speichern der Profile: {err}")

    async def _async_update_data(self):
        results = {}
        if not self.devices_config:
            return results

        sorted_devices = sorted(self.devices_config.items(), key=lambda x: x[1]["priority"])
        first_config = sorted_devices[0][1]
        raw_forecast = self._get_pv_forecast(first_config["pv_forecast_sensor"])
        weather_stability = self._calculate_weather_stability(first_config["pv_forecast_sensor"])
        current_pv_power = self._get_float_state(first_config.get("pv_current_power_sensor"), 0.0)
        battery_soc = self._get_float_state(first_config.get("battery_soc_sensor"))
        battery_energy_kwh = self._get_float_state(first_config.get("battery_energy_sensor"), 0.0)
        battery_min_soc = first_config.get("battery_min_soc", DEFAULT_BATTERY_MIN_SOC)
        battery_available_wh = self._calculate_available_battery_wh(
            battery_soc,
            battery_energy_kwh,
            battery_min_soc
        )

        virtual_pv_forecast = self._build_virtual_pv_forecast(
            raw_forecast,
            weather_stability,
            current_pv_power
        )
        remaining_battery_wh = battery_available_wh
        self.last_context = {
            "pv_current_power": round(current_pv_power, 1),
            "battery_soc": round(battery_soc, 1) if battery_soc is not None else None,
            "battery_available_kwh": round(battery_available_wh / 1000, 2),
            "battery_min_soc": battery_min_soc,
            "profile_lookback_days": PROFILE_LOOKBACK_DAYS
        }

        for entity_id, config in sorted_devices:
            try:
                profile = await self._get_adaptive_profile(entity_id)
                base_load_state = self.hass.states.get(config["home_base_load_sensor"])
                base_load = max(0.0, float(base_load_state.state)) if base_load_state and base_load_state.state not in ("unknown", "unavailable") else 300.0

                best_start, max_coverage, battery_used_wh = self._calculate_best_window(
                    profile, virtual_pv_forecast, base_load, remaining_battery_wh
                )

                recommendation = "ja" if max_coverage >= config["target_coverage"] and best_start == 0 else "warten"
                avg_watts = sum(profile) / len(profile) if profile else 0
                total_kwh = (avg_watts * (len(profile) / 60)) / 1000

                results[entity_id] = {
                    "recommendation": recommendation,
                    "best_start_mins": best_start,
                    "coverage_percent": round(max_coverage, 1),
                    "total_kwh": round(total_kwh, 2),
                    "battery_used_kwh": round(battery_used_wh / 1000, 2),
                    "weather_stability": round(weather_stability * 100, 0),
                    "priority": config["priority"]
                }

                if recommendation == "ja" and best_start == 0:
                    profile_len = len(profile)
                    for i in range(min(profile_len, len(virtual_pv_forecast))):
                        virtual_pv_forecast[i] = max(0.0, virtual_pv_forecast[i] - profile[i])
                    remaining_battery_wh = max(0.0, remaining_battery_wh - battery_used_wh)

            except Exception as err:
                _LOGGER.error(f"Fehler bei Berechnung für {entity_id}: {err}")
                results[entity_id] = {"recommendation": "warten", "best_start_mins": 0, "coverage_percent": 0, "total_kwh": 0, "weather_stability": 80, "priority": config["priority"]}
                
        return results

    def _calculate_weather_stability(self, forecast_sensor_id) -> float:
        state = self.hass.states.get(forecast_sensor_id)
        if not state or state.state in ("unknown", "unavailable"):
            return 0.85
        try:
            val = float(state.state)
            return 0.75 if val < 500 else (0.88 if val < 1500 else 0.95)
        except ValueError:
            return 0.85

    async def _get_adaptive_profile(self, entity_id):
        if entity_id in self.learned_profiles and len(self.learned_profiles[entity_id]) > 0:
            return self.learned_profiles[entity_id]

        now = dt_util.utcnow()
        history_list = await self.hass.async_add_executor_job(
            history.get_significant_states, self.hass, now - timedelta(days=PROFILE_LOOKBACK_DAYS), now, [entity_id]
        )
        default_profile = [300] * 120
        if entity_id not in history_list or not history_list[entity_id]:
            return default_profile

        active_phase = []
        for state in history_list[entity_id]:
            try:
                if state.state in ("unknown", "unavailable"): continue
                val = float(state.state)
                if val > 15: active_phase.append(val)
                elif len(active_phase) > 45: break
                else: active_phase = []
            except (ValueError, TypeError): continue

        if len(active_phase) > 30:
            self.learned_profiles[entity_id] = active_phase
            await self.hass.async_add_executor_job(self.save_learned_profiles)
            return active_phase
        return default_profile

    def _get_pv_forecast(self, forecast_sensor_id):
        state = self.hass.states.get(forecast_sensor_id)
        current_forecast = 1200.0
        if state and state.state not in ("unknown", "unavailable"):
            try: current_forecast = float(state.state)
            except ValueError: pass
        return [max(0, current_forecast - (i * 3)) for i in range(240)]

    def _get_float_state(self, entity_id, fallback=None):
        if not entity_id:
            return fallback

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return fallback

        try:
            return float(state.state)
        except (TypeError, ValueError):
            return fallback

    def _calculate_available_battery_wh(self, battery_soc, battery_energy_kwh, min_soc):
        if battery_soc is None or battery_soc < min_soc:
            return 0.0

        return max(0.0, battery_energy_kwh * 1000)

    def _build_virtual_pv_forecast(self, raw_forecast, weather_stability, current_pv_power):
        forecast = [watt * weather_stability for watt in raw_forecast]

        if current_pv_power <= 0:
            return forecast

        for minute in range(min(90, len(forecast))):
            current_pv_estimate = max(0.0, current_pv_power - (minute * 8))
            forecast[minute] = max(forecast[minute], current_pv_estimate)

        return forecast

    def _calculate_best_window(self, profile, forecast, base_load, battery_available_wh=0.0):
        profile_len = len(profile)
        forecast_len = len(forecast)
        if profile_len >= forecast_len: return 0, 0.0, 0.0
        
        best_start_minute = 0
        max_coverage_found = -1.0
        best_battery_used_wh = 0.0
        battery_available_watt_minutes = battery_available_wh * 60

        for start_min in range(0, forecast_len - profile_len, 15):
            total_device_energy = 0
            covered_by_pv_energy = 0
            missing_energy = 0
            for t in range(profile_len):
                device_power = profile[t]
                forecast_power = forecast[start_min + t]
                available_excess = max(0, forecast_power - base_load)
                total_device_energy += device_power
                covered_now = min(device_power, available_excess)
                covered_by_pv_energy += covered_now
                missing_energy += max(0, device_power - covered_now)

            covered_by_battery_energy = min(missing_energy, battery_available_watt_minutes)
            covered_energy = covered_by_pv_energy + covered_by_battery_energy
            
            coverage_percent = (covered_energy / total_device_energy) * 100 if total_device_energy > 0 else 0
            if coverage_percent > max_coverage_found:
                max_coverage_found = coverage_percent
                best_start_minute = start_min
                best_battery_used_wh = covered_by_battery_energy / 60
                
        return best_start_minute, max_coverage_found, best_battery_used_wh
