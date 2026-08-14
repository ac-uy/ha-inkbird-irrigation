# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- IIC-600 zone switches now use the countdown DP as their authoritative state, preventing stale valve-status DPs from leaving a zone falsely shown as on after watering stops.

## [0.7.1] - 2026-07-25

### Fixed
- Add config entry migration handler for v1→v2 (fixes "Migration handler not found" error when upgrading from v0.6.x)

## [0.7.0] - 2026-07-19

### Added
- Multi-model support: IIC-600 and IIC-800 WIFI
- Device profile abstraction (`models.py`) with auto-detection from returned DPs
- IIC-800 zone control via DP 45 (raw per-zone durations) + DP 101 (operation_mode)
- 8-zone support for IIC-800 with bitmask state (DP 107/108)
- Config flow model selector (Auto-detect / IIC-600 / IIC-800)
- IIC-800 specific sensors: irrigation mode, active/queued zone bitmask
- IIC-800 specific switches: rain sensor, timer error alarm, cancel alarm voice

### Changed
- API client refactored to be profile-driven
- Seasonal adjust range for IIC-800: -90 to 100 (step 10)

### Thanks
- @gonzzovela for reporting IIC-800 incompatibility and providing the full DP extract ([#3](https://github.com/ac-uy/ha-inkbird-irrigation/issues/3))

## [0.6.0] - 2026-07-05

### Fixed
- Zone turn-off not working in local control mode
- Wrong icon displayed for zone entities in the UI
- State bounce-back after issuing on/off commands
- Sensor update lag after state changes

## [0.1.0] - 2026-05-16

### Added
- Initial release of Inkbird Irrigation integration
- Support for Inkbird IIC-600-WIFI (6-zone sprinkler controller)
- Local control via Tuya protocol v3.4 (no cloud dependency)
- Zone valve switches (on/off for each of 6 zones)
- Zone duration number entities (1-240 minutes)
- Zone countdown sensors (seconds remaining)
- Operating mode sensor (auto/manual)
- Config flow with connection testing
- 15-second polling interval

### Features
- 100% local control — no internet required
- Turn zones on/off individually
- Set watering duration per zone
- Monitor remaining time per zone
- HACS compatible
