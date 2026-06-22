# PV Smart Scheduler - Technische Dokumentation

Diese Dokumentation beschreibt die interne Logik der Home Assistant Custom Integration `pv_smart_scheduler`.

## Ziel

Der Scheduler berechnet fuer jedes konfigurierte Geraet eine PV-optimierte Startzeit. Ziel ist eine moeglichst hohe Eigenverbrauchsquote aus PV-Ueberschuss und optional nutzbarer Batterieenergie.

Die Integration schaltet keine Geraete selbst. Sie stellt Empfehlungen und Diagnosewerte ueber `sensor.pv_smart_scheduler_zentrale` bereit.

## Komponenten

- `custom_components/pv_smart_scheduler/__init__.py`
  - richtet den statischen Frontend-Pfad ein
  - erstellt den globalen `PVSmartSchedulerCoordinator`
  - sammelt Konfiguration, Sensorwerte, Profile und Scheduling-Ergebnisse
- `custom_components/pv_smart_scheduler/config_flow.py`
  - verwaltet Einrichtung, globale Sensoren, Geraete, Prioritaet und Zielabdeckung
- `custom_components/pv_smart_scheduler/sensor.py`
  - stellt die zentrale Sensor-Entitaet mit Geraeteliste und Kontextattributen bereit
- `custom_components/pv_smart_scheduler/frontend/pv-smart-scheduler-card.js`
  - zeigt Empfehlungen und Timeline in Lovelace an

## Update-Zyklus

Der `DataUpdateCoordinator` aktualisiert standardmaessig alle 60 Sekunden.

Bei jedem Update:

1. Geraetekonfiguration nach Prioritaet sortieren.
2. PV-Forecast laden und in ein 1-Minuten-Leistungsprofil umwandeln.
3. Aktuelle PV-Leistung, Basislast, Batterie und Nachtverbrauch lesen.
4. Nutzbare Batterieenergie berechnen.
5. Fuer jedes Geraet in Prioritaetsreihenfolge:
   - adaptives Verbrauchsprofil laden oder lernen
   - aktuellen Laufstatus erkennen
   - bestes Startfenster berechnen
   - Ergebnis in `coordinator.data` schreiben
   - PV- und Batteriereserve fuer nachfolgende Geraete abziehen

## Verbrauchsprofile

Die Funktion `_get_adaptive_profile(entity_id)` nutzt die Recorder-Historie der letzten 14 Tage.

Logik:

- Werte unter `DEVICE_ACTIVE_POWER_THRESHOLD` werden als Standby/aus betrachtet.
- Der letzte abgeschlossene aktive Zyklus wird gesucht.
- Der Zyklus wird auf ein 1-Minuten-Profil resampled.
- Profile unter 20 Minuten oder unter 50 Wh werden verworfen.
- Gelernt wird in `pv_smart_scheduler_profiles_v3.json` im Home-Assistant-Konfigurationspfad.

Fallback:

- Wenn kein brauchbares Profil existiert, wird `[300] * 120` verwendet.
- Das entspricht 120 Minuten bei 300 W.

## Laufstatus

Der Laufstatus wird in `_is_device_running(...)` bestimmt.

Standard:

- Ohne optionalen Statussensor gilt ein Geraet als laufend, wenn die aktuelle Leistung ueber `DEVICE_ACTIVE_POWER_THRESHOLD` liegt.

Optionaler Statussensor:

- Pro Geraet kann `device_state_sensor` konfiguriert werden.
- Das kann z. B. eine `climate.*`-, `switch.*`- oder `binary_sensor.*`-Entitaet sein.
- Wenn dieser Sensor gesetzt ist, entscheidet sein Zustand den Laufstatus.
- Typische inaktive Zustaende sind `off`, `idle`, `standby`, `unavailable`, `unknown`, `false` und `0`.
- Typische aktive Zustaende sind `on`, `running`, `active`, `cool`, `heat`, `dry`, `fan_only` und `auto`.

Das ist besonders fuer Klimaanlagen wichtig, weil der Leistungswert kurzfristig 0 W oder veraltet sein kann, obwohl das Geraet aus Home-Assistant-Sicht eingeschaltet ist.

## PV-Forecast

Der Forecast wird in `_get_pv_forecast(...)` in eine Liste von Wattwerten mit 720 Minuten Horizont umgerechnet.

Unterstuetzte Quellen:

- Sensorwert in W:
  - wird als aktuelle/nahe PV-Leistung interpretiert
  - Fallback-Profil sinkt linear leicht ab
- Sensor in kWh mit `estimate`:
  - wird als Restenergie interpretiert
  - ohne Detaildaten wird daraus eine Durchschnittsleistung bis 21:00 Uhr berechnet
- Solcast `detailedForecast`:
  - wird bevorzugt genutzt
  - jedes 30-Minuten-Intervall mit `pv_estimate` in kWh wird in durchschnittliche W umgerechnet
  - daraus entsteht ein minutengenaues Forecast-Profil

Die Funktion `_build_virtual_pv_forecast(...)` kombiniert diesen Forecast mit aktueller PV-Leistung. Fuer die ersten 90 Minuten wird aktuelle PV-Leistung als konservativer Mindestwert einbezogen.

## Basislast

Der konfigurierte `home_base_load_sensor` wird als aktuelle Haus-Basislast in W verwendet.

Bereinigung:

- Leistung aktuell laufender, vom Scheduler verwalteter Geraete wird abgezogen.
- Dadurch soll verhindert werden, dass bereits laufende Geraete doppelt in der Basislast und im Geraeteprofil auftauchen.

Wichtig:

- Ist der Sensor wirklich reine Grundlast ohne verwaltete Geraete, kann diese Bereinigung zu niedrig rechnen.
- Ist der Sensor Gesamtverbrauch des Hauses, ist die Bereinigung korrekt.

