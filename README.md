# PV Smart Scheduler

![PV Smart Scheduler Banner](images/banner.png)

PV Smart Scheduler ist eine Home Assistant Custom Integration zur PV-optimierten Planung von Haushaltsgeräten wie Waschmaschine, Trockner, Pool oder Whirlpool.

Die Integration erzeugt eine zentrale Entität `sensor.pv_smart_scheduler_zentrale`. Diese enthält eine priorisierte Geräteliste mit Startempfehlung, PV-Deckung, erwarteter Energie, Batterienutzung und Laufstatus.

## Funktionen

- **Visueller Schlachtplan:** Gantt-Timeline (08:00 - 20:00 Uhr) direkt in der Lovelace-Karte für alle geplanten Geräte.
- **Peak-Finder Technologie:** Findet immer den energetisch besten Zeitpunkt des Tages, auch wenn die PV-Leistung nicht für 100% Deckung ausreicht.
- **Intelligente Verbrauchsprofile:** Lernt automatisch aus echten Zyklen, ignoriert Standby-Rauschen (<50Wh) und aktualisiert sich kontinuierlich.
- **12-Stunden Vorausschau:** Erweiterter Planungshorizont (720 Minuten) für eine verlässliche Tagesplanung ab dem Morgen.
- Unterstützung für PV-Prognosen in W und Solcast-Restenergie in kWh
- **Akku-Nacht-Wächter:** Warnt visuell, wenn der aktuelle SoC voraussichtlich nicht ausreicht, um die Haus-Basislast bis zum nächsten Morgen zu decken.
- **Robustes Power-Parsing:** Erkennt Leistungswerte zuverlässig in Attributen oder im Hauptstatus, inklusive intelligenter Korrektur von Tausender-Trennzeichen.
- **Kaskadierende Priorisierung:** Höhere Prioritäten reservieren PV-Leistung und Batterie-Kapazität für nachfolgende Geräte.
- Geräte nachträglich einzeln löschen
- Geräte-Einstellungen (Entität, Priorität, Zielabdeckung) nachträglich bearbeiten
- Lovelace-Karte für die visuelle Anzeige

## Benötigte Sensoren

Pflicht:

- Geräte-Leistungssensor in W, z. B. Waschmaschine, Trockner oder Pool
- PV-Prognosesensor
- Haus-Basislast in W

Optional:

- Aktuelle PV-Leistung in W
- Batterie-SoC in %
- Verfügbare Batterie-Energie in kWh
- Mindest-SoC für Batterie-Nutzung

Solcast-Sensoren mit `unit_of_measurement: kWh` werden unterstützt. Die Integration nutzt dabei bevorzugt das Attribut `estimate` als verbleibende PV-Energie und rechnet daraus eine durchschnittliche verfügbare Leistung für den Planungshorizont.

## Einrichtung

1. Repository über HACS als Custom Repository hinzufügen.
2. Integration installieren.
3. Home Assistant neu starten.
4. Unter Einstellungen > Geräte & Dienste > Integration hinzufügen den PV Smart Scheduler einrichten.
5. Erstes Gerät und globale Sensoren auswählen.
6. Weitere Geräte über denselben Config Flow hinzufügen.

## Nachträglich anpassen

Über das Zahnrad der Integration stehen folgende Optionen zur Verfügung:

- Globale Sensoren ändern
- Gerät bearbeiten (Entität, Priorität oder Zielabdeckung anpassen)
- Einzelnes Gerät löschen

Die globalen Sensoren gelten für alle konfigurierten Geräte. Beim Löschen wird nur das ausgewählte Gerät entfernt.

## Zentrale Entität

Die Entität `sensor.pv_smart_scheduler_zentrale` liefert unter anderem:

- `devices`: Liste aller geplanten Geräte
- `device_count`: Anzahl Geräte
- `pv_current_power`: aktuelle PV-Leistung
- `battery_soc`: Batterie-Ladestand
- `battery_available_kwh`: nutzbare Batterie-Energie
- `forecast_source_unit`: Einheit des Forecast-Sensors
- `forecast_remaining_kwh`: verbleibende PV-Energie bei kWh-Forecast
- `forecast_average_power`: daraus berechnete Durchschnittsleistung
- `battery_night_warning`: True, wenn der Akku vermutlich nicht für die Nacht reicht
- `night_usage_estimate_wh`: Geschätzter Energiebedarf für 12 Stunden Nacht

Pro Gerät werden unter anderem geliefert:

- `recommendation`: `ja`, `warten` oder `läuft`
- `is_running`: Gerät läuft aktuell
- `best_start_time`: Konkreter ISO-Zeitstempel für den geplanten Start
- `best_start_mins`: Minuten bis zum Start
- `duration_mins`: Erwartete Programmdauer basierend auf dem gelernten Profil
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
/pv_smart_scheduler/pv-smart-scheduler-card.js?v=0.1.1
```
