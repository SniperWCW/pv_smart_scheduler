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
        super().__init__(coordinator)
        self.device_entity_id = device_entity_id
        self._attr_name = f"PV Scheduler {device_entity_id.split('.')[-1].replace('_power', '').title()}"
        self._attr_unique_id = f"pv_sched_{device_entity_id}"

    @property
    def state(self):
        """Gibt 'ja' oder 'warten' aus."""
        data = self.coordinator.data.get(self.device_entity_id)
        return data["recommendation"] if data else "unbekannt"

    @property
    def extra_state_attributes(self):
        """Zusätzliche Infos für das Dashboard."""
        data = self.coordinator.data.get(self.device_entity_id)
        if not data:
            return {}
            
        # Berechne die Uhrzeit für den besten Start
        start_time = "Sofort" if data["best_start_mins"] == 0 else f"In {data['best_start_mins']} Min"
        
        return {
            "best_start": start_time,
            "pv_coverage_percent": data["coverage_percent"],
            "estimated_consumption_kwh": data["total_kwh"],
            "monitored_entity": self.device_entity_id
        }

    @property
    def icon(self):
        """Dynamisches Icon je nach Gerätetyp."""
        if "wash" in self.device_entity_id:
            return "mdi:washing-machine"
        if "dryer" in self.device_entity_id:
            return "mdi:tumble-dryer"
        if "dish" in self.device_entity_id:
            return "mdi:dishwasher"
        return "mdi:solar-power"