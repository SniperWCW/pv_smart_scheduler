# Changelog

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
