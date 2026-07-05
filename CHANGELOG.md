# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
