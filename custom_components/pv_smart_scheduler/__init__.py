import logging
import json
import os
import math
import statistics
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.recorder import history
from homeassistant.util import dt as dt_util
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PROFILE_LOOKBACK_DAYS = 14
PROFILE_SAMPLE_LIMIT = 5
# Ohne Statussensor gehört eine Pause bis zu dieser Länge noch zum selben Lauf
# (Waschmaschinen und Geschirrspüler pausieren zwischen den Heizphasen).
PROFILE_QUIET_MINUTES = 60
# So lange wird der letzte gültige Wert bei unavailable/unknown fortgeschrieben.
PROFILE_DROPOUT_MINUTES = 10
PROFILE_MAX_MINUTES = 360
PROFILE_MIN_MINUTES = 10
INACTIVE_STATE_VALUES = frozenset({
    "off", "idle", "standby", "unavailable", "unknown", "0", "false", "closed"
})
ACTIVE_STATE_VALUES = frozenset({
    "on", "open", "true", "running", "active", "cool", "cooling", "heat",
    "heating", "dry", "fan_only", "auto"
})
DEFAULT_BATTERY_MIN_SOC = 25
DEVICE_ACTIVE_POWER_THRESHOLD = 15
# 36 Stunden: genug, um abends auch den morgigen Vormittag einzuplanen.
FORECAST_HORIZON_MINUTES = 2160
NO_PV_WINDOW_COVERAGE = 5.0
DEFAULT_SCHEDULE_START_TIME = "05:00"
DEFAULT_SCHEDULE_END_TIME = "23:00"
DEFAULT_NIGHT_HOURS = 12
DEFAULT_SUNRISE_MINUTES = 7 * 60
DEFAULT_SUNSET_MINUTES = 21 * 60
MAX_PROFILE_POWER_W = 25000
MAX_PROFILE_ENERGY_WH = 50000
ACTIVE_STATE_SENSOR_GRACE_MINUTES = 90
CARD_MODULE_FILENAME = "pv-smart-scheduler-card.js"
INTEGRATION_VERSION = "0.4.4"
CARD_RESOURCE_BASE_URL = f"/{DOMAIN}/{CARD_MODULE_FILENAME}"
CARD_RESOURCE_URL = f"{CARD_RESOURCE_BASE_URL}?v={INTEGRATION_VERSION}"

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

    async def _register_card_resource(_event):
        await async_ensure_card_resource(hass)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_card_resource)

    return True


