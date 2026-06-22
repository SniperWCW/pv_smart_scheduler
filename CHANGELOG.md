# Changelog

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
