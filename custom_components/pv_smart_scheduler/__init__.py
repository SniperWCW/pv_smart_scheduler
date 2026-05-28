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
DEVICE_ACTIVE_POWER_THRESHOLD = 15
FORECAST_HORIZON_MINUTES = 240

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
        self.configured_device_count = configured_device_count
        self.unique_device_count = len(new_config)
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

        # 1. Prüfe Attribute (oft präziser oder enthält die Zahl, wenn State "on/off" ist)
        for attr in ("current_power_w", "power", "load", "current_consumption", "power_consumption", "watt", "watts", "current_power"):
            val = state.attributes.get(attr)
            if val is not None:
                parsed = self._clean_numeric_string(str(val))
                if parsed is not None:
                    return parsed

        try:
            # 2. Haupt-Status parsen
            val = self._clean_numeric_string(state.state)
            if val is None:
                return None
                
            unit = state.attributes.get("unit_of_measurement")
            if unit and unit.strip().lower() == "kw":
                val *= 1000.0
            return val
        except (TypeError, ValueError, IndexError):
            return None

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
            "profile_lookback_days": PROFILE_LOOKBACK_DAYS,
            "configured_device_count": self.configured_device_count,
            "unique_device_count": self.unique_device_count,
            **forecast_context
        }

        # 1. Basislast-Bereinigung: Wir ermitteln, wie viel der aktuellen Last auf bereits 
        # laufende, vom Scheduler gesteuerte Geräte entfällt.
        total_base_load = self._get_float_state(first_config.get("home_base_load_sensor"), 300.0)
        managed_running_power = 0.0
        for dev_id in self.devices_config:
            p = self._get_float_state(dev_id, 0.0)
            if p > DEVICE_ACTIVE_POWER_THRESHOLD:
                managed_running_power += p
        
        # Die "echte" Basislast ist der Hausverbrauch minus die gesteuerten Geräte.
        clean_base_load = max(0.0, total_base_load - managed_running_power)

        for entity_id, config in sorted_devices:
            try:
                profile = await self._get_adaptive_profile(entity_id)
                state = self.hass.states.get(entity_id)
                current_device_power = self._parse_state_value(state) or 0.0
                is_running = current_device_power > DEVICE_ACTIVE_POWER_THRESHOLD

                best_start, max_coverage, battery_used_wh = self._calculate_best_window(
                    profile, virtual_pv_forecast, clean_base_load, remaining_battery_wh, config.get("target_coverage", 90)
                )

                # Berechne konkrete Uhrzeit
                start_time = dt_util.now() + timedelta(minutes=best_start)

                recommendation = "läuft" if is_running else ("ja" if max_coverage >= config["target_coverage"] and best_start == 0 else "warten")
                total_kwh = (sum(profile) / 60) / 1000 if profile else 0

                results[entity_id] = {
                    "recommendation": recommendation,
                    "is_running": is_running,
                    "current_power": round(current_device_power, 1),
                    "best_start_mins": best_start,
                    "coverage_percent": round(max_coverage, 1),
                    "total_kwh": round(total_kwh, 2),
                    "battery_used_kwh": round(battery_used_wh / 1000, 2),
                    "best_start_time": start_time.isoformat(),
                    "weather_stability": round(weather_stability * 100, 0),
                    "priority": config["priority"]
                }

                # Reserviere PV-Leistung und Batterie für dieses Gerät, wenn es läuft oder jetzt starten soll
                if is_running or (recommendation == "ja" and best_start == 0):
                    profile_len = len(profile)
                    for i in range(min(profile_len, len(virtual_pv_forecast))):
                        virtual_pv_forecast[i] = max(0.0, virtual_pv_forecast[i] - profile[i])
                    remaining_battery_wh = max(0.0, remaining_battery_wh - battery_used_wh)

            except Exception as err:
                _LOGGER.error(f"Fehler bei Berechnung für {entity_id}: {err}")
                results[entity_id] = {"recommendation": "warten", "best_start_mins": 0, "coverage_percent": 0, "total_kwh": 0, "weather_stability": 80, "priority": config["priority"], "best_start_time": None}
                
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
        
        # Throttling: Historie nur einmal pro Stunde abfragen oder wenn Profil fehlt
        last_check = self._profile_query_timestamps.get(entity_id, dt_util.utc_from_timestamp(0))
        if entity_id in self.learned_profiles and (now - last_check).total_seconds() < 3600:
            return self.learned_profiles[entity_id]

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
            return self.learned_profiles.get(entity_id, default_profile)

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
            
            val = self._parse_state_value(states[current_state_ptr])
            resampled_profile.append(val if val is not None else 0.0)

        if len(resampled_profile) > 10:
            self.learned_profiles[entity_id] = resampled_profile
            await self.hass.async_add_executor_job(self.save_learned_profiles)
            return resampled_profile

        return self.learned_profiles.get(entity_id, default_profile)

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
        return [max(0, forecast_value - (i * 3)) for i in range(FORECAST_HORIZON_MINUTES)], context

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

    def _calculate_available_battery_wh(self, battery_soc, battery_energy_kwh, min_soc):
        """Berechnet die tatsächlich nutzbare Energie oberhalb des Mindest-SoC."""
        if battery_soc is None or battery_soc <= min_soc or battery_soc <= 0 or battery_energy_kwh <= 0:
            return 0.0

        try:
            # Berechnung der Gesamtkapazität basierend auf aktuellem Stand und SoC.
            # Wenn z.B. 5kWh bei 50% SoC im Speicher sind, beträgt die Gesamtkapazität 10kWh.
            total_capacity = battery_energy_kwh / (battery_soc / 100.0)
            # Die Energie, die dem Mindest-SoC entspricht, ist nicht für den Scheduler verfügbar.
            min_energy_limit = total_capacity * (min_soc / 100.0)
            usable_kwh = max(0.0, battery_energy_kwh - min_energy_limit)
            return usable_kwh * 1000.0
        except (ZeroDivisionError, TypeError, ValueError):
            return 0.0

    def _build_virtual_pv_forecast(self, raw_forecast, weather_stability, current_pv_power):
        forecast = [watt * weather_stability for watt in raw_forecast]

        if current_pv_power <= 0:
            return forecast

        for minute in range(min(90, len(forecast))):
            current_pv_estimate = max(0.0, current_pv_power - (minute * 8))
            forecast[minute] = max(forecast[minute], current_pv_estimate)

        return forecast

    def _calculate_best_window(self, profile, forecast, base_load, battery_available_wh=0.0, target_coverage=90.0):
        """Findet das optimale Zeitfenster unter Berücksichtigung der Zielabdeckung."""
        profile_len = len(profile)
        forecast_len = len(forecast)
        if profile_len >= forecast_len:
            return 0, 0.0, 0.0
        
        windows = []
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
            
            windows.append({
                "start": start_min,
                "coverage": coverage_percent,
                "battery_wh": covered_by_battery_energy / 60
            })

        if not windows:
            return 0, 0.0, 0.0

        # 1. Wenn das aktuelle Fenster (t=0) bereits die Zielabdeckung erreicht -> Sofort starten
        if windows[0]["coverage"] >= target_coverage:
            return 0, windows[0]["coverage"], windows[0]["battery_wh"]

        # 2. Das erste Fenster finden, das die Zielabdeckung erreicht
        for w in windows:
            if w["coverage"] >= target_coverage:
                return w["start"], w["coverage"], w["battery_wh"]

        # 3. Sonst: Das Fenster mit der maximalen Abdeckung wählen
        best_w = max(windows, key=lambda x: x["coverage"])
        return best_w["start"], best_w["coverage"], best_w["battery_wh"]
