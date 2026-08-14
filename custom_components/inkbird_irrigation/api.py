"""Inkbird WiFi Irrigation local API client using Tuya protocol.

Supports IIC-600 and IIC-800 models via device profiles.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import tinytuya

from .const import (
    DP_ACTIVE_ZONE,
    DP_AUTO_REMAINING,
    DP_MODE,
    DP_POWER_SWITCH,
    DP_QUEUED_ZONE,
    DP_RAIN_SENSOR_ENABLED,
    DP_SEASONAL_ADJUST,
    DP_SKIP_SCHEDULE,
    DP_SYSTEM_POWER,
    DP_ZONE_COUNTDOWN,
    DP_ZONE_DURATION,
    DP_ZONE_SWITCH,
)
from .models import (
    DeviceModel,
    DeviceProfile,
    decode_dp45,
    decode_dp104,
    decode_dp38,
    encode_dp45_start_manual,
    detect_model_from_dps,
    get_profile,
)

_LOGGER = logging.getLogger(__name__)


class InkbirdDevice:
    """Represents the state of an Inkbird irrigation controller (any model)."""

    def __init__(self, profile: DeviceProfile) -> None:
        self.profile = profile
        self.online: bool = False
        self.raw_dps: dict[str, Any] = {}

        # Common state
        self.system_power: str = "on"
        self.mode: str = "auto"  # IIC-600: "auto"/"manual"; IIC-800: "OFF"/"Manual"/"Auto"
        self.power_switch: bool = True
        self.skip_schedule: bool = False
        self.rain_sensor_enabled: bool = True
        self.seasonal_adjust: int = 0
        self.auto_remaining: int = 0
        self.active_zone: int = 0  # bitmask
        self.queued_zone: int = 0  # bitmask

        # Per-zone state
        num = profile.num_zones
        self.zone_active: dict[int, bool] = {z: False for z in range(1, num + 1)}
        self.zone_countdown: dict[int, int] = {z: 0 for z in range(1, num + 1)}
        self.zone_duration: dict[int, int] = {z: 0 for z in range(1, num + 1)}

        # IIC-800 specific state
        self.irrigation_mode: str = "order"  # "order" / "together"
        self.operation_mode: str = "OFF"  # "OFF" / "Manual" / "Auto"
        self.irrigation_time_all: bytes = b""  # raw DP 45
        self.normal_time: str = ""  # DP 38 schedule string (hex repr)
        self.normal_time_raw: bytes = b""  # DP 38 raw bytes
        self.timeerror_alarm: bool = False
        self.cancel_alarm_voice: bool = False
        self.reset_device: bool = False
        self.merge_history: int = 0
        self.merge_history_raw: bytes = b""  # DP 104 raw bytes
        self.merge_history_parsed: Any = None  # MergeHistoryEntry

    def update_from_dps(self, dps: dict[str, Any]) -> None:
        """Update device state from Tuya data points."""
        self.raw_dps.update(dps)

        if self.profile.model == DeviceModel.IIC_600:
            self._update_iic600(dps)
        elif self.profile.model == DeviceModel.IIC_800:
            self._update_iic800(dps)

    def _update_iic600(self, dps: dict[str, Any]) -> None:
        """Parse DPs for IIC-600."""
        active_zone_dp = str(DP_ACTIVE_ZONE)
        active_zone_received = active_zone_dp in dps

        for zone in range(1, self.profile.num_zones + 1):
            dp_switch = str(self.profile.dp_zone_switch[zone])
            dp_countdown = str(self.profile.dp_zone_countdown[zone])
            dp_elapsed = str(self.profile.dp_zone_elapsed[zone])

            if dp_switch in dps:
                self.zone_active[zone] = bool(dps[dp_switch])
            if dp_countdown in dps:
                self.zone_countdown[zone] = int(dps[dp_countdown])
            if dp_elapsed in dps:
                self.zone_duration[zone] = int(dps[dp_elapsed])

        if active_zone_received:
            self.active_zone = int(dps[active_zone_dp])
        elif any(
            str(self.profile.dp_zone_switch[zone]) in dps
            for zone in range(1, self.profile.num_zones + 1)
        ):
            # Cloud fallback does not expose DP 110. Rebuild its state from
            # fresh per-zone valve switches so an old optimistic bit cannot linger.
            self.active_zone = sum(
                1 << (zone - 1)
                for zone, is_active in self.zone_active.items()
                if is_active
            )

        if str(DP_SYSTEM_POWER) in dps:
            self.system_power = dps[str(DP_SYSTEM_POWER)]
        if str(DP_MODE) in dps:
            self.mode = dps[str(DP_MODE)]
        if str(DP_POWER_SWITCH) in dps:
            self.power_switch = bool(dps[str(DP_POWER_SWITCH)])
        if str(DP_SKIP_SCHEDULE) in dps:
            self.skip_schedule = bool(dps[str(DP_SKIP_SCHEDULE)])
        if str(DP_RAIN_SENSOR_ENABLED) in dps:
            self.rain_sensor_enabled = bool(dps[str(DP_RAIN_SENSOR_ENABLED)])
        if str(DP_SEASONAL_ADJUST) in dps:
            self.seasonal_adjust = int(dps[str(DP_SEASONAL_ADJUST)])
        if str(DP_AUTO_REMAINING) in dps:
            self.auto_remaining = int(dps[str(DP_AUTO_REMAINING)])
        if str(DP_ACTIVE_ZONE) in dps:
            self.active_zone = int(dps[str(DP_ACTIVE_ZONE)])
        if str(DP_QUEUED_ZONE) in dps:
            self.queued_zone = int(dps[str(DP_QUEUED_ZONE)])

    def _update_iic800(self, dps: dict[str, Any]) -> None:
        """Parse DPs for IIC-800."""
        p = self.profile

        # Operation mode (DP 101)
        if p.dp_operation_mode and str(p.dp_operation_mode) in dps:
            self.operation_mode = str(dps[str(p.dp_operation_mode)])
            self.mode = self.operation_mode

        # Irrigation mode (DP 44)
        if p.dp_irrigation_mode and str(p.dp_irrigation_mode) in dps:
            self.irrigation_mode = str(dps[str(p.dp_irrigation_mode)])

        # Rain sensor (DP 102)
        if p.dp_rain_sensor and str(p.dp_rain_sensor) in dps:
            self.rain_sensor_enabled = bool(dps[str(p.dp_rain_sensor)])

        # Seasonal adjust (DP 103)
        if p.dp_seasonal_adjust and str(p.dp_seasonal_adjust) in dps:
            self.seasonal_adjust = int(dps[str(p.dp_seasonal_adjust)])

        # Zone run state bitmask (DP 107)
        if p.dp_active_zone_bitmask and str(p.dp_active_zone_bitmask) in dps:
            bitmask = int(dps[str(p.dp_active_zone_bitmask)])
            self.active_zone = bitmask
            # Derive per-zone active state from bitmask
            for zone in range(1, p.num_zones + 1):
                self.zone_active[zone] = bool(bitmask & (1 << (zone - 1)))

        # Pending zone state bitmask (DP 108)
        if p.dp_queued_zone_bitmask and str(p.dp_queued_zone_bitmask) in dps:
            self.queued_zone = int(dps[str(p.dp_queued_zone_bitmask)])

        # Irrigation time all — raw bytes with per-zone durations (DP 45)
        if p.dp_irrigation_time_all and str(p.dp_irrigation_time_all) in dps:
            raw = dps[str(p.dp_irrigation_time_all)]
            self.irrigation_time_all = self._parse_raw_dp(raw)
            self._decode_zone_durations()

        # Normal time — schedule raw bytes (DP 38)
        if p.dp_normal_time and str(p.dp_normal_time) in dps:
            raw = dps[str(p.dp_normal_time)]
            self.normal_time_raw = self._parse_raw_dp(raw)
            self.normal_time = raw if isinstance(raw, str) else raw.hex() if isinstance(raw, bytes) else str(raw)

        # Merge history (DP 104) — 4 bytes raw
        if p.dp_merge_history and str(p.dp_merge_history) in dps:
            raw = dps[str(p.dp_merge_history)]
            self.merge_history_raw = self._parse_raw_dp(raw)
            self.merge_history_parsed = decode_dp104(self.merge_history_raw)

        # Reset device (DP 105)
        if p.dp_reset_device and str(p.dp_reset_device) in dps:
            self.reset_device = bool(dps[str(p.dp_reset_device)])

        # Time error alarm (DP 106)
        if p.dp_timeerror_alarm and str(p.dp_timeerror_alarm) in dps:
            self.timeerror_alarm = bool(dps[str(p.dp_timeerror_alarm)])

        # Cancel alarm voice (DP 109)
        if p.dp_cancel_alarm_voice and str(p.dp_cancel_alarm_voice) in dps:
            self.cancel_alarm_voice = bool(dps[str(p.dp_cancel_alarm_voice)])

        # Derive power state from operation mode
        self.power_switch = self.operation_mode != "OFF"
        self.system_power = "on" if self.power_switch else "off"

    @staticmethod
    def _parse_raw_dp(raw: Any) -> bytes:
        """Convert a raw DP value to bytes."""
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            # tinytuya may return raw DPs as hex strings
            try:
                return bytes.fromhex(raw)
            except ValueError:
                return raw.encode()
        if isinstance(raw, int):
            # Tuya reports some "raw" DPs as integers — convert to 4 big-endian bytes
            import struct
            return struct.pack(">I", raw & 0xFFFFFFFF)
        if isinstance(raw, (list, bytearray)):
            return bytes(raw)
        return b""

    def _decode_zone_durations(self) -> None:
        """Decode per-zone durations from irrigation_time_all (DP 45).

        The raw payload is 34 bytes:
          Byte 0: command type (0=query, 1=start/reset, 2=auto report)
          Byte 1: target (0=all, 1=specific)
          Bytes 2-17: stations 1-8 running time (2 bytes each, big-endian, minutes)
          Bytes 18-33: stations 1-8 single-use duration (2 bytes each, big-endian, minutes)
        """
        data = self.irrigation_time_all
        parsed = decode_dp45(data, self.profile.num_zones)

        # Use running_time if zones are active, otherwise show duration
        for zone in range(1, self.profile.num_zones + 1):
            running = parsed["running_time"].get(zone, 0)
            duration = parsed["duration"].get(zone, 0)
            # Show running time if non-zero (zone is active), else show configured duration
            self.zone_duration[zone] = running if running > 0 else duration



class InkbirdAPI:
    """Local Tuya API client for Inkbird irrigation controllers.

    Supports IIC-600 and IIC-800 via device profiles.
    Uses a fresh local status query for each poll to prevent stale frames from
    a persistent Tuya socket being presented as current controller state.
    Optionally falls back to Tuya Cloud API when local is unavailable.
    """

    def __init__(
        self,
        device_id: str,
        local_key: str,
        device_ip: str,
        cloud_api_key: str = "",
        cloud_api_secret: str = "",
        cloud_api_region: str = "eu",
        device_model: DeviceModel | str = DeviceModel.IIC_600,
    ) -> None:
        self._device_id = device_id
        self._local_key = local_key
        self._device_ip = device_ip
        self._cloud_api_key = cloud_api_key
        self._cloud_api_secret = cloud_api_secret
        self._cloud_api_region = cloud_api_region
        self._tuya: tinytuya.Device | None = None
        self._cloud: tinytuya.Cloud | None = None
        self._connected = False
        self._fail_count = 0
        self._using_cloud = False
        self._command_lock = False

        # Resolve model
        if isinstance(device_model, str):
            try:
                device_model = DeviceModel(device_model)
            except ValueError:
                device_model = DeviceModel.IIC_600
        self._model = device_model
        self._profile = get_profile(device_model)
        self.device = InkbirdDevice(self._profile)

    @property
    def model(self) -> DeviceModel:
        """Return the device model."""
        return self._model

    @property
    def profile(self) -> DeviceProfile:
        """Return the device profile."""
        return self._profile

    @property
    def _has_cloud(self) -> bool:
        return bool(self._cloud_api_key and self._cloud_api_secret)

    def _get_cloud(self) -> tinytuya.Cloud | None:
        """Get or create cloud client."""
        if not self._has_cloud:
            return None
        if not self._cloud:
            self._cloud = tinytuya.Cloud(
                apiRegion=self._cloud_api_region,
                apiKey=self._cloud_api_key,
                apiSecret=self._cloud_api_secret,
            )
        return self._cloud

    def _ensure_connection(self, version: float | None = None) -> tinytuya.Device | None:
        """Get or create a persistent connection.

        Args:
            version: If provided, force this protocol version. Otherwise use profile default.
        """
        if self._tuya and self._connected and version is None:
            return self._tuya
        # Close existing connection if switching versions
        if self._tuya and version is not None:
            self._reset_connection()
        try:
            ver = version if version is not None else self._profile.tuya_version
            self._tuya = tinytuya.Device(self._device_id, self._device_ip, self._local_key)
            self._tuya.set_version(ver)
            # Coordinator polls must use fresh responses. A persistent Tuya
            # socket can return a queued frame from an earlier controller state.
            self._tuya.set_socketPersistent(False)
            self._tuya.set_socketTimeout(5)
            self._connected = True
            self._fail_count = 0
            _LOGGER.debug(
                "Local connection prepared for %s (protocol v%.1f)",
                self._device_ip, ver,
            )
            return self._tuya
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Connection setup failed: %s", exc)
            self._connected = False
            return None

    def _reset_connection(self) -> None:
        """Close and reset the connection."""
        if self._tuya:
            try:
                self._tuya.close()
            except Exception:  # noqa: BLE001
                pass
        self._tuya = None
        self._connected = False

    def _try_connect_with_version(self, version: float) -> dict[str, Any] | None:
        """Attempt connection with a specific protocol version, return DPs or None."""
        self._reset_connection()
        d = self._ensure_connection(version=version)
        if not d:
            return None
        try:
            status = d.status()
            _LOGGER.debug(
                "Protocol v%.1f response from %s: %s", version, self._device_ip, status
            )
            if status and "dps" in status and status["dps"]:
                return status["dps"]
            # Log what the device returned even if empty
            if status:
                _LOGGER.warning(
                    "Device at %s returned status with protocol v%.1f but no DPs: %s",
                    self._device_ip, version, status,
                )
            else:
                _LOGGER.warning(
                    "Device at %s returned None/empty with protocol v%.1f",
                    self._device_ip, version,
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("status() failed with protocol v%.1f: %s", version, exc)
        return None

    def connect(self) -> bool:
        """Initialize the Tuya device connection and auto-detect model if needed.

        Tries the configured protocol version first. If no DPs are returned,
        retries with alternative protocol versions (3.3, 3.4, 3.5) to handle
        devices that use a different Tuya protocol than expected.
        """
        # Protocol versions to try: configured version first, then alternatives
        configured_ver = self._profile.tuya_version
        versions_to_try = [configured_ver]
        for v in (3.4, 3.3, 3.5):
            if v != configured_ver:
                versions_to_try.append(v)

        dps: dict[str, Any] | None = None
        successful_version: float = configured_ver

        for ver in versions_to_try:
            dps = self._try_connect_with_version(ver)
            if dps:
                successful_version = ver
                if ver != configured_ver:
                    _LOGGER.info(
                        "Device responded on protocol v%.1f (configured was v%.1f)",
                        ver, configured_ver,
                    )
                break
            # Small delay between retries to let device settle
            time.sleep(1)

        if dps:
            # Auto-detect model from returned DPs
            detected = detect_model_from_dps(dps)
            if detected and detected != self._model:
                _LOGGER.info(
                    "Auto-detected model %s (was configured as %s), switching profile",
                    detected.value, self._model.value,
                )
                self._model = detected
                self._profile = get_profile(detected)
                self.device = InkbirdDevice(self._profile)

            # Update profile tuya_version to the one that worked
            if successful_version != self._profile.tuya_version:
                _LOGGER.info(
                    "Updating protocol version from %.1f to %.1f for future connections",
                    self._profile.tuya_version, successful_version,
                )
                self._profile.tuya_version = successful_version

            self.device.online = True
            self.device.update_from_dps(dps)
            _LOGGER.debug(
                "Connected to Inkbird %s at %s (protocol v%.1f)",
                self._model.value, self._device_ip, successful_version,
            )
            return True

        _LOGGER.error(
            "No DPs returned from device at %s after trying protocol versions %s. "
            "Raw responses were logged at debug level. "
            "Possible causes: (1) Wrong Device ID or Local Key, "
            "(2) Another integration (e.g. LocalTuya) has an active connection to this "
            "device — remove any LocalTuya entities for this device and restart HA, "
            "(3) The device may be offline or unreachable.",
            self._device_ip,
            [f"v{v:.1f}" for v in versions_to_try],
        )
        self._reset_connection()
        return False

    def update(self) -> bool:
        """Poll the device for current state. Falls back to cloud if local fails."""
        if not self._using_cloud:
            try:
                d = self._ensure_connection()
                if d:
                    # Use a complete DP query on a non-persistent socket.
                    # `updatedps()` targets only a selected DP and can leave a
                    # queued persistent-socket frame to be read as this poll.
                    status = d.status()
                    dps = status.get("dps") if status else None
                    if isinstance(dps, dict) and dps:
                        self.device.online = True
                        self.device.update_from_dps(dps)
                        self._fail_count = 0
                        return True
                    self._fail_count += 1
                else:
                    self._fail_count += 1
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Local update failed: %s", exc)
                self._fail_count += 1

            if self._fail_count >= 3:
                self._reset_connection()

            if self._has_cloud and self._fail_count >= 2:
                _LOGGER.warning(
                    "Local connection failed %d times, falling back to cloud API",
                    self._fail_count,
                )
                self._using_cloud = True

        if self._using_cloud and self._has_cloud:
            if self._cloud_update():
                if self._fail_count % 20 == 0:
                    self._reset_connection()
                    try:
                        d = self._ensure_connection()
                        if d:
                            status = d.status()
                            dps = status.get("dps") if status else None
                            if isinstance(dps, dict) and dps:
                                _LOGGER.info("Local connection recovered")
                                self._using_cloud = False
                                self._fail_count = 0
                                self.device.update_from_dps(dps)
                    except Exception:  # noqa: BLE001
                        pass
                self._fail_count += 1
                return True

        self.device.online = False
        return False


    def _cloud_update(self) -> bool:
        """Poll device via cloud API (fallback)."""
        cloud = self._get_cloud()
        if not cloud:
            return False
        try:
            status = cloud.getstatus(self._device_id)
            if not status or not status.get("success") or not status.get("result"):
                return False

            dps: dict[str, Any] = {}

            if self._model == DeviceModel.IIC_600:
                code_to_dp = {
                    "switch_1": "1", "switch_2": "2", "switch_3": "3",
                    "switch_4": "4", "switch_5": "5", "switch_6": "6",
                    "countdown_1": "13", "countdown_2": "14", "countdown_3": "15",
                    "countdown_4": "16", "countdown_5": "17", "countdown_6": "18",
                    "use_time_1": "25", "use_time_2": "26", "use_time_3": "27",
                    "use_time_4": "28", "use_time_5": "29", "use_time_6": "30",
                    "water_control": "40", "control_skip": "43",
                }
                for item in status["result"]:
                    code = item.get("code", "")
                    dp = code_to_dp.get(code)
                    if dp:
                        value = item["value"]
                        if code == "water_control":
                            value = str(value)
                        dps[dp] = value

            elif self._model == DeviceModel.IIC_800:
                # IIC-800 cloud code-to-DP mapping
                code_to_dp_800 = {
                    "normal_time": "38",
                    "irrigation_mode": "44",
                    "irrigation_time_all": "45",
                    "operation_mode": "101",
                    "RainSen_TotalONOFF": "102",
                    "SeaAdjValue": "103",
                    "Merge_History": "104",
                    "ResetDevice": "105",
                    "timeerror_alarm": "106",
                    "zonerun_state": "107",
                    "pendingzone_state": "108",
                    "cancel_timealarm_voice": "109",
                }
                for item in status["result"]:
                    code = item.get("code", "")
                    dp = code_to_dp_800.get(code)
                    if dp:
                        dps[dp] = item["value"]

            if dps:
                self.device.online = True
                self.device.update_from_dps(dps)
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Cloud update failed: %s", exc)
            return False

    def _cloud_command(self, code: str, value: Any) -> bool:
        """Send command via cloud API."""
        cloud = self._get_cloud()
        if not cloud:
            return False
        try:
            commands = {"commands": [{"code": code, "value": value}]}
            result = cloud.sendcommand(self._device_id, commands)
            return result.get("success", False)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Cloud command failed: %s", exc)
            return False


    def _wait_for_device(self) -> None:
        """Wait for device to be ready for next command."""
        while self._command_lock:
            time.sleep(0.1)
        self._command_lock = True
        try:
            time.sleep(1)
        finally:
            self._command_lock = False

    # ─── IIC-600 Zone Control ──────────────────────────────────────────────────

    def _turn_on_zone_600(self, zone: int, duration_minutes: int) -> bool:
        """Start an IIC-600 zone with an atomic duration-and-zone command."""
        if self._using_cloud and self._has_cloud:
            return self._cloud_turn_on_600(zone, duration_minutes)
        try:
            d = self._ensure_connection()
            if d:
                dp_countdown = DP_ZONE_COUNTDOWN[zone]
                payload = d.generate_payload(
                    tinytuya.CONTROL,
                    {
                        str(dp_countdown): duration_minutes,
                        str(DP_ACTIVE_ZONE): 1 << (zone - 1),
                    },
                )
                d.send(payload)
                _LOGGER.debug(
                    "Zone %d ON for %d min (local) dp=%d, active_bitmask=%d",
                    zone,
                    duration_minutes,
                    dp_countdown,
                    1 << (zone - 1),
                )
                time.sleep(1)
                return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Local turn_on_zone failed: %s", exc)
            self._reset_connection()
        if self._has_cloud:
            return self._cloud_turn_on_600(zone, duration_minutes)
        return False

    def _cloud_turn_on_600(self, zone: int, duration_minutes: int) -> bool:
        """Start a zone via cloud (IIC-600)."""
        cloud = self._get_cloud()
        if not cloud:
            return False
        try:
            commands = {"commands": [
                {"code": f"switch_{zone}", "value": True},
                {"code": f"countdown_{zone}", "value": duration_minutes},
            ]}
            result = cloud.sendcommand(self._device_id, commands)
            return result.get("success", False)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Cloud turn_on failed: %s", exc)
            return False

    def _turn_off_zone_600(self, zone: int) -> bool:
        """Stop a zone on IIC-600."""
        if self._using_cloud and self._has_cloud:
            return self._cloud_command(f"switch_{zone}", False)
        try:
            d = self._ensure_connection()
            if d:
                dp_countdown = DP_ZONE_COUNTDOWN[zone]
                d.set_value(dp_countdown, 0)
                _LOGGER.debug("Zone %d OFF (local) dp=%d=0", zone, dp_countdown)
                time.sleep(1)
                return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Local turn_off_zone failed: %s", exc)
            self._reset_connection()
        if self._has_cloud:
            return self._cloud_command(f"switch_{zone}", False)
        return False

    # ─── IIC-800 Zone Control ──────────────────────────────────────────────────

    def _encode_zone_durations_800(self, durations: dict[int, int]) -> bytes:
        """Encode per-zone durations as 34-byte raw payload for DP 45.

        Format (34 bytes):
          Byte 0 = 0x01 (start manual irrigation)
          Byte 1 = 0x01 (specific stations)
          Bytes 2-17: running time per zone (set to 0, device fills in)
          Bytes 18-33: single-use duration per zone (2 bytes each, big-endian, minutes)
        """
        return encode_dp45_start_manual(durations, self._profile.num_zones)

    def _turn_on_zone_800(self, zone: int, duration_minutes: int) -> bool:
        """Start a zone on IIC-800.

        Strategy: Write DP 45 (34-byte payload with command=start, target=specific,
        and the zone's duration set) then set DP 101 (operation_mode) to "Manual".
        The device uses DP 107 (zonerun_state) bitmask to indicate active zones.
        """
        # Build durations: set only the target zone
        durations: dict[int, int] = {z: 0 for z in range(1, self._profile.num_zones + 1)}
        durations[zone] = duration_minutes
        raw_payload = self._encode_zone_durations_800(durations)

        if self._using_cloud and self._has_cloud:
            return self._cloud_turn_on_800(zone, duration_minutes, raw_payload)

        try:
            d = self._ensure_connection()
            if d:
                # Write durations
                dp_time = self._profile.dp_irrigation_time_all
                if dp_time:
                    d.set_value(dp_time, raw_payload, nowait=True)
                    time.sleep(0.5)
                # Set to Manual mode to start irrigation
                dp_mode = self._profile.dp_operation_mode
                if dp_mode:
                    d.set_value(dp_mode, "Manual")
                _LOGGER.debug("Zone %d ON for %d min (IIC-800 local)", zone, duration_minutes)
                time.sleep(1)
                return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Local turn_on_zone (800) failed: %s", exc)
            self._reset_connection()

        if self._has_cloud:
            return self._cloud_turn_on_800(zone, duration_minutes, raw_payload)
        return False

    def _cloud_turn_on_800(self, zone: int, duration_minutes: int, raw_payload: bytes) -> bool:
        """Start a zone via cloud (IIC-800)."""
        cloud = self._get_cloud()
        if not cloud:
            return False
        try:
            commands = {"commands": [
                {"code": "irrigation_time_all", "value": raw_payload.hex()},
                {"code": "operation_mode", "value": "Manual"},
            ]}
            result = cloud.sendcommand(self._device_id, commands)
            if result.get("success", False):
                _LOGGER.debug("Zone %d ON for %d min (IIC-800 cloud)", zone, duration_minutes)
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Cloud turn_on (800) failed: %s", exc)
            return False

    def _turn_off_zone_800(self, zone: int) -> bool:
        """Stop irrigation on IIC-800 by setting operation mode to OFF."""
        if self._using_cloud and self._has_cloud:
            return self._cloud_command("operation_mode", "OFF")
        try:
            d = self._ensure_connection()
            if d:
                dp_mode = self._profile.dp_operation_mode
                if dp_mode:
                    d.set_value(dp_mode, "OFF")
                _LOGGER.debug("Zone %d OFF (IIC-800 local)", zone)
                time.sleep(1)
                return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Local turn_off (800) failed: %s", exc)
            self._reset_connection()
        if self._has_cloud:
            return self._cloud_command("operation_mode", "OFF")
        return False

    def turn_on_zone_800_multi(self, durations: dict[int, int]) -> bool:
        """Start multiple zones on IIC-800 with individual durations.

        Sends DP 45 as a 34-byte payload (command=start, target=specific,
        durations in bytes 18-33) then sets DP 101 to "Manual".

        Args:
            durations: dict mapping zone number (1-8) to duration in minutes.
                       Zones with 0 or missing entries won't run.
        """
        self._wait_for_device()
        raw_payload = self._encode_zone_durations_800(durations)

        if self._using_cloud and self._has_cloud:
            cloud = self._get_cloud()
            if not cloud:
                return False
            try:
                commands = {"commands": [
                    {"code": "irrigation_time_all", "value": raw_payload.hex()},
                    {"code": "operation_mode", "value": "Manual"},
                ]}
                result = cloud.sendcommand(self._device_id, commands)
                return result.get("success", False)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Cloud multi-zone start failed: %s", exc)
                return False

        try:
            d = self._ensure_connection()
            if d:
                dp_time = self._profile.dp_irrigation_time_all
                if dp_time:
                    d.set_value(dp_time, raw_payload, nowait=True)
                    time.sleep(0.5)
                dp_mode = self._profile.dp_operation_mode
                if dp_mode:
                    d.set_value(dp_mode, "Manual")
                _LOGGER.debug("Multi-zone start (IIC-800 local): %s", durations)
                time.sleep(1)
                return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Local multi-zone start failed: %s", exc)
            self._reset_connection()
        return False


    # ─── Public dispatchers ────────────────────────────────────────────────────

    def turn_on_zone(self, zone: int, duration_minutes: int = 30) -> bool:
        """Turn on a zone for the specified duration."""
        if zone < 1 or zone > self._profile.num_zones:
            return False
        self._wait_for_device()

        if self._model == DeviceModel.IIC_600:
            return self._turn_on_zone_600(zone, duration_minutes)
        elif self._model == DeviceModel.IIC_800:
            return self._turn_on_zone_800(zone, duration_minutes)
        return False

    def turn_off_zone(self, zone: int) -> bool:
        """Turn off a zone."""
        if zone < 1 or zone > self._profile.num_zones:
            return False
        self._wait_for_device()

        if self._model == DeviceModel.IIC_600:
            return self._turn_off_zone_600(zone)
        elif self._model == DeviceModel.IIC_800:
            return self._turn_off_zone_800(zone)
        return False

    def set_zone_duration(self, zone: int, duration_minutes: int) -> bool:
        """Set the default duration for a zone (IIC-600 only, no-op for 800)."""
        if self._model == DeviceModel.IIC_800:
            # IIC-800 uses DP 45 (raw), duration is set at start time
            return True
        if zone < 1 or zone > self._profile.num_zones:
            return False
        try:
            d = self._ensure_connection()
            if not d:
                return False
            dp_duration = DP_ZONE_DURATION[zone]
            d.set_value(dp_duration, duration_minutes)
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to set duration for zone %d: %s", zone, exc)
            self._reset_connection()
            return False

    def set_dp(self, dp: int, value: Any) -> bool:
        """Set a single data point value."""
        try:
            d = self._ensure_connection()
            if not d:
                return False
            d.set_value(dp, value)
            _LOGGER.debug("Set DP %d = %r", dp, value)
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to set DP %d: %s", dp, exc)
            self._reset_connection()
            return False

    def set_irrigation_mode(self, mode: str) -> bool:
        """Set irrigation mode on IIC-800 ('order' or 'together')."""
        if self._model != DeviceModel.IIC_800:
            return False
        dp = self._profile.dp_irrigation_mode
        if dp is None:
            return False
        return self.set_dp(dp, mode)

    def set_operation_mode(self, mode: str) -> bool:
        """Set operation mode on IIC-800 ('OFF', 'Manual', 'Auto')."""
        if self._model != DeviceModel.IIC_800:
            return False
        dp = self._profile.dp_operation_mode
        if dp is None:
            return False
        return self.set_dp(dp, mode)
