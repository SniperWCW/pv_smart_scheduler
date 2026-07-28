import logging
import json
import os
import math
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
DEVICE_ACTIVE_POWER_THRESHOLD = 15
FORECAST_HORIZON_MINUTES = 720
DEFAULT_SCHEDULE_START_TIME = "05:00"
DEFAULT_SCHEDULE_END_TIME = "23:00"
DEFAULT_NIGHT_HOURS = 12
MAX_PROFILE_POWER_W = 25000
MAX_PROFILE_ENERGY_WH = 50000

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
        await coordinator.async_refresh_devices_config()
        await coordinator.async_refresh()

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
            await coordinator.async_refresh()
    return unload_ok


class PVSmartSchedulerCoordinator(DataUpdateCoordinator):
    """Zentraler Koordinator, der alle Geräte sammelt und kaskadierend priorisiert."""

    def __init__(self, hass):
        super().__init__(
            hass, 
            _LOGGER, 
            name=DOMAIN, 
            update_interval=timedelta(minutes=1)
        )
        self.devices_config = {}
        self.configured_device_count = 0
        self.unique_device_count = 0
        self.learned_profiles = {}
        self.last_context = {}
        self._profile_query_timestamps = {}
        self.profile_path = hass.config.path("pv_smart_scheduler_profiles_v3.json")

    async def async_refresh_devices_config(self):
        new_config = {}
        configured_device_count = 0
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            value = {**entry.data, **entry.options}
            devices = entry.data.get("devices", [])

            for device in devices:

                entity_id = device.get("device_power_sensor")

                if entity_id:
                    configured_device_count += 1
                    new_config[entity_id] = {
                        "device_state_sensor":
                            device.get("device_state_sensor"),

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

                        "battery_capacity_sensor":
                            value.get("battery_capacity_sensor"),

                        "battery_charge_power_sensor":
                            value.get("battery_charge_power_sensor"),

                        "battery_discharge_power_sensor":
                            value.get("battery_discharge_power_sensor"),

                        "grid_import_energy_sensor":
                            value.get("grid_import_energy_sensor"),

                        "grid_export_energy_sensor":
                            value.get("grid_export_energy_sensor"),

                        "battery_min_soc":
                            value.get("battery_min_soc", DEFAULT_BATTERY_MIN_SOC),

                        "night_consumption_sensor":
                            value.get("night_consumption_sensor"),

                        "schedule_start_time":
                            value.get("schedule_start_time", DEFAULT_SCHEDULE_START_TIME),

                        "schedule_end_time":
                            value.get("schedule_end_time", DEFAULT_SCHEDULE_END_TIME)
                    }
        self.devices_config = new_config
        self.configured_device_count = configured_device_count
        self.unique_device_count = len(new_config)
        await self.async_load_learned_profiles()
        valid_entities = set(new_config.keys())
        pruned_profiles = {
            entity_id: profile
            for entity_id, profile in self.learned_profiles.items()
            if entity_id in valid_entities
        }
        if pruned_profiles != self.learned_profiles:
            self.learned_profiles = pruned_profiles
            await self.hass.async_add_executor_job(self.save_learned_profiles)

    async def async_load_learned_profiles(self):
        def load():
            if os.path.exists(self.profile_path):
                try:
                    with open(self.profile_path, "r", encoding="utf-8") as f:
                        raw_profiles = json.load(f)
                    return self._sanitize_profile_store(raw_profiles)
                except Exception as err:
                    _LOGGER.error(f"Fehler beim Laden der Profile: {err}")
            return {}
        self.learned_profiles = await self.hass.async_add_executor_job(load)

    def save_learned_profiles(self):
        try:
            directory = os.path.dirname(self.profile_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

            sanitized_profiles = self._sanitize_profile_store(self.learned_profiles)
            tmp_path = f"{self.profile_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(sanitized_profiles, f, indent=4)
            os.replace(tmp_path, self.profile_path)
            self.learned_profiles = sanitized_profiles
        except Exception as err:
            _LOGGER.error(f"Fehler beim Speichern der Profile: {err}")

    def _sanitize_profile_store(self, raw_profiles):
        if not isinstance(raw_profiles, dict):
            return {}

        sanitized = {}
        for entity_id, profile in raw_profiles.items():
            normalized_profile = self._normalize_profile(profile)
            if not isinstance(entity_id, str) or normalized_profile is None:
                continue
            sanitized[entity_id] = normalized_profile

        return sanitized

    def _normalize_profile(self, profile):
        if not isinstance(profile, list):
            return None

        cleaned_profile = []
        for value in profile:
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue

            if not math.isfinite(numeric_value):
                continue

            if numeric_value < 0:
                numeric_value = 0.0

            if numeric_value > MAX_PROFILE_POWER_W:
                continue

            cleaned_profile.append(round(numeric_value, 3))

        if len(cleaned_profile) < 10:
            return None

        total_energy_wh = sum(cleaned_profile) / 60.0
        if total_energy_wh <= 50 or total_energy_wh > MAX_PROFILE_ENERGY_WH:
            return None

        return cleaned_profile

    def _clean_numeric_string(self, val_str):
        """Säubert einen String und wandelt ihn in eine float-kompatible Zahl um."""
        if not val_str:
            return None
        
        # Entferne Leerzeichen und Sonderzeichen wie geschützte Leerzeichen
        val_str = val_str.strip().replace('\xa0', ' ')
        # Falls Einheiten vorhanden sind ("1942 W"), nimm nur den ersten Teil
        val_str = val_str.split()[0]

        # Fall A: Sowohl Punkt als auch Komma vorhanden (z.B. 1.234,56)
        if "," in val_str and "." in val_str:
            if val_str.rfind(",") > val_str.rfind("."):
                # Deutsch: 1.234,56 -> 1234.56
                val_str = val_str.replace(".", "").replace(",", ".")
            else:
                # US: 1,234.56 -> 1234.56
                val_str = val_str.replace(",", "")
        else:
            # Fall B: Nur ein Trenner vorhanden (Punkt ODER Komma)
            # Wir prüfen, ob es ein Tausender-Trenner sein könnte (z.B. 1.942 oder 1,942)
            separator = "." if "." in val_str else ("," if "," in val_str else None)
            if separator:
                parts = val_str.split(separator)
                # Wenn genau 3 Stellen nach dem Trenner folgen -> Tausender-Trenner
                # Ausnahme: Werte wie "0.123" sind Dezimalzahlen.
                if len(parts) == 2 and len(parts[1]) == 3 and not val_str.startswith("0" + separator):
                    val_str = val_str.replace(separator, "")
                else:
                    # Ansonsten: Komma zu Punkt wandeln für float()
                    val_str = val_str.replace(",", ".")
        
        try:
            return float(val_str)
        except ValueError:
            return None

    def _parse_state_value(self, state):
        """Extrahiert einen Float-Wert aus einem State-Objekt unter Berücksichtigung von Einheiten."""
        if not state or state.state in ("unknown", "unavailable", ""):
            return None

        # 1. Zuerst den Haupt-Status versuchen (wenn es eine Zahl ist, ist das die Quelle der Wahrheit)
        val = self._clean_numeric_string(state.state)
        if val is not None:
            unit = state.attributes.get("unit_of_measurement")
            if unit and unit.strip().lower() == "kw":
                val *= 1000.0
            return val

        # 2. Wenn der Status keine Zahl ist (z.B. "on", "heating"), prüfe Attribute
        for attr in ("current_power_w", "power", "load", "current_consumption", "power_consumption", "watt", "watts", "current_power"):
            attr_val = state.attributes.get(attr)
            if attr_val is not None:
                parsed = self._clean_numeric_string(str(attr_val))
                if parsed is not None:
                    return parsed

        try:
            return None
        except (TypeError, ValueError, IndexError):
            return None

    def _is_device_running(self, current_power, state_sensor_state=None):
        """Returns device activity using an optional state sensor, otherwise power."""
        if state_sensor_state is not None:
            raw_state = str(state_sensor_state.state or "").lower()
            inactive_states = {
                "off",
                "idle",
                "standby",
                "unavailable",
                "unknown",
                "0",
                "false",
                "closed"
            }
            active_states = {
                "on",
                "open",
                "true",
                "running",
                "active",
                "cool",
                "cooling",
                "heat",
                "heating",
                "dry",
                "fan_only",
                "auto"
            }

            if raw_state in inactive_states:
                return False
            if raw_state in active_states:
                return True

        return current_power > DEVICE_ACTIVE_POWER_THRESHOLD

    async def _async_update_data(self):
        results = {}
        if not self.devices_config:
            self.last_context = {
                "profile_lookback_days": PROFILE_LOOKBACK_DAYS,
                "configured_device_count": self.configured_device_count,
                "unique_device_count": self.unique_device_count
            }
            return results

        sorted_devices = sorted(self.devices_config.items(), key=lambda x: x[1]["priority"])
        first_config = sorted_devices[0][1]
        raw_forecast, forecast_context = self._get_pv_forecast(first_config["pv_forecast_sensor"])
        weather_stability = self._calculate_weather_stability(first_config["pv_forecast_sensor"])
        current_pv_power = self._get_float_state(first_config.get("pv_current_power_sensor"), 0.0)
        battery_soc = self._get_float_state(first_config.get("battery_soc_sensor"))
        battery_energy_kwh = self._get_float_state(first_config.get("battery_energy_sensor"), 0.0)
        battery_capacity_kwh = self._get_float_state(first_config.get("battery_capacity_sensor"))
        battery_min_soc = first_config.get("battery_min_soc", DEFAULT_BATTERY_MIN_SOC)
        night_consumption_sensor = first_config.get("night_consumption_sensor")
        schedule_start_time = first_config.get("schedule_start_time", DEFAULT_SCHEDULE_START_TIME)
        schedule_end_time = first_config.get("schedule_end_time", DEFAULT_SCHEDULE_END_TIME)
        schedule_start_offset, schedule_end_offset = self._calculate_schedule_window_offsets(
            schedule_start_time,
            schedule_end_time
        )
        battery_available_wh = self._calculate_available_battery_wh(
            battery_soc,
            battery_energy_kwh,
            battery_capacity_kwh,
            battery_min_soc
        )
        battery_charge_power = self._get_float_state(first_config.get("battery_charge_power_sensor"))
        battery_discharge_power = self._get_float_state(first_config.get("battery_discharge_power_sensor"))
        max_battery_budget_wh = self._calculate_battery_budget_ceiling_wh(
            battery_capacity_kwh,
            battery_min_soc,
            battery_available_wh
        )

        virtual_pv_forecast = self._build_virtual_pv_forecast(
            raw_forecast,
            weather_stability,
            current_pv_power
        )
        remaining_battery_wh = battery_available_wh
        self.last_context = {
            "pv_forecast_sensor": first_config.get("pv_forecast_sensor"),
            "home_base_load_sensor": first_config.get("home_base_load_sensor"),
            "pv_current_power_sensor": first_config.get("pv_current_power_sensor"),
            "battery_soc_sensor": first_config.get("battery_soc_sensor"),
            "battery_energy_sensor": first_config.get("battery_energy_sensor"),
            "battery_capacity_sensor": first_config.get("battery_capacity_sensor"),
            "pv_current_power": round(current_pv_power, 1),
            "battery_soc": round(battery_soc, 1) if battery_soc is not None else None,
            "battery_available_kwh": round(battery_available_wh / 1000, 2),
            "battery_capacity_kwh": round(battery_capacity_kwh, 2) if battery_capacity_kwh is not None else None,
            "battery_min_soc": battery_min_soc,
            "battery_charge_power": battery_charge_power,
            "battery_discharge_power": battery_discharge_power,
            "grid_import_energy_kwh": self._energy_wh_to_kwh(self._get_energy_state(first_config.get("grid_import_energy_sensor"))),
            "grid_export_energy_kwh": self._energy_wh_to_kwh(self._get_energy_state(first_config.get("grid_export_energy_sensor"))),
            "night_consumption_sensor": night_consumption_sensor,
            "schedule_start_time": schedule_start_time,
            "schedule_end_time": schedule_end_time,
            "profile_lookback_days": PROFILE_LOOKBACK_DAYS,
            "configured_device_count": self.configured_device_count,
            "unique_device_count": self.unique_device_count,
            **forecast_context
        }

        # 1. Basislast-Bereinigung: Wir ermitteln, wie viel der aktuellen Last auf bereits 
        # laufende, vom Scheduler gesteuerte Geräte entfällt.
        total_base_load = self._get_float_state(first_config.get("home_base_load_sensor"), 300.0)
        managed_running_power = 0.0
        for dev_id, device_config in self.devices_config.items():
            p = self._get_float_state(dev_id, 0.0)
            state_sensor_id = device_config.get("device_state_sensor")
            state_sensor_state = self.hass.states.get(state_sensor_id) if state_sensor_id else None
            if self._is_device_running(p, state_sensor_state):
                managed_running_power += p
        
        # Die "echte" Basislast ist der Hausverbrauch minus die gesteuerten Geräte.
        clean_base_load = max(0.0, total_base_load - managed_running_power)
        battery_trace = self._build_battery_trace(
            virtual_pv_forecast,
            clean_base_load,
            remaining_battery_wh,
            max_battery_budget_wh,
            battery_charge_power,
            battery_discharge_power
        )

        # Nachtverbrauchsschätzung (Grob: 12 Stunden Nacht * Basislast)
        night_usage_window_start = None
        night_usage_window_end = None
        configured_night_usage_wh, night_usage_source, night_usage_window = await self._get_night_usage_wh(
            night_consumption_sensor,
            schedule_start_time,
            schedule_end_time
        )
        if configured_night_usage_wh is not None:
            night_usage_wh = configured_night_usage_wh
            if night_usage_window:
                night_usage_window_start = night_usage_window[0].isoformat()
                night_usage_window_end = night_usage_window[1].isoformat()
        else:
            night_usage_wh = clean_base_load * DEFAULT_NIGHT_HOURS
            night_usage_source = "current_base_load_fallback"

        self.last_context["night_usage_estimate_wh"] = round(night_usage_wh, 1)
        self.last_context["night_usage_source"] = night_usage_source
        self.last_context["night_usage_window_start"] = night_usage_window_start
        self.last_context["night_usage_window_end"] = night_usage_window_end
        battery_night_warning, battery_night_reason = self._calculate_battery_night_warning(
            battery_soc,
            battery_energy_kwh,
            battery_capacity_kwh,
            battery_available_wh,
            night_usage_wh,
            battery_min_soc
        )
        self.last_context["battery_night_warning"] = battery_night_warning
        self.last_context["battery_night_reason"] = battery_night_reason

        for entity_id, config in sorted_devices:
            try:
                profile = await self._get_adaptive_profile(entity_id)
                state = self.hass.states.get(entity_id)
                current_device_power = self._parse_state_value(state) or 0.0
                device_state_sensor = config.get("device_state_sensor")
                state_sensor_state = self.hass.states.get(device_state_sensor) if device_state_sensor else None
                is_running = self._is_device_running(
                    current_device_power,
                    state_sensor_state
                )

                best_start, max_coverage, battery_used_wh = self._calculate_best_window(
                    profile,
                    virtual_pv_forecast,
                    clean_base_load,
                    remaining_battery_wh,
                    battery_trace,
                    battery_charge_power,
                    battery_discharge_power,
                    max_battery_budget_wh,
                    config.get("target_coverage", 90),
                    schedule_start_offset,
                    schedule_end_offset
                )

                if is_running:
                    best_start = 0
                    max_coverage, battery_used_wh = self._calculate_window_coverage(
                        profile,
                        virtual_pv_forecast,
                        clean_base_load,
                        remaining_battery_wh,
                        battery_trace,
                        battery_charge_power,
                        battery_discharge_power,
                        max_battery_budget_wh,
                        best_start
                    )

                # Berechne konkrete Uhrzeit
                start_time = dt_util.now() + timedelta(minutes=best_start)

                recommendation = "läuft" if is_running else ("ja" if max_coverage >= config["target_coverage"] and best_start == 0 else "warten")
                total_kwh = (sum(profile) / 60) / 1000 if profile else 0
                duration_mins = len(profile) if profile else 0

                results[entity_id] = {
                    "recommendation": recommendation,
                    "is_running": is_running,
                    "current_power": round(current_device_power, 1),
                    "power_state": state.state if state else None,
                    "power_unit": state.attributes.get("unit_of_measurement") if state else None,
                    "power_last_updated": state.last_updated.isoformat() if state else None,
                    "device_state_sensor": device_state_sensor,
                    "device_state": state_sensor_state.state if state_sensor_state else None,
                    "device_state_last_updated": state_sensor_state.last_updated.isoformat() if state_sensor_state else None,
                    "best_start_mins": best_start,
                    "coverage_percent": round(max_coverage, 1),
                    "total_kwh": round(total_kwh, 2),
                    "battery_used_kwh": round(battery_used_wh / 1000, 2),
                    "duration_mins": duration_mins,
                    "best_start_time": start_time.isoformat(),
                    "weather_stability": round(weather_stability * 100, 0),
                    "priority": config["priority"],
                    "target_coverage": config.get("target_coverage", 90)
                }

                # Reserve higher-priority devices at their actual planned offset.
                reservation_start = 0 if is_running else best_start
                if profile and reservation_start is not None:
                    self._reserve_forecast_window(
                        virtual_pv_forecast,
                        profile,
                        clean_base_load,
                        reservation_start
                    )
                    remaining_battery_wh = max(0.0, remaining_battery_wh - battery_used_wh)
                    battery_trace = self._build_battery_trace(
                        virtual_pv_forecast,
                        clean_base_load,
                        remaining_battery_wh,
                        max_battery_budget_wh,
                        battery_charge_power,
                        battery_discharge_power
                    )

            except Exception as err:
                _LOGGER.error(f"Fehler bei Berechnung für {entity_id}: {err}")
                results[entity_id] = {"recommendation": "warten", "is_running": False, "current_power": 0.0, "best_start_mins": 0, "coverage_percent": 0, "total_kwh": 0, "duration_mins": 0, "weather_stability": 80, "priority": config["priority"], "target_coverage": config.get("target_coverage", 90), "best_start_time": None}
                
        return results

    def _calculate_weather_stability(self, forecast_sensor_id) -> float:
        state = self.hass.states.get(forecast_sensor_id)
        if not state or state.state in ("unknown", "unavailable"):
            return 0.85

        unit = state.attributes.get("unit_of_measurement")
        if unit and unit.lower() in ("kwh", "kw h"):
            try:
                estimate = float(state.attributes.get("estimate", state.state))
                estimate10 = float(state.attributes.get("estimate10", estimate))
                if estimate > 0:
                    return max(0.5, min(1.0, estimate10 / estimate))
            except (TypeError, ValueError):
                return 0.9

            return 0.9

        try:
            val = float(state.state)
            return 0.75 if val < 500 else (0.88 if val < 1500 else 0.95)
        except ValueError:
            return 0.85

    async def _get_adaptive_profile(self, entity_id):
        """Erstellt ein zeitlich korrektes 1-Minuten-Leistungsprofil aus der Historie."""
        now = dt_util.utcnow()
        cached_profile = self.learned_profiles.get(entity_id)
        normalized_cached_profile = self._normalize_profile(cached_profile) if cached_profile is not None else None
        if cached_profile is not None and normalized_cached_profile is None:
            self.learned_profiles.pop(entity_id, None)
            await self.hass.async_add_executor_job(self.save_learned_profiles)
            cached_profile = None
        
        # Throttling: Historie nur einmal pro Stunde abfragen oder wenn Profil fehlt
        last_check = self._profile_query_timestamps.get(entity_id, dt_util.utc_from_timestamp(0))
        if normalized_cached_profile is not None and (now - last_check).total_seconds() < 3600:
            return normalized_cached_profile

        self._profile_query_timestamps[entity_id] = now

        now = dt_util.utcnow()
        history_dict = await self.hass.async_add_executor_job(
            history.get_significant_states, self.hass, now - timedelta(days=PROFILE_LOOKBACK_DAYS), now, [entity_id]
        )

        default_profile = [300] * 120
        states = history_dict.get(entity_id, [])
        if not states:
            return default_profile

        # 1. Finde den letzten BEENDETEN Zyklus (Übergang von Aktiv zu Inaktiv)
        # Wir gehen von hinten nach vorne durch die Historie
        last_active_idx = -1
        for i in range(len(states) - 2, -1, -1):
            val_current = self._parse_state_value(states[i])
            val_next = self._parse_state_value(states[i+1])
            
            if val_current is not None and val_current > DEVICE_ACTIVE_POWER_THRESHOLD:
                if val_next is not None and val_next <= DEVICE_ACTIVE_POWER_THRESHOLD:
                    last_active_idx = i
                    break

        if last_active_idx == -1:
            return normalized_cached_profile or default_profile

        # 2. Finde den Start dieses aktiven Zyklus (gehe zurück bis eine Lücke > 20 Min auftritt)
        start_active_idx = last_active_idx
        for i in range(last_active_idx, 0, -1):
            try:
                diff = (states[i].last_changed - states[i-1].last_changed).total_seconds()
                if diff > 1200: # 20 Minuten Inaktivität beenden die Phase
                    break
                start_active_idx = i - 1
            except (ValueError, TypeError):
                continue

        # 3. Resampling auf 1-Minuten-Intervalle
        start_dt = states[start_active_idx].last_changed
        end_dt = states[last_active_idx].last_changed
        duration_mins = int((end_dt - start_dt).total_seconds() / 60)

        if duration_mins < 10: # Zu kurze Phasen ignorieren
            return default_profile

        duration_mins = min(duration_mins, 360) # Max 6 Stunden
        resampled_profile = []
        current_state_ptr = start_active_idx

        for m in range(duration_mins + 1):
            check_time = start_dt + timedelta(minutes=m)
            while (current_state_ptr + 1 <= last_active_idx and 
                   states[current_state_ptr + 1].last_changed <= check_time):
                current_state_ptr += 1
            
            raw_val = self._parse_state_value(states[current_state_ptr])
            # Noise-Filter: Werte unter dem Schwellenwert werden als 0W gewertet,
            # um Standby-Rauschen nicht in das Lernprofil zu übernehmen.
            clean_val = raw_val if raw_val is not None else 0.0
            if clean_val < DEVICE_ACTIVE_POWER_THRESHOLD:
                clean_val = 0.0
            resampled_profile.append(clean_val)

        # Qualitäts-Check: Nur speichern, wenn das Profil lang genug ist 
        # UND eine Mindestmenge an Energie (Wh) enthält (verhindert Standby-Lernen)
        total_energy_wh = (sum(resampled_profile) / 60)
        normalized_profile = self._normalize_profile(resampled_profile)
        if normalized_profile is not None:
            self.learned_profiles[entity_id] = normalized_profile
            await self.hass.async_add_executor_job(self.save_learned_profiles)
            return normalized_profile

        return normalized_cached_profile or default_profile

    def _get_pv_forecast(self, forecast_sensor_id):
        state = self.hass.states.get(forecast_sensor_id)
        context = {
            "forecast_source_unit": None,
            "forecast_remaining_kwh": None,
            "forecast_average_power": None
        }

        if not state or state.state in ("unknown", "unavailable"):
            return [1200.0] * FORECAST_HORIZON_MINUTES, context

        unit = state.attributes.get("unit_of_measurement")
        context["forecast_source_unit"] = unit

        detailed_forecast = state.attributes.get("detailedForecast")
        if isinstance(detailed_forecast, list):
            forecast = self._forecast_from_detailed_intervals(detailed_forecast)
            if forecast:
                context["forecast_average_power"] = round(sum(forecast) / len(forecast), 1)
                try:
                    context["forecast_remaining_kwh"] = round(float(state.attributes.get("estimate", state.state)), 3)
                except (TypeError, ValueError):
                    context["forecast_remaining_kwh"] = None
                return forecast, context

        try:
            forecast_value = float(state.attributes.get("estimate", state.state))
        except (TypeError, ValueError):
            forecast_value = 1200.0

        if unit and unit.lower() in ("kwh", "kw h"):
            remaining_minutes = self._remaining_daylight_minutes()
            average_power = (forecast_value * 1000) / (remaining_minutes / 60)
            context["forecast_remaining_kwh"] = round(forecast_value, 3)
            context["forecast_average_power"] = round(average_power, 1)
            return [max(0.0, average_power) for _ in range(FORECAST_HORIZON_MINUTES)], context

        context["forecast_average_power"] = round(forecast_value, 1)
        # Weniger aggressiver Abfall für den Fallback-Forecast
        return [max(0, forecast_value - (i * 1.5)) for i in range(FORECAST_HORIZON_MINUTES)], context

    def _forecast_from_detailed_intervals(self, intervals):
        """Builds a 1-minute W forecast from Solcast-style kWh intervals."""
        now = dt_util.now()
        horizon_end = now + timedelta(minutes=FORECAST_HORIZON_MINUTES)
        parsed = []

        for item in intervals:
            if not isinstance(item, dict):
                continue

            start = dt_util.parse_datetime(str(item.get("period_start")))
            if start is None:
                continue
            if start.tzinfo is None:
                start = dt_util.as_local(start)

            try:
                estimate_kwh = float(item.get("pv_estimate", 0.0))
            except (TypeError, ValueError):
                estimate_kwh = 0.0

            parsed.append((start, estimate_kwh))

        parsed.sort(key=lambda value: value[0])
        if len(parsed) < 2:
            return None

        forecast = [0.0] * FORECAST_HORIZON_MINUTES
        for index, (start, estimate_kwh) in enumerate(parsed):
            next_start = parsed[index + 1][0] if index + 1 < len(parsed) else start + timedelta(minutes=30)
            interval_minutes = max(1, int((next_start - start).total_seconds() / 60))
            average_power = max(0.0, estimate_kwh * 1000.0 / (interval_minutes / 60.0))

            overlap_start = max(start, now)
            overlap_end = min(next_start, horizon_end)
            if overlap_end <= overlap_start:
                continue

            start_offset = max(0, int((overlap_start - now).total_seconds() / 60))
            end_offset = min(FORECAST_HORIZON_MINUTES, int((overlap_end - now).total_seconds() / 60))
            for minute in range(start_offset, end_offset):
                forecast[minute] = average_power

        return forecast

    def _remaining_daylight_minutes(self):
        now = dt_util.now()
        end_of_day = now.replace(hour=21, minute=0, second=0, microsecond=0)

        if now >= end_of_day:
            return 60

        return max(60, min(720, int((end_of_day - now).total_seconds() / 60)))

    def _get_float_state(self, entity_id, fallback=None):
        if not entity_id:
            return fallback

        state = self.hass.states.get(entity_id)
        val = self._parse_state_value(state)
        return val if val is not None else fallback

    def _get_energy_state(self, entity_id):
        """Reads an energy sensor and returns Wh."""
        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        return self._energy_state_to_wh(state)

    def _energy_wh_to_kwh(self, value_wh):
        if value_wh is None:
            return None

        return round(value_wh / 1000.0, 3)

    def _energy_state_to_wh(self, state):
        val = self._parse_state_value(state)
        if val is None:
            return None

        unit = (state.attributes.get("unit_of_measurement") or "").strip().lower()
        if unit in ("wh", "w h"):
            return val
        if unit in ("mwh", "mw h"):
            return val * 1000000.0

        return val * 1000.0

    async def _get_night_usage_wh(self, entity_id, schedule_start_time, schedule_end_time):
        """Returns the last completed night consumption in Wh."""
        if not entity_id:
            return None, None, None

        state = self.hass.states.get(entity_id)
        current_energy_wh = self._energy_state_to_wh(state)
        if current_energy_wh is None:
            return None, None, None

        is_cumulative = self._is_cumulative_energy_sensor(state, current_energy_wh)
        if not is_cumulative:
            return current_energy_wh, "configured_night_consumption_sensor", None

        night_start, night_end = self._last_completed_night_window(
            schedule_start_time,
            schedule_end_time
        )
        history_dict = await self.hass.async_add_executor_job(
            history.get_significant_states,
            self.hass,
            dt_util.as_utc(night_start),
            dt_util.as_utc(night_end),
            [entity_id]
        )
        states = history_dict.get(entity_id, [])
        values = [
            self._energy_state_to_wh(history_state)
            for history_state in states
        ]
        values = [value for value in values if value is not None]

        if len(values) < 2:
            return None, None, None

        usage_wh = self._calculate_cumulative_delta_wh(values)
        if usage_wh <= 0:
            return None, None, None

        return usage_wh, "history_delta_night_consumption_sensor", (night_start, night_end)

    def _is_cumulative_energy_sensor(self, state, energy_wh):
        if not state:
            return False

        state_class = (state.attributes.get("state_class") or "").lower()
        if state_class in ("total", "total_increasing"):
            return True

        return energy_wh > 100000.0

    def _last_completed_night_window(self, schedule_start_time, schedule_end_time):
        now = dt_util.now()
        start_minutes = self._parse_time_minutes(schedule_start_time, DEFAULT_SCHEDULE_START_TIME)
        end_minutes = self._parse_time_minutes(schedule_end_time, DEFAULT_SCHEDULE_END_TIME)
        night_end = now.replace(
            hour=start_minutes // 60,
            minute=start_minutes % 60,
            second=0,
            microsecond=0
        )

        if now < night_end:
            night_end = night_end - timedelta(days=1)

        night_start = (night_end - timedelta(days=1)).replace(
            hour=end_minutes // 60,
            minute=end_minutes % 60,
            second=0,
            microsecond=0
        )

        if end_minutes < start_minutes:
            night_start = night_end.replace(
                hour=end_minutes // 60,
                minute=end_minutes % 60,
                second=0,
                microsecond=0
            )

        return night_start, night_end

    def _calculate_cumulative_delta_wh(self, values):
        if values[-1] >= values[0]:
            return values[-1] - values[0]

        usage_wh = 0.0
        previous = values[0]
        for value in values[1:]:
            if value >= previous:
                usage_wh += value - previous
            previous = value

        return usage_wh

    def _parse_time_minutes(self, value, fallback):
        if not value:
            value = fallback

        if hasattr(value, "hour") and hasattr(value, "minute"):
            return (int(value.hour) * 60) + int(value.minute)

        try:
            parts = str(value).split(":")
            hour = max(0, min(23, int(parts[0])))
            minute = max(0, min(59, int(parts[1]) if len(parts) > 1 else 0))
            return (hour * 60) + minute
        except (TypeError, ValueError, IndexError):
            fallback_hour, fallback_minute = fallback.split(":", 1)
            return (int(fallback_hour) * 60) + int(fallback_minute)

    def _calculate_schedule_window_offsets(self, start_time, end_time):
        """Returns allowed start offsets in minutes relative to now."""
        now = dt_util.now()
        now_minutes = (now.hour * 60) + now.minute
        start_minutes = self._parse_time_minutes(start_time, DEFAULT_SCHEDULE_START_TIME)
        end_minutes = self._parse_time_minutes(end_time, DEFAULT_SCHEDULE_END_TIME)

        if start_minutes == end_minutes:
            return 0, FORECAST_HORIZON_MINUTES

        if start_minutes < end_minutes:
            if now_minutes < start_minutes:
                return start_minutes - now_minutes, end_minutes - now_minutes
            if now_minutes <= end_minutes:
                return 0, end_minutes - now_minutes
            return (1440 - now_minutes) + start_minutes, (1440 - now_minutes) + end_minutes

        if now_minutes >= start_minutes:
            return 0, (1440 - now_minutes) + end_minutes
        if now_minutes <= end_minutes:
            return 0, end_minutes - now_minutes
        return start_minutes - now_minutes, (1440 - now_minutes) + end_minutes

    def _calculate_available_battery_wh(self, battery_soc, battery_energy_kwh, battery_capacity_kwh, min_soc):
        """Berechnet die tatsächlich nutzbare Energie oberhalb des Mindest-SoC."""
        if battery_soc is None or battery_soc <= min_soc or battery_soc <= 0:
            return 0.0

        try:
            # Berechnung der Gesamtkapazität basierend auf aktuellem Stand und SoC.
            # Wenn z.B. 5kWh bei 50% SoC im Speicher sind, beträgt die Gesamtkapazität 10kWh.
            if battery_capacity_kwh and battery_capacity_kwh > 0:
                total_capacity = battery_capacity_kwh
                battery_energy_kwh = total_capacity * (battery_soc / 100.0)
            elif battery_energy_kwh and battery_energy_kwh > 0:
                # Fallback: der alte Sensor wird als aktuell gespeicherte Energie interpretiert.
                total_capacity = battery_energy_kwh / (battery_soc / 100.0)
            else:
                return 0.0
            # Die Energie, die dem Mindest-SoC entspricht, ist nicht für den Scheduler verfügbar.
            min_energy_limit = total_capacity * (min_soc / 100.0)
            usable_kwh = max(0.0, battery_energy_kwh - min_energy_limit)
            return usable_kwh * 1000.0
        except (ZeroDivisionError, TypeError, ValueError):
            return 0.0

    def _calculate_battery_night_warning(
        self,
        battery_soc,
        battery_energy_kwh,
        battery_capacity_kwh,
        battery_available_wh,
        night_usage_wh,
        min_soc
    ):
        """Warnt nur sicher, wenn genug Batteriedaten für eine belastbare Bewertung vorliegen."""
        if battery_soc is None:
            return False, "Kein Batterie-SoC konfiguriert"

        if (battery_capacity_kwh and battery_capacity_kwh > 0) or (battery_energy_kwh and battery_energy_kwh > 0):
            if battery_available_wh < night_usage_wh:
                return True, "Nutzbare Batterieenergie reicht rechnerisch nicht für die Nacht"
            return False, "Nutzbare Batterieenergie reicht rechnerisch für die Nacht"

        # Ohne kWh-Sensor kann die Nachtreichweite nicht berechnet werden.
        # Dann nur bei wirklich niedrigem SoC warnen, statt pauschal "knapp" zu melden.
        fallback_threshold = max(40, min_soc + 10)
        if battery_soc < fallback_threshold:
            return True, "Kein kWh-Sensor vorhanden und SoC unter Reserve-Schwelle"

        return False, "Kein kWh-Sensor vorhanden, SoC ist ausreichend hoch"

    def _build_virtual_pv_forecast(self, raw_forecast, weather_stability, current_pv_power):
        forecast = [watt * weather_stability for watt in raw_forecast]

        if current_pv_power <= 0:
            return forecast

        for minute in range(min(90, len(forecast))):
            current_pv_estimate = max(0.0, current_pv_power - (minute * 8))
            forecast[minute] = max(forecast[minute], current_pv_estimate)

        return forecast

    def _calculate_battery_budget_ceiling_wh(self, battery_capacity_kwh, min_soc, fallback_wh):
        if battery_capacity_kwh and battery_capacity_kwh > 0:
            usable_fraction = max(0.0, (100.0 - float(min_soc)) / 100.0)
            return battery_capacity_kwh * 1000.0 * usable_fraction
        return max(0.0, float(fallback_wh or 0.0))

    def _build_battery_trace(
        self,
        forecast,
        base_load,
        initial_available_wh,
        max_available_wh,
        charge_power_w,
        discharge_power_w
    ):
        """Simulates baseline battery state over the forecast horizon."""
        if not forecast:
            return [max(0.0, float(initial_available_wh or 0.0))]

        battery_wh = max(0.0, min(float(initial_available_wh or 0.0), float(max_available_wh or 0.0)))
        max_budget_wh = max(0.0, float(max_available_wh or 0.0))
        charge_limit = None if charge_power_w is None or charge_power_w <= 0 else float(charge_power_w)
        discharge_limit = None if discharge_power_w is None or discharge_power_w <= 0 else float(discharge_power_w)
        trace = [battery_wh]

        for forecast_power in forecast:
            net_power = float(forecast_power) - float(base_load)
            if net_power >= 0:
                charge_w = net_power if charge_limit is None else min(net_power, charge_limit)
                battery_wh = min(max_budget_wh, battery_wh + (charge_w / 60.0))
            else:
                discharge_need_w = abs(net_power)
                discharge_w = discharge_need_w if discharge_limit is None else min(discharge_need_w, discharge_limit)
                discharge_w = min(discharge_w, battery_wh * 60.0)
                battery_wh = max(0.0, battery_wh - (discharge_w / 60.0))
            trace.append(battery_wh)

        return trace

    def _reserve_forecast_window(self, forecast, profile, base_load, start_offset):
        """Reserves only the PV share actually consumed by a higher-priority device."""
        try:
            start = max(0, int(start_offset))
        except (TypeError, ValueError):
            start = 0

        if start >= len(forecast):
            return

        for minute, device_power in enumerate(profile):
            forecast_index = start + minute
            if forecast_index >= len(forecast):
                break
            available_excess = max(0.0, forecast[forecast_index] - base_load)
            pv_reserved = min(float(device_power), available_excess)
            forecast[forecast_index] = max(0.0, forecast[forecast_index] - pv_reserved)

    def _calculate_window_coverage(
        self,
        profile,
        forecast,
        base_load,
        battery_available_wh,
        battery_trace,
        battery_charge_power_w,
        battery_discharge_power_w,
        max_battery_budget_wh,
        start_min
    ):
        """Calculates PV and battery coverage for one concrete start offset."""
        if not profile or not forecast:
            return 0.0, 0.0

        try:
            start = max(0, int(start_min))
        except (TypeError, ValueError):
            start = 0

        if start >= len(forecast):
            return 0.0, 0.0

        if battery_trace and start < len(battery_trace):
            battery_wh = max(0.0, battery_trace[start])
        else:
            battery_wh = max(0.0, float(battery_available_wh or 0.0))

        total_device_energy = 0.0
        covered_by_pv_energy = 0.0
        covered_by_battery_energy = 0.0
        charge_limit = None if battery_charge_power_w is None or battery_charge_power_w <= 0 else float(battery_charge_power_w)
        discharge_limit = None if battery_discharge_power_w is None or battery_discharge_power_w <= 0 else float(battery_discharge_power_w)
        max_budget_wh = max(0.0, float(max_battery_budget_wh or battery_wh))

        for minute, device_power in enumerate(profile):
            forecast_index = start + minute
            if forecast_index >= len(forecast):
                break

            device_power = float(device_power)
            forecast_power = float(forecast[forecast_index])
            available_excess = max(0.0, forecast_power - base_load)
            total_device_energy += device_power
            pv_covered_now = min(device_power, available_excess)
            covered_by_pv_energy += pv_covered_now

            remaining_device_power = max(0.0, device_power - pv_covered_now)
            discharge_w = remaining_device_power if discharge_limit is None else min(remaining_device_power, discharge_limit)
            discharge_w = min(discharge_w, battery_wh * 60.0)
            covered_by_battery_energy += discharge_w
            battery_wh = max(0.0, battery_wh - (discharge_w / 60.0))

            surplus_after_device = max(0.0, forecast_power - base_load - device_power)
            charge_w = surplus_after_device if charge_limit is None else min(surplus_after_device, charge_limit)
            if charge_w > 0:
                battery_wh = min(max_budget_wh, battery_wh + (charge_w / 60.0))

        covered_energy = covered_by_pv_energy + covered_by_battery_energy
        coverage_percent = (covered_energy / total_device_energy) * 100 if total_device_energy > 0 else 0.0

        return coverage_percent, covered_by_battery_energy / 60.0

    def _calculate_best_window(
        self,
        profile,
        forecast,
        base_load,
        battery_available_wh=0.0,
        battery_trace=None,
        battery_charge_power_w=None,
        battery_discharge_power_w=None,
        max_battery_budget_wh=0.0,
        target_coverage=90.0,
        earliest_start_offset=0,
        latest_start_offset=FORECAST_HORIZON_MINUTES
    ):
        """Findet das optimale Zeitfenster unter Berücksichtigung der Zielabdeckung."""
        profile_len = len(profile)
        forecast_len = len(forecast)
        if profile_len >= forecast_len:
            return 0, 0.0, 0.0
        
        windows = []
        latest_start = min(forecast_len - profile_len, max(0, int(latest_start_offset)))
        earliest_start = max(0, min(int(earliest_start_offset), latest_start))
        first_start = ((earliest_start + 14) // 15) * 15
        candidate_starts = []
        if earliest_start <= latest_start:
            candidate_starts.append(earliest_start)
        if first_start == earliest_start:
            candidate_starts = []
        candidate_starts.extend(range(first_start, latest_start + 1, 15))

        for start_min in candidate_starts:
            coverage_percent, battery_used_wh = self._calculate_window_coverage(
                profile,
                forecast,
                base_load,
                battery_available_wh,
                battery_trace,
                battery_charge_power_w,
                battery_discharge_power_w,
                max_battery_budget_wh,
                start_min
            )
            absolute_pv_sum = sum(forecast[start_min:start_min + profile_len])
            
            windows.append({
                "start": start_min,
                "coverage": coverage_percent,
                "battery_wh": battery_used_wh,
                "absolute_pv": absolute_pv_sum
            })

        # 1. Falls keine Fenster berechnet werden konnten
        if not windows:
            return earliest_start, 0.0, 0.0

        # 2. Wenn das aktuelle Fenster (t=0) bereits die Zielabdeckung erreicht -> Sofort starten
        if windows[0]["start"] == 0 and windows[0]["coverage"] >= target_coverage:
            return 0, windows[0]["coverage"], windows[0]["battery_wh"]

        # 2. Das erste Fenster finden, das die Zielabdeckung erreicht
        for w in windows:
            if w["coverage"] >= target_coverage:
                return w["start"], w["coverage"], w["battery_wh"]

        # 3. Sonst: Das Fenster mit der maximalen Abdeckung wählen. 
        # Wir gewichten die Abdeckung am höchsten, aber bei Gleichstand (oder geringer Deckung) 
        # nehmen wir das Fenster mit der absolut höchsten PV-Leistungssumme (Peak-Suche).
        best_w = max(windows, key=lambda x: (x["coverage"], x["absolute_pv"], -x["start"]))

        return best_w["start"], best_w["coverage"], best_w["battery_wh"]
