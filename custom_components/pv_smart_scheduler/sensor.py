from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    """Sensoren basierend auf dem Koordinator anlegen."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    for entity_id in coordinator.devices.keys():
        entities.append(PVSchedulerSensor(coordinator, entity_id))
        
    async_add_entities(entities, update_before_add=True)

class PVSchedulerSensor(CoordinatorEntity, SensorEntity):
    """Repräsentiert die Start-Empfehlung für ein bestimmtes Gerät."""

    def __init__(self, coordinator, device_entity_id):
        """Initialisiert den Sensor und verknüpft den Koordinator."""
        super().__init__(coordinator)
        self.device_entity_id = device_entity_id
        
        # Generiert einen sauberen Gerätenamen (z.B. Waschmaschine)
        self._clean_device_name = device_entity_id.split('.')[-1].replace('_power', '').replace('_', ' ').title()
        self._attr_name = f"PV Scheduler {self._clean_device_name}"
        self._attr_unique_id = f"pv_sched_{device_entity_id}"

    @property
    def native_value(self):
        """Gibt den Hauptzustand ('ja' oder 'warten') aus."""
        if not self.coordinator.data:
            return "unbekannt"
        
        data = self.coordinator.data.get(self.device_entity_id)
        return data["recommendation"] if data else "unbekannt"

    @property
    def available(self) -> bool:
        """Gibt an, ob der Sensor valide Daten liefert."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def extra_state_attributes(self):
        """Zusätzliche Infos für das Dashboard und LLM-Kontext."""
        if not self.coordinator.data:
            return {}
            
        data = self.coordinator.data.get(self.device_entity_id)
        if not data:
            return {}
            
        start_time = "Sofort" if data["best_start_mins"] == 0 else f"In {data['best_start_mins']} Min"
        
        return {
            "best_start": start_time,
            "pv_coverage_percent": data["coverage_percent"],
            "estimated_consumption_kwh": data["total_kwh"],
            "weather_stability_percent": data["weather_stability"],
            # Absolut sichere Struktur für Ollama / OpenAI / OpenRouter
            "ai_prompt_context": {
                "device": self._clean_device_name,
                "action_recommended": "START_NOW" if data["recommendation"] == "ja" else "WAIT",
                "delay_minutes": data["best_start_mins"],
                "expected_solar_coverage": f"{data['coverage_percent']}%",
                "weather_condition_confidence": f"{data['weather_stability']}%"
            }
        }

    @property
    def icon(self):
        """Dynamisches Icon je nach Gerätetyp."""
        entity_lower = self.device_entity_id.lower()
        if "wash" in entity_lower:
            return "mdi:washing-machine"
        if "dryer" in entity_lower or "trockner" in entity_lower:
            return "mdi:tumble-dryer"
        if "dish" in entity_lower or "spuel" in entity_lower:
            return "mdi:dishwasher"
        if "pool" in entity_lower:
            return "mdi:pool"
        return "mdi:solar-power"