async def async_ensure_card_resource(hass: HomeAssistant) -> None:
    """Ensure the embedded Lovelace card resource exists in storage mode."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.debug("Lovelace data not available yet, skipping auto-registration of card resource")
        return

    if getattr(lovelace_data, "resource_mode", None) != MODE_STORAGE:
        _LOGGER.debug(
            "Skipping automatic card resource registration because Lovelace resource mode is not storage"
        )
        return

    resources = getattr(lovelace_data, "resources", None)
    if resources is None:
        _LOGGER.debug("Lovelace resources collection unavailable, skipping card resource registration")
        return

    await resources.async_get_info()
    items = list(resources.async_items() or [])

    for item in items:
        if item.get("url") == CARD_RESOURCE_URL and item.get("type") == "module":
            return

    matching_item = next(
        (
            item for item in items
            if _resource_base_url(item.get("url")) == CARD_RESOURCE_BASE_URL
        ),
        None,
    )

    try:
        if matching_item and matching_item.get("id"):
            await resources.async_update_item(
                matching_item["id"],
                {"url": CARD_RESOURCE_URL, "res_type": "module"},
            )
            _LOGGER.info("Updated Lovelace resource for %s to %s", DOMAIN, CARD_RESOURCE_URL)
            return

        await resources.async_create_item(
            {"url": CARD_RESOURCE_URL, "res_type": "module"}
        )
        _LOGGER.info("Registered Lovelace resource for %s at %s", DOMAIN, CARD_RESOURCE_URL)
    except Exception as err:  # pragma: no cover - defensive integration guard
        _LOGGER.warning("Failed to auto-register Lovelace card resource: %s", err)


def _resource_base_url(url: str | None) -> str | None:
    if not url:
        return None

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

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

    await async_ensure_card_resource(hass)

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
        self._device_activity = {}
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

                        "min_run_minutes":
                            device.get("min_run_minutes", 0),

                        "min_pause_minutes":
                            device.get("min_pause_minutes", 0),

                        "offpeak_start_time":
                            device.get("offpeak_start_time"),

                        "pv_forecast_sensor":
                            value.get("pv_forecast_sensor"),

                        "pv_forecast_tomorrow_sensor":
                            value.get("pv_forecast_tomorrow_sensor"),

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

        # Führende und abschließende Nullminuten gehören nicht zum Lauf.
        while cleaned_profile and cleaned_profile[0] <= 0:
            cleaned_profile.pop(0)
        while cleaned_profile and cleaned_profile[-1] <= 0:
            cleaned_profile.pop()

        if len(cleaned_profile) < PROFILE_MIN_MINUTES:
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
        val_str = str(val_str).strip().replace('\xa0', ' ')
        if not val_str:
            return None
        # Falls Einheiten vorhanden sind ("1942 W"), nimm nur den ersten Teil
        val_str = val_str.split()[0]

        # Home-Assistant-States verwenden immer den Punkt als Dezimaltrenner.
        # Ein einzelner Trenner wird deshalb NIE als Tausendertrenner gedeutet
        # ("1.942" ist 1,942 und nicht 1942).
        try:
            parsed = float(val_str)
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            pass

        # Fallback für Texte aus Attributen mit lokalisierter Schreibweise.
        if "," in val_str and "." in val_str:
            if val_str.rfind(",") > val_str.rfind("."):
                # Deutsch: 1.234,56 -> 1234.56
                val_str = val_str.replace(".", "").replace(",", ".")
            else:
                # US: 1,234.56 -> 1234.56
                val_str = val_str.replace(",", "")
        elif "," in val_str:
            # Deutsches Dezimalkomma: 1,5 -> 1.5
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

    def _is_state_recent(self, state, max_age_minutes):
        if state is None:
            return False

        try:
            # Ein Sensor, der konstant denselben Wert meldet (z. B. 0 W), ändert
            # last_updated nicht. last_reported zeigt, dass er weiter meldet.
            last_seen = state.last_updated
            last_reported = getattr(state, "last_reported", None)
            if last_reported is not None and last_reported > last_seen:
                last_seen = last_reported
            age_seconds = (dt_util.utcnow() - last_seen).total_seconds()
        except (AttributeError, TypeError):
            return False

        return age_seconds <= (max_age_minutes * 60)

    def _sensor_problem(self, entity_id, state):
        """Kurzer Code für den Zustand eines konfigurierten Sensors."""
        if not entity_id:
            return None
        if state is None:
            return "missing"
        if state.state in ("unavailable", "unknown"):
            return "unavailable"
        return None

    def _is_stale(self, entity_id, state):
        """Veraltet-Prüfung. Nur sensor-Entitäten melden regelmäßig neu."""
        if state is None or entity_id.split(".", 1)[0] != "sensor":
            return None if state is None else False
        return not self._is_state_recent(state, ACTIVE_STATE_SENSOR_GRACE_MINUTES)

    def _is_device_running(self, current_power, state_sensor_state=None):
        """Returns device activity using power and an optional state sensor."""
        if state_sensor_state is not None:
            raw_state = str(state_sensor_state.state or "").lower()
            inactive_states = INACTIVE_STATE_VALUES
            active_states = ACTIVE_STATE_VALUES

            if raw_state in inactive_states:
                return False
            if raw_state in active_states:
                if current_power > DEVICE_ACTIVE_POWER_THRESHOLD:
                    return True
                if self._is_state_recent(state_sensor_state, ACTIVE_STATE_SENSOR_GRACE_MINUTES):
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
        raw_forecast, forecast_context = self._get_pv_forecast(
            first_config["pv_forecast_sensor"],
            first_config.get("pv_forecast_tomorrow_sensor")
        )
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
            "pv_forecast_tomorrow_sensor": first_config.get("pv_forecast_tomorrow_sensor"),
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
                profile = await self._get_adaptive_profile(entity_id, config.get("device_state_sensor"))
                state = self.hass.states.get(entity_id)
                current_device_power = self._parse_state_value(state) or 0.0
                device_state_sensor = config.get("device_state_sensor")
                state_sensor_state = self.hass.states.get(device_state_sensor) if device_state_sensor else None
                is_running = self._is_device_running(
                    current_device_power,
                    state_sensor_state
                )
                activity = self._update_device_activity(entity_id, is_running)
                cooldown_remaining = self._pause_remaining_minutes(
                    is_running,
                    activity,
                    state,
                    state_sensor_state,
                    config.get("min_pause_minutes", 0)
                )
                effective_start_offset = max(schedule_start_offset, cooldown_remaining)

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
                    effective_start_offset,
                    schedule_end_offset
                )
                plan_reason = "pv_window"

                # Reicht das Zeitfenster von heute nicht aus, wird dasselbe
                # Startfenster am Folgetag geprüft (z. B. morgen Vormittag).
                if (
                    profile
                    and not cooldown_remaining
                    and max_coverage < config.get("target_coverage", 90)
                ):
                    next_day = self._next_day_schedule_offsets(
                        schedule_start_time,
                        schedule_end_time
                    )
                    next_day_start, next_day_end = next_day if next_day else (None, None)
                    if (
                        next_day_start is not None
                        and next_day_start > schedule_start_offset
                        and next_day_start < len(virtual_pv_forecast)
                    ):
                        alt_start, alt_coverage, alt_battery_wh = self._calculate_best_window(
                            profile,
                            virtual_pv_forecast,
                            clean_base_load,
                            remaining_battery_wh,
                            battery_trace,
                            battery_charge_power,
                            battery_discharge_power,
                            max_battery_budget_wh,
                            config.get("target_coverage", 90),
                            next_day_start,
                            next_day_end
                        )
                        if alt_coverage > max_coverage:
                            best_start = alt_start
                            max_coverage = alt_coverage
                            battery_used_wh = alt_battery_wh
                            plan_reason = "tomorrow_window"

                if not profile:
                    plan_reason = "profile_missing"
                elif cooldown_remaining:
                    plan_reason = "minimum_pause"
                elif max_coverage < config.get("target_coverage", 90):
                    if plan_reason == "pv_window" and max_coverage < NO_PV_WINDOW_COVERAGE:
                        plan_reason = "no_pv_window"
                    offpeak_offset = self._next_time_offset(config.get("offpeak_start_time"))
                    if offpeak_offset is not None and offpeak_offset <= schedule_end_offset:
                        best_start = offpeak_offset
                        max_coverage, battery_used_wh = self._calculate_window_coverage(
                            profile, virtual_pv_forecast, clean_base_load,
                            remaining_battery_wh, battery_trace, battery_charge_power,
                            battery_discharge_power, max_battery_budget_wh, best_start
                        )
                        plan_reason = "offpeak_fallback"

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
                    plan_reason = "running"

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
                    "power_problem": self._sensor_problem(entity_id, state),
                    "power_is_stale": self._is_stale(entity_id, state) is not False,
                    "device_state_sensor": device_state_sensor,
                    "device_state": state_sensor_state.state if state_sensor_state else None,
                    "device_state_last_updated": state_sensor_state.last_updated.isoformat() if state_sensor_state else None,
                    "device_state_problem": self._sensor_problem(device_state_sensor, state_sensor_state),
                    "device_state_is_stale": self._is_stale(device_state_sensor, state_sensor_state) if state_sensor_state else None,
                    "best_start_mins": best_start,
                    "coverage_percent": round(max_coverage, 1),
                    "total_kwh": round(total_kwh, 2),
                    "battery_used_kwh": round(battery_used_wh / 1000, 2),
                    "duration_mins": duration_mins,
                    "plan_reason": plan_reason,
                    "minimum_run_remaining_mins": self._run_remaining_minutes(
                        is_running, activity, state, state_sensor_state,
                        config.get("min_run_minutes", 0)
                    ),
                    "minimum_pause_remaining_mins": cooldown_remaining,
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
                results[entity_id] = {"recommendation": "warten", "is_running": False, "current_power": 0.0, "best_start_mins": 0, "coverage_percent": 0, "total_kwh": 0, "duration_mins": 0, "weather_stability": 0, "priority": config["priority"], "target_coverage": config.get("target_coverage", 90), "best_start_time": None}
                
        return results

    def _calculate_weather_stability(self, forecast_sensor_id) -> float:
        state = self.hass.states.get(forecast_sensor_id)
        # Ein ausgefallener oder ungültiger Forecast hat keine Qualität. Die
        # Prognosequalität bleibt dann 0, passend zum Fail-closed-Forecast von 0 W.
        if not state or state.state in ("unknown", "unavailable"):
            return 0.0

        unit = state.attributes.get("unit_of_measurement")
        if unit and unit.lower() in ("kwh", "kw h"):
            try:
                estimate = float(state.attributes.get("estimate", state.state))
                estimate10 = float(state.attributes.get("estimate10", estimate))
                if estimate > 0:
                    return max(0.5, min(1.0, estimate10 / estimate))
            except (TypeError, ValueError):
                return 0.0

            return 0.9

        try:
            val = float(state.state)
            return 0.75 if val < 500 else (0.88 if val < 1500 else 0.95)
        except (TypeError, ValueError):
            return 0.0

    def _update_device_activity(self, entity_id, is_running):
        now = dt_util.utcnow()
        activity = self._device_activity.setdefault(entity_id, {"is_running": None})
        if activity["is_running"] is not None and activity["is_running"] != is_running:
            activity["last_started" if is_running else "last_stopped"] = now
        activity["is_running"] = is_running
        return activity

    def _activity_changed_at(self, state, state_sensor_state):
        source = state_sensor_state or state
        return getattr(source, "last_changed", None) if source else None

    def _remaining_minutes(self, changed_at, minimum):
        if not changed_at or not minimum:
            return 0
        elapsed = (dt_util.utcnow() - changed_at).total_seconds() / 60
        return max(0, int(math.ceil(float(minimum) - elapsed)))

    def _run_remaining_minutes(self, is_running, activity, state, state_sensor_state, minimum):
        if not is_running:
            return 0
        return self._remaining_minutes(
            activity.get("last_started") or self._activity_changed_at(state, state_sensor_state),
            minimum
        )

    def _pause_remaining_minutes(self, is_running, activity, state, state_sensor_state, minimum):
        if is_running:
            return 0
        return self._remaining_minutes(
            activity.get("last_stopped") or self._activity_changed_at(state, state_sensor_state),
            minimum
        )

    def _next_time_offset(self, value):
        if not value:
            return None
        target_minutes = self._parse_time_minutes(value, "00:00")
        now = dt_util.now()
        now_minutes = (now.hour * 60) + now.minute
        return target_minutes - now_minutes if target_minutes >= now_minutes else (1440 - now_minutes) + target_minutes

    async def _get_adaptive_profile(self, entity_id, state_sensor_id=None):
        """Lernt ein 1-Minuten-Leistungsprofil aus den letzten abgeschlossenen Läufen."""
        now = dt_util.utcnow()
        cached_profile = self.learned_profiles.get(entity_id)
        normalized_cached_profile = self._normalize_profile(cached_profile) if cached_profile is not None else None
        if cached_profile is not None and normalized_cached_profile != cached_profile:
            # Ungültige oder alte Profile (z. B. mit führenden Nullminuten) bereinigen.
            if normalized_cached_profile is None:
                self.learned_profiles.pop(entity_id, None)
            else:
                self.learned_profiles[entity_id] = normalized_cached_profile
            await self.hass.async_add_executor_job(self.save_learned_profiles)

        # Throttling: Historie nur einmal pro Stunde abfragen oder wenn Profil fehlt
        last_check = self._profile_query_timestamps.get(entity_id, dt_util.utc_from_timestamp(0))
        if normalized_cached_profile is not None and (now - last_check).total_seconds() < 3600:
            return normalized_cached_profile

        self._profile_query_timestamps[entity_id] = now

        entity_ids = [entity_id]
        if state_sensor_id and state_sensor_id != entity_id:
            entity_ids.append(state_sensor_id)
        history_dict = await self.hass.async_add_executor_job(
            history.get_significant_states,
            self.hass,
            now - timedelta(days=PROFILE_LOOKBACK_DAYS),
            now,
            entity_ids
        )

        # Ohne gelerntes Profil wird bewusst nicht mit einer erfundenen
        # Verbrauchskurve geplant. Das verhindert falsche Sofort-Empfehlungen.
        power_states = history_dict.get(entity_id, [])
        if not power_states:
            return normalized_cached_profile or []

        state_sensor_states = history_dict.get(state_sensor_id, []) if state_sensor_id else []
        recent_profiles = self._extract_recent_completed_profiles(
            power_states,
            state_sensor_states,
            now
        )
        if recent_profiles:
            representative_profile = self._select_representative_profile(recent_profiles)
            self.learned_profiles[entity_id] = representative_profile
            await self.hass.async_add_executor_job(self.save_learned_profiles)
            return representative_profile

        return normalized_cached_profile or []

    def _minute_series(self, states, start, minutes, parse):
        """Step-Funktion der Zustände auf einem 1-Minuten-Raster.

        parse(state) liefert den Wert oder None (unavailable/unknown). Kurze
        Ausfälle schreiben den letzten gültigen Wert fort, längere zählen als 0.
        """
        series = []
        pointer = -1
        last_valid = 0.0
        last_valid_at = None
        for minute in range(minutes):
            moment = start + timedelta(minutes=minute)
            while pointer + 1 < len(states) and states[pointer + 1].last_changed <= moment:
                pointer += 1
            if pointer < 0:
                series.append(0.0)
                continue
            current = parse(states[pointer])
            if current is not None:
                last_valid = current
                last_valid_at = moment
                series.append(current)
            elif last_valid_at is not None and (moment - last_valid_at).total_seconds() <= PROFILE_DROPOUT_MINUTES * 60:
                series.append(last_valid)
            else:
                series.append(0.0)
        return series

    def _parse_state_active(self, state):
        raw = str(getattr(state, "state", "") or "").lower()
        if raw in ACTIVE_STATE_VALUES:
            return 1.0
        return 0.0

    def _extract_recent_completed_profiles(self, states, state_sensor_states=None, now=None):
        """Erkennt abgeschlossene Läufe und gibt ihre Profile zurück (neueste zuerst).

        Ein Lauf wird bevorzugt über den Statussensor abgegrenzt (on bis off).
        Ohne brauchbaren Statussensor endet ein Lauf erst nach einer
        durchgehenden Pause von PROFILE_QUIET_MINUTES. Dadurch zerfällt ein
        Waschgang nicht mehr in einzelne Heizphasen.
        """
        if not states:
            return []

        now = now or dt_util.utcnow()
        start = min(state.last_changed for state in states)
        total_minutes = int((now - start).total_seconds() // 60)
        if total_minutes < PROFILE_MIN_MINUTES:
            return []

        power = self._minute_series(
            states,
            start,
            total_minutes,
            lambda state: self._parse_state_value(state)
        )
        cycles = []

        status = []
        if state_sensor_states:
            status = self._minute_series(
                sorted(state_sensor_states, key=lambda state: state.last_changed),
                start,
                total_minutes,
                self._parse_state_active
            )

        if status and any(value > 0 for value in status):
            # Statussensor: zusammenhängende aktive Abschnitte, kleine Lücken überbrücken.
            minute = 0
            while minute < total_minutes:
                if status[minute] > 0:
                    end = minute
                    last_active = minute
                    while end < total_minutes and end - last_active <= 5:
                        if status[end] > 0:
                            last_active = end
                        end += 1
                    if end >= total_minutes:
                        break  # noch laufend
                    cycles.append((minute, last_active + 1))
                    minute = end
                else:
                    minute += 1
        else:
            # Nur Leistung: Pausen unter PROFILE_QUIET_MINUTES gehören zum Lauf.
            minute = 0
            while minute < total_minutes:
                if power[minute] > DEVICE_ACTIVE_POWER_THRESHOLD:
                    last_active = minute
                    end = minute
                    while end < total_minutes and end - last_active <= PROFILE_QUIET_MINUTES:
                        if power[end] > DEVICE_ACTIVE_POWER_THRESHOLD:
                            last_active = end
                        end += 1
                    if end >= total_minutes and end - last_active <= PROFILE_QUIET_MINUTES:
                        break  # Pause noch nicht lang genug: Lauf ist vermutlich nicht beendet
                    cycles.append((minute, last_active + 1))
                    minute = end
                else:
                    minute += 1

        profiles = []
        for cycle_start, cycle_end in reversed(cycles):
            if cycle_end - cycle_start < PROFILE_MIN_MINUTES:
                continue
            segment = power[cycle_start:min(cycle_end, cycle_start + PROFILE_MAX_MINUTES)]
            segment = [value if value >= DEVICE_ACTIVE_POWER_THRESHOLD else 0.0 for value in segment]
            normalized = self._normalize_profile(segment)
            if normalized:
                profiles.append(normalized)
            if len(profiles) >= PROFILE_SAMPLE_LIMIT:
                break
        return profiles

    def _select_representative_profile(self, profiles):
        median_duration = statistics.median(len(profile) for profile in profiles)
        energies = [sum(profile) / 60 for profile in profiles]
        median_energy = statistics.median(energies)
        return min(
            profiles,
            key=lambda profile: (
                abs(len(profile) - median_duration) / max(1, median_duration)
                + abs((sum(profile) / 60) - median_energy) / max(1, median_energy)
            )
        )

    def _get_pv_forecast(self, forecast_sensor_id, tomorrow_sensor_id=None):
        state = self.hass.states.get(forecast_sensor_id)
        context = {
            "forecast_source_unit": None,
            "forecast_remaining_kwh": None,
            "forecast_average_power": None,
            "forecast_status": "available",
            "forecast_tomorrow_kwh": None,
            "forecast_tomorrow_status": None
        }
        tomorrow_state = self.hass.states.get(tomorrow_sensor_id) if tomorrow_sensor_id else None
        tomorrow_kwh = None
        if tomorrow_sensor_id:
            tomorrow_kwh = self._read_energy_kwh(tomorrow_state)
            context["forecast_tomorrow_status"] = "available" if tomorrow_kwh is not None else "unavailable"
            context["forecast_tomorrow_kwh"] = round(tomorrow_kwh, 3) if tomorrow_kwh is not None else None

        today_window, tomorrow_window, window_known = self._get_daylight_windows()

        def spread(forecast, window, kwh, only_empty=False, shape=None):
            """Verteilt eine Tagesenergie glockenförmig auf ein Tageslichtfenster.

            Die Sonne liefert mittags am meisten. Eine konstante Leistung würde
            die Mittagsspitze verschlucken und die Deckung klein rechnen. `shape`
            ist das volle Tagesfenster, wenn `window` nur der Rest davon ist.
            """
            start, end = window
            length = max(60, end - start)
            shape_start, shape_end = shape if shape else (start, start + length)
            shape_length = max(60, shape_end - shape_start)
            minutes = list(range(max(0, start), min(FORECAST_HORIZON_MINUTES, start + length)))
            weights = [
                max(0.0, math.sin(math.pi * (minute - shape_start + 0.5) / shape_length))
                for minute in minutes
            ]
            total = sum(weights)
            if total <= 0:
                weights = [1.0] * len(minutes)
                total = float(len(minutes)) or 1.0
            # Summe der Minutenwerte in W / 60 ergibt die Energie in Wh.
            scale = kwh * 1000.0 * 60.0 / total
            for minute, weight in zip(minutes, weights):
                if not only_empty or forecast[minute] == 0.0:
                    forecast[minute] = scale * weight
            return max(0.0, (kwh * 1000.0) / (length / 60.0))

        # Volles Tagesfenster von heute: Sonnenaufgang liegt 1440 Minuten vor dem von morgen.
        today_shape = (tomorrow_window[0] - 1440, today_window[1]) if today_window else None

        # Hat der Morgen-Sensor eine detailedForecast (Solcast), wird deren echte
        # Tageskurve genutzt, sonst die glockenförmig verteilte Tagesenergie.
        tomorrow_profile = None
        if tomorrow_state is not None:
            tomorrow_detailed_list = tomorrow_state.attributes.get("detailedForecast")
            if isinstance(tomorrow_detailed_list, list):
                tomorrow_profile = self._forecast_from_detailed_intervals(tomorrow_detailed_list)

        def add_tomorrow(forecast, only_empty=False):
            if tomorrow_profile is not None:
                for minute, value in enumerate(tomorrow_profile):
                    if value > 0 and (not only_empty or forecast[minute] == 0.0):
                        forecast[minute] = value
                return None
            if tomorrow_kwh is not None:
                return spread(forecast, tomorrow_window, tomorrow_kwh, only_empty=only_empty)
            return None

        tomorrow_available = tomorrow_profile is not None or tomorrow_kwh is not None

        if not state or state.state in ("unknown", "unavailable"):
            context["forecast_status"] = "unavailable"
            forecast = [0.0] * FORECAST_HORIZON_MINUTES
            # Fällt die heutige Prognose aus, kann morgen trotzdem geplant werden.
            add_tomorrow(forecast)
            return forecast, context

        unit = state.attributes.get("unit_of_measurement")
        context["forecast_source_unit"] = unit

        detailed_forecast = state.attributes.get("detailedForecast")
        if isinstance(detailed_forecast, list):
            intervals = list(detailed_forecast)
            tomorrow_detailed = tomorrow_state.attributes.get("detailedForecast") if tomorrow_state else None
            if isinstance(tomorrow_detailed, list):
                intervals.extend(tomorrow_detailed)
                tomorrow_detailed_used = True
            else:
                tomorrow_detailed_used = False
            forecast = self._forecast_from_detailed_intervals(intervals)
            if forecast:
                if not tomorrow_detailed_used:
                    add_tomorrow(forecast, only_empty=True)
                context["forecast_average_power"] = round(sum(forecast[:720]) / 720, 1)
                # Restenergie bis Mitternacht aus der Prognose selbst. Das
                # Attribut `estimate` ist bei Solcast die ganze Tagesprognose.
                now_local = dt_util.now()
                minutes_to_midnight = max(0, 1440 - ((now_local.hour * 60) + now_local.minute))
                context["forecast_remaining_kwh"] = round(sum(forecast[:minutes_to_midnight]) / 60000.0, 3)
                return forecast, context

        try:
            forecast_value = float(state.attributes.get("estimate", state.state))
        except (TypeError, ValueError):
            context["forecast_status"] = "invalid"
            forecast = [0.0] * FORECAST_HORIZON_MINUTES
            add_tomorrow(forecast)
            return forecast, context

        if unit and unit.lower() in ("kwh", "kw h"):
            forecast = [0.0] * FORECAST_HORIZON_MINUTES
            context["forecast_remaining_kwh"] = round(forecast_value, 3)
            if today_window is None and not tomorrow_available:
                # Ohne Morgen-Sensor gilt wie bisher: Die Energie wird auf das
                # nächste Tageslichtfenster verteilt.
                average_power = spread(forecast, tomorrow_window, forecast_value)
            else:
                # Die Restenergie gehört zu heute. Nach Sonnenuntergang gibt es
                # dafür kein Fenster mehr, morgen kommt vom Morgen-Sensor.
                average_power = 0.0
                if today_window is not None:
                    average_power = spread(forecast, today_window, forecast_value, shape=today_shape)
                tomorrow_power = add_tomorrow(forecast)
                if today_window is None and tomorrow_power is not None:
                    average_power = tomorrow_power
            context["forecast_average_power"] = round(average_power, 1)
            return forecast, context

        context["forecast_average_power"] = round(forecast_value, 1)
        # Weniger aggressiver Abfall für den Fallback-Forecast
        forecast = [max(0.0, forecast_value - (i * 1.5)) for i in range(FORECAST_HORIZON_MINUTES)]
        next_start, next_end = today_window if today_window is not None else tomorrow_window
        if window_known:
            # Nur mit echten Sonnendaten maskieren, damit eine falsch geschätzte
            # Standardzeit keine gültige Prognose abschneidet.
            for minute in range(FORECAST_HORIZON_MINUTES):
                if not (next_start <= minute < next_end):
                    forecast[minute] = 0.0
        add_tomorrow(forecast, only_empty=True)
        return forecast, context

    def _read_energy_kwh(self, state):
        """Liest einen Energiesensor als kWh (Wh wird umgerechnet)."""
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.attributes.get("estimate", state.state))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        if str(state.attributes.get("unit_of_measurement") or "") == "Wh":
            value /= 1000.0
        return max(0.0, value)

    def _forecast_from_detailed_intervals(self, intervals):
        """Builds a 1-minute W forecast from Solcast-style kW intervals."""
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

            # Solcast liefert pv_estimate als mittlere Leistung der Periode in kW
            # (30-Minuten-Wert 0,94 = 940 W), nicht als Energie der Periode.
            try:
                estimate_kw = float(item.get("pv_estimate", 0.0))
            except (TypeError, ValueError):
                estimate_kw = 0.0

            parsed.append((start, estimate_kw))

        parsed.sort(key=lambda value: value[0])
        if len(parsed) < 2:
            return None

        forecast = [0.0] * FORECAST_HORIZON_MINUTES
        for index, (start, estimate_kw) in enumerate(parsed):
            next_start = parsed[index + 1][0] if index + 1 < len(parsed) else start + timedelta(minutes=30)
            average_power = max(0.0, estimate_kw * 1000.0)

            overlap_start = max(start, now)
            overlap_end = min(next_start, horizon_end)
            if overlap_end <= overlap_start:
                continue

            start_offset = max(0, int((overlap_start - now).total_seconds() / 60))
            end_offset = min(FORECAST_HORIZON_MINUTES, int((overlap_end - now).total_seconds() / 60))
            for minute in range(start_offset, end_offset):
                forecast[minute] = average_power

        return forecast

    def _get_daylight_window(self):
        """Returns (start_offset, end_offset, known) of the next daylight window."""
        today, tomorrow, known = self._get_daylight_windows()
        window = today if today is not None else tomorrow
        return window[0], window[1], known

    def _get_daylight_windows(self):
        """Returns (today_window, tomorrow_window, known).

        Fenster sind (Start, Ende) in Minuten ab jetzt. today_window ist None,
        sobald die Sonne heute untergegangen ist. `known` ist True, wenn die
        Zeiten aus `sun.sun` stammen, sonst gilt 07:00 bis 21:00 Uhr.
        """
        now = dt_util.now()
        sun = self.hass.states.get("sun.sun")

        if sun is not None:
            def local_time(attribute):
                raw = sun.attributes.get(attribute)
                parsed = dt_util.parse_datetime(str(raw)) if raw else None
                if parsed is None:
                    return None
                if parsed.tzinfo is None:
                    parsed = dt_util.as_local(parsed)
                return dt_util.as_local(parsed)

            def minutes_from_now(moment):
                return int((moment - now).total_seconds() // 60)

            setting_at = local_time("next_setting")
            rising_at = local_time("next_rising")
            if setting_at is not None and rising_at is not None:
                setting = minutes_from_now(setting_at)
                rising = minutes_from_now(rising_at)
                if sun.state == "below_horizon":
                    if rising_at.date() == now.date():
                        # Vor Sonnenaufgang: heute und morgen liegen noch voraus.
                        return (
                            (max(0, rising), max(rising + 1, setting)),
                            (rising + 1440, setting + 1440),
                            True
                        )
                    # Nach Sonnenuntergang: nur noch morgen.
                    return None, (max(0, rising), max(rising + 1, setting)), True
                # Sonne steht: heute bis Sonnenuntergang, morgen ab nächstem Aufgang.
                return (
                    (0, max(1, setting)),
                    (max(0, rising), max(rising + 1, setting + 1440)),
                    True
                )

        now_minutes = (now.hour * 60) + now.minute
        if now_minutes < DEFAULT_SUNRISE_MINUTES:
            return (
                (DEFAULT_SUNRISE_MINUTES - now_minutes, DEFAULT_SUNSET_MINUTES - now_minutes),
                (1440 + DEFAULT_SUNRISE_MINUTES - now_minutes, 1440 + DEFAULT_SUNSET_MINUTES - now_minutes),
                False
            )
        tomorrow = (
            (1440 - now_minutes) + DEFAULT_SUNRISE_MINUTES,
            (1440 - now_minutes) + DEFAULT_SUNSET_MINUTES
        )
        if now_minutes < DEFAULT_SUNSET_MINUTES:
            return (0, DEFAULT_SUNSET_MINUTES - now_minutes), tomorrow, False
        return None, tomorrow, False

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

    def _next_day_schedule_offsets(self, start_time, end_time):
        """Startfenster des nächsten Kalendertags als Minuten ab jetzt (oder None)."""
        now = dt_util.now()
        now_minutes = (now.hour * 60) + now.minute
        start_minutes = self._parse_time_minutes(start_time, DEFAULT_SCHEDULE_START_TIME)
        end_minutes = self._parse_time_minutes(end_time, DEFAULT_SCHEDULE_END_TIME)
        if start_minutes == end_minutes:
            return None
        length = (end_minutes - start_minutes) % 1440
        start = (1440 - now_minutes) + start_minutes
        return start, start + length

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
        requested_earliest = max(0, int(earliest_start_offset))
        if profile_len >= forecast_len:
            return requested_earliest, 0.0, 0.0

        # Der früheste erlaubte Start (Startfenster, Mindestpause) darf nie nach
        # vorne geklemmt werden. Liegt er hinter dem Forecast-Horizont, gibt es
        # dort keine belastbare Prognose, also keine Deckung.
        max_start_by_forecast = forecast_len - profile_len
        if requested_earliest > max_start_by_forecast:
            return requested_earliest, 0.0, 0.0

        windows = []
        earliest_start = requested_earliest
        latest_start = min(max_start_by_forecast, max(earliest_start, int(latest_start_offset)))
        first_start = ((earliest_start + 14) // 15) * 15
        candidate_starts = [] if first_start == earliest_start else [earliest_start]
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
