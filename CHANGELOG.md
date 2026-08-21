# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.11] - 2026-08-21

### Added
- Add a dedicated six-zone IIC-600 v3.5 DP45 profile. Auto-detection now reads the station count from the DP 38 schedule payload before using ambiguous boolean DPs, selecting the correct IIC-600 profile for six-station controllers.

### Fixed
- Route IIC-400, IIC-600 v3.5, and IIC-800 controllers through their shared DP45/bitmask entities and local zone-control implementation.

## [0.7.10] - 2026-08-21

### Fixed
- Close and recreate the local Tuya socket immediately after an error or an empty status response, then retry compatible v3.4, v3.3, and v3.5 protocols through the existing bounded local recovery loop.

## [0.7.9] - 2026-08-21

### Fixed
- Ship the Home Assistant runtime English translation file so the two Configure menu choices, Local connection and Tuya Cloud API credentials, display their labels instead of appearing blank.

## [0.7.8] - 2026-08-18

### Fixed
- Register the persistent Inkbird transport loop as a Home Assistant background task so it no longer blocks Home Assistant startup while waiting for device updates.

## [0.7.7] - 2026-08-18

### Fixed
- Close the initial config-flow validation socket before creating the integration's persistent listener, preventing two local Tuya sessions from being opened during setup.
- On local listener failure, reconnect only with the last verified Tuya protocol version and apply capped exponential backoff instead of repeatedly probing multiple protocol versions and reopening local sessions.

## [0.7.6] - 2026-08-15

### Added
- Add a validated Local connection reconfigure path for updating the Local Key or controller IP without deleting and recreating the integration.

### Changed
- Split the Configure flow into independently verified Local connection and Tuya Cloud API credential paths; both reload the integration only after saving verified values.
- Temporarily unload the active local listener before Local Key/IP validation, preventing a second local Tuya session from conflicting with the controller; failed validation restores the unchanged integration.

## [0.7.5] - 2026-08-15

### Added
- Add a persistent Connection preference selector with Auto, Local, and Cloud modes. Auto prefers the event-driven local listener, falls back to verified cloud polling when local access fails, and periodically retries local.
- Add an integration reconfigure flow for replacing Tuya Cloud credentials after a read-only cloud-status verification, avoiding integration deletion and recreation.
- Document the Tuya IoT Core subscription limitation and the separate Home Assistant Tuya Device Sharing integration as an unverified cloud alternative.

### Changed
- Keep the Connection mode sensor as the active transport indicator and expose the selected preference and cloud availability as attributes.

### Fixed
- Make the coordinator transport-aware so cloud fallback uses bounded cloud polling instead of attempting a local push read in a tight loop.
- In Cloud mode, route only verified cloud controls through the Tuya Cloud API and reject unsupported controls rather than issuing a local command.
- Normalize TinyTuya cloud token/API failures in logs so a rejected Cloud-mode selection reports the provider error code and message instead of only `unknown`.

## [0.7.4] - 2026-08-15

### Fixed
- Replace 15-second full-status polling with one persistent local Tuya listener. The controller now sends pushed DP updates for state changes, avoiding both stale queued frames and repeated reconnects that can make an IIC-600 stop accepting local requests.

## [0.7.3] - 2026-08-14

### Fixed
- Use the IIC-600 active-zone bitmask as the authoritative valve state, preventing a lingering countdown from leaving a stopped zone shown as on.
- Send IIC-600 manual-start duration and active-zone bitmask as one atomic command, preventing the controller from applying an unintended run duration.
- Apply optimistic zone state only after the controller accepts the start or stop command.
- Reject empty local status snapshots and rebuild the IIC-600 active-zone bitmask from fresh valve states when cloud fallback cannot return DP 110, preventing stale optimistic state from persisting.
- Poll the IIC-600 using fresh non-persistent Tuya status queries, avoiding stale queued frames from a long-lived socket.

## [0.7.2] - 2026-08-14

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
