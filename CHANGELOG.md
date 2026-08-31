# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Fixed

- Camera platform setup called `building.eagleeye_api.update()` (blocking network I/O) directly on the event loop. Recent Home Assistant versions raise instead of warn on this, crashing camera entity creation before it started. The fetch now runs via `hass.async_add_executor_job`.
- Carson's building camera list reports `provider: eagle_eye_v2` now, not `eagle_eye`. The building-scoped camera filter required an exact match, so it always returned zero cameras. Fixes [#6](https://github.com/lowlydba/ha-carson-living/issues/6).
