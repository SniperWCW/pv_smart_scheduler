import logging
import re

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Nur EINEN zentralen Sensor anlegen."""

    coordinator = hass.data[DOMAIN]["global_coordinator"]

    async_add_entities([
        PVSmartSchedulerMasterSensor(coordinator)
    ])

class PVSmartSchedulerMasterSensor(
    CoordinatorEntity,
    SensorEntity
):
    """Zentraler Scheduler Sensor."""

    def __init__(self, coordinator):
        super().__init__(coordinator)

        self._attr_name = "PV Smart Scheduler Zentrale"
        self._attr_unique_id = "pv_smart_scheduler_master"
        self._attr_icon = "mdi:solar-power"

    @property
    def native_value(self):
        """Anzahl sofort startbarer Geräte."""
        if not self.coordinator.data:
            return 0

        return sum(
            1
            for device in self.coordinator.data.values()
            if device.get("recommendation") == "ja"
        )

    @property
    def extra_state_attributes(self):
        """Geräteliste für Karte & AI."""

        devices = []
        coordinator_data = self.coordinator.data or {}

        sorted_devices = sorted(
            coordinator_data.items(),
            key=lambda x: x[1].get("priority", 99)
        )

        for entity_id, data in sorted_devices:

            state = self.hass.states.get(entity_id)
            friendly_name = self._device_display_name(entity_id, state)

            devices.append({
                "name": friendly_name,
                "entity_id": entity_id,
                "priority": data.get("priority", 1),
                "recommendation": data.get("recommendation"),
                "is_running": data.get("is_running", False),
                "current_power": data.get("current_power", 0),
                "best_start_mins": data.get("best_start_mins", 0),
                "best_start_time": data.get("best_start_time"),
                "duration_mins": data.get("duration_mins", 0),
                "pv_coverage": round(
                    data.get("coverage_percent", 0),
                    1
                ),
                "estimated_kwh": round(
                    data.get("total_kwh", 0),
                    2
                ),
                "battery_used_kwh": round(
                    data.get("battery_used_kwh", 0),
                    2
                ),
                "weather_confidence": round(
                    data.get("weather_stability", 0),
                    0
                )
            })

        context = self.coordinator.last_context or {}

        return {
            "devices": devices,
            "device_count": len(devices),
            "pv_current_power": context.get("pv_current_power"),
            "battery_soc": context.get("battery_soc"),
            "battery_available_kwh": context.get("battery_available_kwh"),
            "battery_min_soc": context.get("battery_min_soc"),
            "night_consumption_sensor": context.get("night_consumption_sensor"),
            "schedule_start_time": context.get("schedule_start_time"),
            "schedule_end_time": context.get("schedule_end_time"),
            "profile_lookback_days": context.get("profile_lookback_days"),
            "configured_device_count": context.get("configured_device_count"),
            "unique_device_count": context.get("unique_device_count"),
            "forecast_source_unit": context.get("forecast_source_unit"),
            "forecast_remaining_kwh": context.get("forecast_remaining_kwh"),
            "forecast_average_power": context.get("forecast_average_power"),
            "battery_night_warning": context.get("battery_night_warning"),
            "battery_night_reason": context.get("battery_night_reason"),
            "night_usage_estimate_wh": context.get("night_usage_estimate_wh"),
            "night_usage_source": context.get("night_usage_source"),
            "night_usage_window_start": context.get("night_usage_window_start"),
            "night_usage_window_end": context.get("night_usage_window_end")
        }

    def _device_display_name(self, entity_id, state):
        if state:
            friendly_name = state.attributes.get("friendly_name") or getattr(state, "name", None)
            if friendly_name and friendly_name != entity_id and not friendly_name.startswith("sensor."):
                return self._clean_device_name(friendly_name)

        return self._clean_device_name(entity_id)

    def _clean_device_name(self, name):
        name = name.split(".", 1)[-1]
        name = name.replace("_", " ").replace("-", " ").strip()
        name = re.sub(
            r"\b(current power|current consumption|aktuelle leistung|aktueller verbrauch|"
            r"derzeitige leistung|derzeitiger verbrauch|momentane leistung|"
            r"momentaner verbrauch|power|leistung|verbrauch)\b",
            "",
            name,
            flags=re.IGNORECASE
        )
        name = re.sub(r"\s+", " ", name).strip()

        return name.title() if name else "Gerät"
