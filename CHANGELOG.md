# Changelog

## v0.4.1

- New optional setting "PV-Prognosesensor Morgen" (kWh, or `detailedForecast` for Solcast). When the daily window is over or too weak, the planner now also checks the same schedule window on the next day and proposes the best start there ("Morgen 08:00").
- The forecast horizon is now 36 hours (was 12) so tomorrow morning can be planned in the evening.
- With the "today" sensor the remaining energy is only spread over the remaining daylight of today. After sunset it is no longer shifted onto tomorrow when a tomorrow sensor is set.
- When there is no usable PV window, the card shows "Kein PV-Fenster" instead of a start time right now with a warning icon.
- Sensor freshness uses `last_reported`, so sensors that keep reporting the same value (for example 0 W) are no longer marked as stale. Discrete state entities such as `input_boolean`, `climate` and `binary_sensor` are never marked as stale.
- A configured sensor that does not exist now shows "Sensor nicht gefunden: <entity>", an unavailable one "Sensor nicht verfügbar" (new attributes `power_problem` and `device_state_problem`).
- Card: the "Jetzt" marker and the time axis now align with the bars; they previously spanned the label column as well.
- New attributes `pv_forecast_tomorrow_sensor`, `forecast_tomorrow_kwh`, `forecast_tomorrow_status`, and plan reasons `tomorrow_window` and `no_pv_window`.

## v0.4.0

- Fixed the numeric parser: values such as `1.942` or `12.345` were read as thousands (1942 / 12345). A single separator is now always a decimal separator.
- Fixed kWh forecasts without `detailedForecast`: the remaining energy is only spread over the daylight window (from `sun.sun`, fallback 07:00 to 21:00) and is 0 W at night. Watt fallback forecasts are also cut off outside daylight when `sun.sun` is available.
- Fixed the start window search: the earliest allowed start (schedule window, minimum pause) is no longer clamped to an earlier time when the profile does not fit the forecast horizon.
- Forecast quality is now 0 % when the PV forecast is unavailable or invalid instead of showing 85 %.
- Fixed `battery_min_soc = 0` being replaced by 25 when adding another device.
- Optional global sensors can be cleared again in the options flow and in the add-device form.
- Settings changed in the add-device form are no longer overridden by older option values.
- Added the missing `no_devices` abort text for the options flow.
- Card: no more "Akku: null%" without a battery sensor, the card recovers after a missing entity appears, and it shows when the forecast is unavailable.
## v0.3.0-beta.4

- Made unavailable or invalid PV forecasts fail closed instead of assuming fictitious solar production.
- Learn a representative device profile from up to five recent completed runs instead of relying on one run.
- Added per-device minimum run and pause settings plus an optional off-peak fallback time.

## v0.3.0-beta.3

- Moved the current-time label above the timeline axis so it no longer covers a time tick.

## v0.3.0-beta.2

- Fixed HACS release installation by adding the required `hacs.json` metadata file at the repository root.

## v0.3.0-beta.1

- Added a compact scheduler summary with immediately useful device count, remaining PV forecast, and forecast quality.
- Added per-device planning and stale-sensor diagnostics, including planned battery use.
- Improved the Gantt timeline with coverage-based colours and a current-time marker.

## v0.2.6

- Added automatic Lovelace resource registration for the embedded card in Home Assistant storage mode.
- Resource URLs are now versioned automatically so card updates are picked up without manually editing the dashboard resource entry.

## v0.2.5

- Fixed stale optional device state sensors from keeping individual devices on outdated scheduler timing for too long.
- Added diagnostic freshness attributes for power and optional state sensors.

## v0.2.4

- Fixed an in-memory profile cache fallback that could keep using an invalid learned device profile even after `pv_smart_scheduler_profiles_v3.json` was deleted.

## v0.2.3

- Added a visible card version marker in the Lovelace header to detect stale frontend caches.
- Rejected implausible learned device profiles so corrupted history values no longer produce absurd `estimated_kwh` outputs.

## v0.2.2

- Improved PV window evaluation by simulating battery availability over time with charge/discharge limits.
- Fixed future reservation so higher-priority devices reserve only the PV share they actually consume.
- Hardened learned profile persistence in `pv_smart_scheduler_profiles_v3.json` with validation, pruning and atomic writes.
- Fixed Lovelace card start column for running devices so it shows `Läuft` instead of a watt value.

## v0.2.1

- Added optional per-device state sensor for more reliable running-state detection.
- Fixed Lovelace card running-state display so backend `is_running` is authoritative.
- Added diagnostic attributes for configured global sensors, device power state and optional device state sensor.
- Improved managed-load cleanup by respecting the optional device state sensor.
- Updated README and technical documentation for device state handling.

## v0.2.0

- Added future PV and battery reservation for cascading device priorities.
- Higher-priority devices now reserve their planned future time window, not only immediate starts.
- Running devices are evaluated and reserved from the current minute.
- Added Solcast `detailedForecast` support for time-resolved PV planning.
- Added configuration fields for battery capacity, charge power, discharge power, grid import and grid export.
- Added per-device `target_coverage` output for the Lovelace card.
- Added technical documentation in `docs/TECHNICAL.md`.
- Updated README and release version.

## v0.1.11

- Added advanced PV scheduler sensor configuration.
- Improved battery capacity handling and diagnostic attributes.
