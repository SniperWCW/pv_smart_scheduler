import logging
import datetime
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.recorder import history
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)
DOMAIN = "pv_smart_scheduler"

async def async_setup_entry(hass: HomeAssistant, entry):
    """Setup der Integration über die UI/Config Entry."""
    # Hier konfigurierst du später die Entitäten (z.B. per Options Flow)
    # Für dieses Beispiel hardcoden wir ein Test-Setup im Config-Eintrag
    configured_devices = entry.data.get("devices", {
        "sensor.waschmaschine_power": {
            "duration_hours": 2,
            "target_coverage": 95,
            "pv_forecast_sensor": "sensor.solcast_pv_forecast_4h", # Beispiel-Sensor
            "home_base_load_sensor": "sensor.home_base_consumption"
        }
    })

    coordinator = PVSmartSchedulerCoordinator(hass, configured_devices)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

class PVSmartSchedulerCoordinator(DataUpdateCoordinator):
    """Zentraler Koordinator für die Berechnung der Startzeiten."""

    def __init__(self, hass: HomeAssistant, devices):
        super().__init__(
            hass, 
            _LOGGER, 
            name=DOMAIN, 
            update_interval=timedelta(minutes=15)
        )
        self.devices = devices

    async def _async_update_data(self):
        """Berechnet die Empfehlungen für alle Geräte."""
        results = {}
        
        for entity_id, config in self.devices.items():
            try:
                # 1. Historisches Profil berechnen (Letzte 24h als Basis)
                profile = await self._get_historical_profile(entity_id, config["duration_hours"])
                
                # 2. PV-Prognose und Basislast holen
                forecast = self._get_pv_forecast(config["pv_forecast_sensor"])
                base_load = float(self.hass.states.get(config["home_base_load_sensor"]).state)

                # 3. Sliding Window Algorithmus
                best_start, max_coverage = self._calculate_best_window(
                    profile, forecast, base_load, config["target_coverage"]
                )

                results[entity_id] = {
                    "recommendation": "ja" if max_coverage >= config["target_coverage"] and best_start == 0 else "warten",
                    "best_start_mins": best_start,
                    "coverage_percent": round(max_coverage, 1),
                    "total_kwh": round(sum(profile) / 60, 2) # Watt-Minuten zu kWh
                }
            except Exception as err:
                _LOGGER.error(f"Fehler bei Berechnung für {entity_id}: {err}")
                
        return results

    async def _get_historical_profile(self, entity_id, duration_hours):
        """Holt die letzten aktiven Phasen des Sensors und baut ein Durchschnitts-Profil (in Minuten)."""
        now = dt_util.utcnow()
        start_time = now - timedelta(days=3) # Wir prüfen die letzten 3 Tage
        
        # Aufruf der HA Recorder History (muss im Executor laufen)
        history_list = await self.hass.async_add_executor_job(
            history.get_significant_states, self.hass, start_time, now, [entity_id]
        )

        # Standard-Profil falls keine Historie (z.B. 120 Minuten mit 400W im Schnitt)
        duration_mins = int(duration_hours * 60)
        default_profile = [400] * duration_mins

        if entity_id not in history_list:
            return default_profile

        states = history_list[entity_id]
        # Einfache Heuristik: Finde die letzte Phase, bei der die Leistung > 10W war
        # Für eine präzise Kurve kann man hier die Werte in ein minütliches Raster interpolieren
        # Aus Gründen der Übersichtlichkeit nutzen wir hier ein geglättetes Profil:
        return default_profile

    def _get_pv_forecast(self, forecast_sensor_id):
        """Holt die stündliche/minütliche Prognose. Gibt eine Liste von Watt-Werten pro Minute für die nächsten 4h zurück."""
        # Das hängt stark von deinem Prognose-Sensor ab (z.B. Solcast Attribut 'forecast')
        # Hier simulieren wir eine abfallende/steigende Kurve basierend auf dem aktuellen Zustand
        state = self.hass.states.get(forecast_sensor_id)
        current_forecast = float(state.state) if state else 1000.0
        
        # Erzeuge 240 Minuten-Werte (4 Stunden)
        return [max(0, current_forecast - (i * 2)) for i in range(240)]

    def _calculate_best_window(self, profile, forecast, base_load, target_coverage):
        """Der mathematische Kern: Verschiebe das Profil über die Prognose (Sliding Window)."""
        profile_len = len(profile)
        forecast_len = len(forecast)
        
        best_start_minute = 0
        max_coverage_found = 0.0

        # Verschiebe den Startzeitpunkt im Minutenraster
        for start_min in range(0, forecast_len - profile_len, 15): # 15-Minuten-Schritte für Performance
            total_device_energy = 0
            covered_by_pv_energy = 0

            for t in range(profile_len):
                device_power = profile[t]
                forecast_power = forecast[start_min + t]
                
                # Verfügbarer Überschuss in dieser Minute
                available_excess = max(0, forecast_power - base_load)
                
                total_device_energy += device_power
                covered_by_pv_energy += min(device_power, available_excess)

            coverage_percent = (covered_by_pv_energy / total_device_energy) * 100 if total_device_energy > 0 else 0

            if coverage_percent > max_coverage_found:
                max_coverage_found = coverage_percent
                best_start_minute = start_min

        return best_start_minute, max_coverage_found