## Batterie

Die nutzbare Batterieenergie wird in `_calculate_available_battery_wh(...)` berechnet.

Bevorzugte Berechnung:

- `battery_soc_sensor` in %
- `battery_capacity_sensor` in kWh
- `battery_min_soc`

Formel:

```text
current_energy_kwh = capacity_kwh * soc / 100
reserved_energy_kwh = capacity_kwh * min_soc / 100
usable_kwh = current_energy_kwh - reserved_energy_kwh
```

Fallback:

- Wenn keine Gesamtkapazitaet vorhanden ist, wird `battery_energy_sensor` als aktuell gespeicherte Energie interpretiert.
- Daraus wird die Kapazitaet ueber den SoC zurueckgerechnet.

## Nachtreserve

Der Nachtverbrauch wird in `_get_night_usage_wh(...)` bestimmt.

Moegliche Quellen:

- expliziter Nachtverbrauchssensor
- Delta eines kumulierenden Energiezaehlers im letzten abgeschlossenen Nachtfenster
- Fallback: aktuelle bereinigte Basislast mal `DEFAULT_NIGHT_HOURS`

Der Nachtwaechter erzeugt aktuell eine Warnung, reduziert aber noch nicht automatisch das fuer Geraete nutzbare Batteriebudget. Diese bewusste Trennung verhindert versteckte Ueberkorrektur, bis die passende Reserve-Strategie konfigurierbar ist.

## Scheduling

Die Funktion `_calculate_best_window(...)` bewertet moegliche Startfenster.

Suchraum:

- Startfenster aus `schedule_start_time` und `schedule_end_time`
- 15-Minuten-Raster
- zusaetzlich exakt `earliest_start`, falls dieser nicht auf dem Raster liegt
- maximal 720 Minuten Forecast-Horizont

Pro Kandidat:

1. Fuer jede Minute des Geraeteprofils:
   - PV-Ueberschuss = `forecast_power - base_load`
   - PV-Deckung = Minimum aus Geraeteleistung und Ueberschuss
   - fehlende Energie wird gesammelt
2. Fehlende Energie kann durch verbleibendes Batteriebudget gedeckt werden.
3. Deckung in Prozent wird berechnet.

Auswahl:

- Wenn Start `0` die Zielabdeckung erreicht, wird sofort empfohlen.
- Sonst wird das erste Fenster gewaehlt, das die Zielabdeckung erreicht.
- Wenn kein Fenster die Zielabdeckung erreicht, gewinnt das Fenster mit maximaler Deckung, dann hoechster absoluter PV-Summe, dann frueherem Start.

## Kaskadierende Zukunftsreserve

Ab Version `0.2.0` reservieren hoeher priorisierte Geraete nicht nur Sofortstarts, sondern ihr tatsaechlich geplantes Zukunftsfenster.

Nach der Berechnung eines Geraets:

- `reservation_start = 0`, wenn das Geraet bereits laeuft
- sonst `reservation_start = best_start`
- `_reserve_forecast_window(...)` zieht das Geraeteprofil ab diesem Offset aus dem virtuellen PV-Forecast ab
- das berechnete `battery_used_wh` wird vom verbleibenden Batteriebudget abgezogen

Effekt:

- Prioritaet 1 kann z. B. 13:00 bis 15:00 PV-Leistung reservieren.
- Prioritaet 2 sieht diese PV-Leistung nicht mehr als frei verfuegbar.
- Mehrere Geraete verplanen dadurch nicht mehr dieselbe zukuenftige PV-Produktion.

Laufende Geraete:

- werden immer ab Offset `0` bewertet und reserviert
- dadurch blockieren sie reale aktuelle und kommende Leistung ab jetzt

## Empfehlungen

`recommendation` kann folgende Werte haben:

- `laeuft`: aktueller Leistungssensor liegt ueber `DEVICE_ACTIVE_POWER_THRESHOLD`
- `ja`: Zielabdeckung ist erreicht und `best_start_mins == 0`
- `warten`: alles andere

Auch bei `warten` wird `best_start_time` ausgegeben. Das ist die rechnerisch beste Startzeit im aktuellen Plan.

## Grenzen der aktuellen Logik

- Die Integration empfiehlt nur, sie automatisiert keinen Start.
- Nachtreserve ist Diagnose, aber noch kein harter Batterieabzug.
- Geraeteprofile basieren auf dem letzten brauchbaren Lauf, nicht auf Programmauswahl.
- Laufende Geraete werden mit dem vollen Profil ab jetzt reserviert; ein echter Restlaufzeit-Sensor waere genauer.
- Netzbezug und Einspeisung werden derzeit als Kontextwerte ausgegeben, aber noch nicht fuer eine eigene Ueberschusslogik aus Energie-Deltas genutzt.

## Relevante Attribute

Zentrale Attribute:

- `pv_current_power`
- `battery_soc`
- `battery_available_kwh`
- `battery_capacity_kwh`
- `battery_charge_power`
- `battery_discharge_power`
- `grid_import_energy_kwh`
- `grid_export_energy_kwh`
- `forecast_source_unit`
- `forecast_remaining_kwh`
- `forecast_average_power`
- `battery_night_warning`
- `battery_night_reason`

Geraeteattribute in `devices`:

- `name`
- `entity_id`
- `priority`
- `target_coverage`
- `recommendation`
- `is_running`
- `current_power`
- `power_state`
- `power_unit`
- `power_last_updated`
- `device_state_sensor`
- `device_state`
- `device_state_last_updated`
- `best_start_mins`
- `best_start_time`
- `duration_mins`
- `pv_coverage`
- `estimated_kwh`
- `battery_used_kwh`
- `weather_confidence`
