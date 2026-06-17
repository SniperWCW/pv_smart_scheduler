# PV Smart Scheduler

![PV Smart Scheduler Banner](images/banner.png)

PV Smart Scheduler ist eine Home Assistant Custom Integration zur PV-optimierten Planung von Haushaltsgeräten wie Waschmaschine, Trockner, Pool, Klimaanlage oder Whirlpool.

Die Integration erzeugt eine zentrale Entität `sensor.pv_smart_scheduler_zentrale`. Diese enthält eine priorisierte Geräteliste mit Startempfehlung, PV-Deckung, erwarteter Energie, Batterienutzung, Laufstatus und Diagnosewerten.

## Funktionen

- Visuelle Gantt-Timeline mit konfigurierbarem Startfenster, standardmäßig 05:00 bis 23:00 Uhr
- Peak-Finder: sucht den energetisch besten Zeitpunkt, auch wenn keine 100% PV-Deckung erreichbar ist
- Adaptive Verbrauchsprofile aus der Recorder-Historie der letzten 14 Tage
- Standby-Filter und robustes Parsing von Leistungswerten aus Status oder Attributen
- 12-Stunden-Planungshorizont mit kaskadierender Priorisierung
- Unterstützung für PV-Prognosen in W und Solcast-Restenergie in kWh
- Berücksichtigung aktueller PV-Produktion in W
- Berücksichtigung der Haus-Basislast in W
- Optionale Batterieplanung mit SoC, verfügbarer Energie in kWh und Mindest-SoC
- Akku-Nacht-Wächter mit optionalem Nachtverbrauchs-Sensor und Diagnosegrund statt pauschaler Warnung
- Erkennung bereits laufender Geräte über aktuelle Leistungsaufnahme
- Geräte nachträglich bearbeiten oder einzeln löschen
- Lovelace-Karte für die visuelle Anzeige

## Benötigte Sensoren

Pflicht:

- Geräte-Leistungssensor in W, z. B. Waschmaschine, Trockner, Pool oder Klimaanlage
- PV-Prognosesensor
- Haus-Basislast in W

Optional:

- Aktuelle PV-Leistung in W
- Batterie-SoC in %
- Verfügbare Batterie-Energie in kWh
- Mindest-SoC für Batterie-Nutzung
- Hausverbrauch Nacht in kWh
- Früheste und späteste Startzeit für neue Gerätestarts

Solcast-Sensoren mit `unit_of_measurement: kWh` werden unterstützt. Die Integration nutzt bevorzugt das Attribut `estimate` als verbleibende PV-Energie und rechnet daraus eine durchschnittlich verfügbare Leistung für den Planungshorizont.

## Einrichtung

1. Repository über HACS als Custom Repository hinzufügen.
2. Integration installieren.
3. Home Assistant neu starten.
4. Unter Einstellungen > Geräte & Dienste > Integration hinzufügen den PV Smart Scheduler einrichten.
5. Erstes Gerät und globale Sensoren auswählen.
6. Weitere Geräte über denselben Config Flow hinzufügen.

## Nachträglich Anpassen

Über das Zahnrad der Integration stehen folgende Optionen zur Verfügung:

- Globale Sensoren ändern
- Gerät bearbeiten, inklusive Entität, Priorität und Zielabdeckung
- Einzelnes Gerät löschen

Die globalen Sensoren gelten für alle konfigurierten Geräte. Beim Löschen wird nur das ausgewählte Gerät entfernt.

## Zentrale Entität

Die Entität `sensor.pv_smart_scheduler_zentrale` liefert unter anderem:

- `devices`: Liste aller geplanten Geräte
- `device_count`: Anzahl Geräte in der Ausgabe
- `configured_device_count`: Anzahl gespeicherter Geräte in der Konfiguration
- `unique_device_count`: Anzahl eindeutiger Leistungssensoren in der Berechnung
- `pv_current_power`: aktuelle PV-Leistung
- `battery_soc`: Batterie-Ladestand
- `battery_available_kwh`: nutzbare Batterie-Energie
- `battery_min_soc`: konfigurierte Mindestreserve
- `night_consumption_sensor`: konfigurierter Sensor für den letzten Nachtverbrauch
- `schedule_start_time`: früheste Startzeit für geplante Gerätestarts
- `schedule_end_time`: späteste Startzeit für geplante Gerätestarts
- `battery_night_warning`: `true`, wenn eine Warnung für die Nacht angezeigt werden soll
- `battery_night_reason`: Diagnose, warum gewarnt oder nicht gewarnt wird
- `night_usage_estimate_wh`: ermittelter oder geschätzter Energiebedarf für die Nacht
- `night_usage_source`: Quelle der Nachtverbrauchsschätzung
- `night_usage_window_start`: Start des ausgewerteten Nachtfensters bei kumulierenden Energiesensoren
- `night_usage_window_end`: Ende des ausgewerteten Nachtfensters bei kumulierenden Energiesensoren
- `forecast_source_unit`: Einheit des Forecast-Sensors
- `forecast_remaining_kwh`: verbleibende PV-Energie bei kWh-Forecast
- `forecast_average_power`: daraus berechnete Durchschnittsleistung

Pro Gerät werden unter anderem geliefert:

- `recommendation`: `ja`, `warten` oder `läuft`
- `is_running`: Gerät läuft aktuell
- `current_power`: aktuelle Leistung des Geräts
- `best_start_time`: konkreter ISO-Zeitstempel für den geplanten Start
- `best_start_mins`: Minuten bis zum Start
- `duration_mins`: erwartete Programmdauer basierend auf dem gelernten Profil
- `pv_coverage`: berechnete PV-/Batterie-Deckung
- `estimated_kwh`: erwarteter Energiebedarf
- `battery_used_kwh`: eingeplante Batterie-Energie

## Lovelace-Karte

Die Karte liegt unter:

```text
/pv_smart_scheduler/pv-smart-scheduler-card.js
```

Beispiel:

```yaml
type: custom:pv-smart-scheduler-card
entity: sensor.pv_smart_scheduler_zentrale
```

Nach Updates der Karte kann ein Browser-/App-Cache-Refresh nötig sein. Bei manueller Ressource hilft eine Versionsquery, z. B.:

```text
/pv_smart_scheduler/pv-smart-scheduler-card.js?v=0.1.10
```
