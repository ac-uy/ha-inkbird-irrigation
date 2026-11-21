"""Device model profiles for Inkbird Irrigation controllers.

Each model class defines the DP mapping and zone-control semantics for a
specific hardware revision.  The API layer uses these profiles to interpret
data and issue commands without hard-coding any particular DP layout.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeviceModel(str, Enum):
    """Supported device models."""

    IIC_400 = "IIC-400"
    IIC_600 = "IIC-600"
    IIC_600_V35 = "IIC-600 v3.5"
    IIC_800 = "IIC-800"


@dataclass
class DeviceProfile:
    """Abstract DP mapping and capabilities for a device model."""

    model: DeviceModel
    num_zones: int
    product_id: str
    category: str
    tuya_version: float

    # --- DP mappings (zone-indexed dicts or single DPs) ---
    # Zone switches: zone_number -> DP id (IIC-600 has per-zone bool DPs)
    dp_zone_switch: dict[int, int] = field(default_factory=dict)

    # Zone countdown timers: zone_number -> DP id
    dp_zone_countdown: dict[int, int] = field(default_factory=dict)

    # Zone elapsed time: zone_number -> DP id
    dp_zone_elapsed: dict[int, int] = field(default_factory=dict)

    # System DPs — may or may not be present per model
    dp_system_power: int | None = None
    dp_skip_schedule: int | None = None
    dp_mode: int | None = None
    dp_power_switch: int | None = None
    dp_auto_remaining: int | None = None
    dp_rain_sensor: int | None = None
    dp_seasonal_adjust: int | None = None
    dp_active_zone_bitmask: int | None = None
    dp_queued_zone_bitmask: int | None = None

    # IIC-800 specific DPs
    dp_normal_time: int | None = None           # DP 38 — schedule/timer config (Raw)
    dp_irrigation_mode: int | None = None       # DP 44 — "order" / "together" (Enum)
    dp_irrigation_time_all: int | None = None   # DP 45 — 34 bytes raw (see below)
    dp_operation_mode: int | None = None        # DP 101 — "OFF"/"Manual"/"Auto" (Enum)
    dp_reset_device: int | None = None          # DP 105 — reset (Boolean)
    dp_timeerror_alarm: int | None = None       # DP 106 — time error alarm (Boolean)
    dp_cancel_alarm_voice: int | None = None    # DP 109 — cancel alarm voice (Boolean)
    dp_merge_history: int | None = None         # DP 104 — history (Raw 4 bytes)

    # Control semantics
    zone_control_method: str = "countdown"  # "countdown" (IIC-600) or "bitmask_raw" (IIC-800)

    # DP 45 payload length in bytes, used for manual-start commands and to
    # disambiguate hex vs base64 reports. 34 on the IIC-800 (2 + 4 x 8 zones).
    dp45_length: int = 34

    # --- Capabilities: what live telemetry this model actually provides ---
    # Default True so existing models keep their behaviour; set False only
    # where live hardware testing proved the data is unavailable/meaningless.

    # The device reports DP 45 in status(), so per-zone remaining/elapsed time
    # can be derived from it. The IIC-400 treats DP 45 as a write-only start
    # command and never reports it, so this is False there.
    supports_dp45_readback: bool = True

    # DP 104 (Merge_History) decodes into meaningful data worth exposing. On the
    # IIC-400 it is a volatile history scroll that does not track the active
    # zone (confirmed on real hardware), so this is False there.
    supports_merge_history: bool = True

    def get_all_dps(self) -> list[int]:
        """Return all known DP IDs for this device model."""
        dps: set[int] = set()
        dps.update(self.dp_zone_switch.values())
        dps.update(self.dp_zone_countdown.values())
        dps.update(self.dp_zone_elapsed.values())
        for attr in (
            "dp_system_power", "dp_skip_schedule", "dp_mode", "dp_power_switch",
            "dp_auto_remaining", "dp_rain_sensor", "dp_seasonal_adjust",
            "dp_active_zone_bitmask", "dp_queued_zone_bitmask",
            "dp_normal_time", "dp_irrigation_mode", "dp_irrigation_time_all",
            "dp_operation_mode", "dp_reset_device", "dp_timeerror_alarm",
            "dp_cancel_alarm_voice", "dp_merge_history",
        ):
            val = getattr(self, attr, None)
            if val is not None:
                dps.add(val)
        return sorted(dps)


# ─── IIC-600 Profile ──────────────────────────────────────────────────────────

IIC_600_PROFILE = DeviceProfile(
    model=DeviceModel.IIC_600,
    num_zones=6,
    product_id="",  # Unknown / varies
    category="",
    tuya_version=3.4,
    dp_zone_switch={1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6},
    dp_zone_countdown={1: 13, 2: 14, 3: 15, 4: 16, 5: 17, 6: 18},
    dp_zone_elapsed={1: 25, 2: 26, 3: 27, 4: 28, 5: 29, 6: 30},
    dp_system_power=40,
    dp_skip_schedule=43,
    dp_mode=101,
    dp_power_switch=102,
    dp_auto_remaining=103,
    dp_rain_sensor=107,
    dp_seasonal_adjust=109,
    dp_active_zone_bitmask=110,
    dp_queued_zone_bitmask=111,
    zone_control_method="countdown",
)

# ─── IIC-800 Profile ──────────────────────────────────────────────────────────
#
# The IIC-800 uses a fundamentally different approach:
# - No per-zone switch DPs (zones are controlled via DP 45 raw bytes + bitmask)
# - DP 45 (irrigation_time_all): 34 bytes raw — see encode/decode functions below
# - DP 107 (zonerun_state): bitmask of currently running zones (8 bits)
# - DP 108 (pendingzone_state): bitmask of queued zones (8 bits)
# - DP 44 (irrigation_mode): "order" (sequential) or "together" (parallel)
# - DP 101 (operation_mode): "OFF" / "Manual" / "Auto"
# - DP 38 (normal_time): schedule config (raw bytes, 20 bytes per channel)
# - DP 104 (Merge_History): 4 bytes raw — see decode function below
#
# DP 45 Format (34 bytes):
#   Byte 0: command type (0=query, 1=start/reset manual, 2=auto running report)
#   Byte 1: target (0=all stations, 1=specific stations)
#   Bytes 2-17: stations 1-8 running time (2 bytes each, big-endian, minutes)
#   Bytes 18-33: stations 1-8 single-use duration (2 bytes each, big-endian, minutes)
#
# DP 38 Format (20 bytes per channel, up to 8 channels = 160 bytes):
#   Byte 0: station number (1-8)
#   Byte 1: irrigation duration in minutes (0 = disabled)
#   Bytes 2-13: up to 6 start times (2 bytes each: hour, minute; 0xFFFF = unused)
#   Byte 14: cycle mode (0=weekly, 1=odd, 2=even, 3=interval)
#   Byte 15: weekday bitmask (bits 0-6 = Sun-Sat) or interval days (1-9)
#   Bytes 16-18: interval start date (year_offset, month, day)
#   Byte 19: rain sensor follow (0=ignore, 1=follow)
#
# DP 104 Format (Tuya "value" integer, read-only; bytes of the big-endian uint32):
#   Byte 0:
#     bits 7-4: auto(0) or manual(1)
#     bits 3-0: valve state (1=open, 0=closed)
#   Byte 1: irrigation channel number
#   Bytes 2-3 (big-endian uint16): total irrigation time in minutes
#   e.g. 268500997 = 0x10010005 -> manual, valve closed, channel 1, 5 minutes

IIC_800_PROFILE = DeviceProfile(
    model=DeviceModel.IIC_800,
    num_zones=8,
    product_id="h71ip90tp4mfd6mx",
    category="ggq",
    tuya_version=3.3,  # IIC-800 uses protocol v3.3 (confirmed)
    dp_zone_switch={},  # No individual zone switch DPs
    dp_zone_countdown={},  # No individual countdown DPs
    dp_zone_elapsed={},  # No individual elapsed DPs
    dp_system_power=None,
    dp_skip_schedule=None,
    dp_mode=None,
    dp_power_switch=None,
    dp_auto_remaining=None,
    dp_rain_sensor=102,  # RainSen_TotalONOFF
    dp_seasonal_adjust=103,  # SeaAdjValue (-90 to 100, step 10)
    dp_active_zone_bitmask=107,  # zonerun_state
    dp_queued_zone_bitmask=108,  # pendingzone_state
    dp_normal_time=38,
    dp_irrigation_mode=44,
    dp_irrigation_time_all=45,
    dp_operation_mode=101,
    dp_reset_device=105,
    dp_timeerror_alarm=106,
    dp_cancel_alarm_voice=109,
    dp_merge_history=104,
    zone_control_method="bitmask_raw",
)


# ─── IIC-600 v3.5 DP45 Profile ──────────────────────────────────────────────
#
# Newer IIC-600 revisions use the DP45 raw/bitmask architecture shared with
# IIC-400 and IIC-800, while retaining six stations. DP 38 starts with 0x06,
# which distinguishes this revision from the four-station IIC-400 (0x04).

IIC_600_V35_PROFILE = DeviceProfile(
    model=DeviceModel.IIC_600_V35,
    num_zones=6,
    product_id="ln52teq4wpifvfcl",
    category="ggq",
    tuya_version=3.5,
    dp_zone_switch={},
    dp_zone_countdown={},
    dp_zone_elapsed={},
    dp_system_power=None,
    dp_skip_schedule=None,
    dp_mode=None,
    dp_power_switch=None,
    dp_auto_remaining=None,
    dp_rain_sensor=102,
    dp_seasonal_adjust=103,
    dp_active_zone_bitmask=107,
    dp_queued_zone_bitmask=108,
    dp_normal_time=38,
    dp_irrigation_mode=44,
    dp_irrigation_time_all=45,
    dp_operation_mode=101,
    dp_reset_device=105,
    dp_timeerror_alarm=106,
    dp_cancel_alarm_voice=109,
    dp_merge_history=104,
    zone_control_method="bitmask_raw",
)


# ─── IIC-400 Profile ──────────────────────────────────────────────────────────
#
# The IIC-400 is very similar to the IIC-800, but with 4 zones instead of 8.
# Key differences:
# - 4 zones instead of 8
# - Tuya protocol v3.5
# - DP 110 and DP 111 are simple booleans (NOT bitmasks like the IIC-600)
# - DP 38 is pushed as one 20-byte block per station (first byte = station
#   1..4); a status snapshot carries the last block, so its first byte is 0x04
# - DP 45 is 18 bytes (2 + 4 x 4 zones), reported base64-encoded, e.g.
#   "AAEAAAAAAAAAAAAAAAAAAAAA" when idle (issue #1 capture)
# - Product ID is unknown at this time
#
# DP 110 / DP 111: Booleans. On the six-zone IIC-600 v3.5 schema (issue #4)
# they are "device_upgrade" and "master_switch"; unverified on the IIC-400.

IIC_400_PROFILE = DeviceProfile(
    model=DeviceModel.IIC_400,
    num_zones=4,
    product_id="x7hkmeis8yqj6ntj",  # confirmed 2026-11-21 from a live IIC-400-WIFI
    category="ggq",
    tuya_version=3.5,
    dp_zone_switch={},  # No individual zone switch DPs
    dp_zone_countdown={},  # No individual countdown DPs
    dp_zone_elapsed={},  # No individual elapsed DPs
    dp_system_power=None,
    dp_skip_schedule=None,
    dp_mode=None,
    dp_power_switch=None,
    dp_auto_remaining=None,
    dp_rain_sensor=102,  # RainSen_TotalONOFF (assumed same as IIC-800)
    dp_seasonal_adjust=103,  # SeaAdjValue (assumed same as IIC-800)
    dp_active_zone_bitmask=107,  # zonerun_state
    dp_queued_zone_bitmask=108,  # pendingzone_state
    dp_normal_time=38,
    dp_irrigation_mode=44,
    dp_irrigation_time_all=45,
    dp_operation_mode=101,
    dp_reset_device=105,
    dp_timeerror_alarm=106,
    dp_cancel_alarm_voice=109,
    dp_merge_history=104,
    zone_control_method="bitmask_raw",
    dp45_length=18,  # 2 + 4 x 4 zones, as reported by the device
    # DP 45 is write-only on the IIC-400 (never in status()), and DP 104 is a
    # volatile history scroll — both confirmed on real hardware 2026-11-21.
    supports_dp45_readback=False,
    supports_merge_history=False,
)


# ─── DP 45 Encoding/Decoding (IIC-800) ───────────────────────────────────────

DP45_LENGTH = 34  # IIC-800 payload length (2 + 4 bytes per zone x 8 zones)


def dp45_min_length(num_zones: int) -> int:
    """Return the shortest DP 45 payload carrying both words for every zone."""
    return 2 + 4 * num_zones


def encode_dp45_start_manual(
    durations: dict[int, int], num_zones: int = 8, length: int = DP45_LENGTH
) -> bytes:
    """Encode a DP 45 payload to START manual irrigation on specific zones.

    Args:
        durations: dict mapping zone (1-8) to duration in minutes.
                   Zones with 0 or missing entries won't run.
        num_zones: number of zones (default 8).
        length: payload length in bytes (34 on the IIC-800, 18 on the IIC-400).

    Returns:
        ``length``-byte payload.
    """
    payload = bytearray(max(length, dp45_min_length(num_zones)))
    payload[0] = 0x01  # command = start/reset manual irrigation
    payload[1] = 0x01  # target = specific stations

    # Bytes 2-17: manual duration per zone
    for zone in range(1, num_zones + 1):
        dur = durations.get(zone, 0)
        offset = 2 + (zone - 1) * 2
        struct.pack_into(">H", payload, offset, dur)

    return bytes(payload)


def encode_dp45_query() -> bytes:
    """Encode a DP 45 query payload."""
    payload = bytearray(DP45_LENGTH)
    payload[0] = 0x00  # command = query
    payload[1] = 0x00  # all stations
    return bytes(payload)


def decode_dp45(data: bytes, num_zones: int = 8) -> dict[str, Any]:
    """Decode a DP 45 payload (34 bytes on the IIC-800, 18 on the IIC-400).

    Byte layout (confirmed against live IIC-800 captures, 0-indexed,
    big-endian 16-bit words):
        Byte 0: command type (0=query, 1=start/reset, 2=auto report)
        Byte 1: target (0=all, 1=specific)
        First half after the header:  per-zone REMAINING time, counts DOWN
            (zone N at 2+(N-1)*2; bytes 2-17 on the IIC-800)
        Second half:                  per-zone ELAPSED time, counts UP
            (bytes 18-33 on the IIC-800, 10-17 on the IIC-400)
    While a zone runs, remaining decreases and elapsed increases; their sum is
    the configured single-use duration for that run.

    Returns dict with:
        command_type, target: int
        remaining: dict[int, int] — zone -> minutes left in the current run
        elapsed:   dict[int, int] — zone -> minutes run so far
        duration:  dict[int, int] — zone -> remaining + elapsed (configured)
    """
    result: dict[str, Any] = {
        "command_type": 0,
        "target": 0,
        "remaining": {},
        "elapsed": {},
        "duration": {},
    }

    if len(data) < dp45_min_length(num_zones):
        # Graceful handling of short payloads
        return result

    result["command_type"] = data[0]
    result["target"] = data[1]
    # The elapsed block starts halfway through the per-zone area, which also
    # covers a device reporting more zone slots than it has stations.
    elapsed_base = 2 + (len(data) - 2) // 2

    for zone in range(1, num_zones + 1):
        rem_offset = 2 + (zone - 1) * 2
        ela_offset = elapsed_base + (zone - 1) * 2
        remaining = struct.unpack_from(">H", data, rem_offset)[0]
        elapsed = struct.unpack_from(">H", data, ela_offset)[0]
        result["remaining"][zone] = remaining
        result["elapsed"][zone] = elapsed
        result["duration"][zone] = remaining + elapsed

    return result


# ─── DP 38 Decoding (IIC-800 schedule) ───────────────────────────────────────

CHANNEL_BLOCK_SIZE = 20  # bytes per channel


@dataclass
class ScheduleChannel:
    """Parsed schedule for one channel from DP 38."""

    station: int = 0
    duration_minutes: int = 0
    start_times: list[tuple[int, int]] = field(default_factory=list)  # (hour, minute)
    cycle_mode: int = 0  # 0=weekly, 1=odd, 2=even, 3=interval
    weekday_bitmask: int = 0  # bits 0-6 = Sun-Sat (if weekly) or interval days
    interval_start_date: tuple[int, int, int] = (0, 0, 0)  # (year_offset, month, day)
    rain_sensor_follow: bool = False


def decode_dp38(data: bytes) -> list[ScheduleChannel]:
    """Decode DP 38 (normal_time) raw bytes into channel schedules.

    Each channel is a 20-byte block. Up to 8 channels.
    """
    channels: list[ScheduleChannel] = []

    if not data or len(data) < CHANNEL_BLOCK_SIZE:
        return channels

    num_blocks = len(data) // CHANNEL_BLOCK_SIZE

    for i in range(num_blocks):
        offset = i * CHANNEL_BLOCK_SIZE
        block = data[offset:offset + CHANNEL_BLOCK_SIZE]
        if len(block) < CHANNEL_BLOCK_SIZE:
            break

        ch = ScheduleChannel()
        ch.station = block[0]
        ch.duration_minutes = block[1]

        # 6 start times, 2 bytes each (hour, minute). 0xFF,0xFF = unused.
        for t in range(6):
            t_off = 2 + t * 2
            hour = block[t_off]
            minute = block[t_off + 1]
            if hour != 0xFF or minute != 0xFF:
                ch.start_times.append((hour, minute))

        ch.cycle_mode = block[14]
        ch.weekday_bitmask = block[15]
        ch.interval_start_date = (block[16], block[17], block[18])
        ch.rain_sensor_follow = block[19] != 0

        channels.append(ch)

    return channels


# ─── DP 104 Decoding (Merge_History) ─────────────────────────────────────────

@dataclass
class MergeHistoryEntry:
    """Parsed DP 104 (Merge_History) 4-byte payload."""

    total_time_minutes: int = 0
    channel: int = 0
    is_manual: bool = False
    valve_state: int = 0


def decode_dp104(data: bytes) -> MergeHistoryEntry:
    """Decode DP 104 (Merge_History) — 4 bytes, read-only.

    The integer is stored big-endian. Layout of the 4 big-endian bytes, per the
    Tuya schema and live IIC-400/600 v3.5/800 values:
        data[0]:
            bits 7-4: auto(0) or manual(1)
            bits 3-0: valve state (1=open, 0=closed)
        data[1]: irrigation channel number
        data[2:4] (big-endian uint16): total irrigation time in minutes
    e.g. 268500997 = 0x10010005 -> manual, valve closed, channel 1, 5 minutes.
    """
    entry = MergeHistoryEntry()

    if not data or len(data) < 4:
        return entry

    entry.is_manual = ((data[0] >> 4) & 0x0F) != 0
    entry.valve_state = data[0] & 0x0F
    entry.channel = data[1]
    entry.total_time_minutes = struct.unpack_from(">H", data, 2)[0]

    return entry


# ─── Lookup helpers ───────────────────────────────────────────────────────────

PROFILES: dict[DeviceModel, DeviceProfile] = {
    DeviceModel.IIC_400: IIC_400_PROFILE,
    DeviceModel.IIC_600: IIC_600_PROFILE,
    DeviceModel.IIC_600_V35: IIC_600_V35_PROFILE,
    DeviceModel.IIC_800: IIC_800_PROFILE,
}

# Product IDs used for auto-detection
PRODUCT_ID_MAP: dict[str, DeviceModel] = {
    "h71ip90tp4mfd6mx": DeviceModel.IIC_800,
    "x7hkmeis8yqj6ntj": DeviceModel.IIC_400,
    "ln52teq4wpifvfcl": DeviceModel.IIC_600_V35,
}

# DPs that uniquely identify a model (used for auto-detection from status)
# IIC-600 has DPs 1-6 (zone switches), IIC-800 has DP 44/45
IIC_600_SIGNATURE_DPS = {1, 2, 3, 4, 5, 6, 13, 14, 15, 16, 17, 18}
IIC_800_SIGNATURE_DPS = {38, 44, 45, 107, 108}
# IIC-400 shares DPs with IIC-800 but has DP 110/111 as booleans (not bitmasks)
IIC_400_SIGNATURE_DPS = {38, 44, 45, 107, 108, 110, 111}


def _dp38_station_count(dps: dict[str, Any]) -> int | None:
    """Return the station count encoded by a DP 38 schedule payload."""
    raw = dps.get("38", dps.get(38))
    if isinstance(raw, str):
        try:
            raw = bytes.fromhex(raw)
        except ValueError:
            return None
    elif isinstance(raw, (list, bytearray)):
        raw = bytes(raw)

    if isinstance(raw, bytes) and raw:
        return raw[0]
    return None


def detect_model_from_dps(dps: dict[str, Any]) -> DeviceModel | None:
    """Detect the controller model from its DP schema and station count.

    DP45-based controllers share many DPs, including boolean DPs 110/111. Their
    DP38 schedule payload identifies the number of stations: 4=IIC-400,
    6=IIC-600 v3.5, and 8=IIC-800. Legacy IIC-600 controllers are identified
    by their individual zone-switch and countdown DPs.
    """
    dp_keys = {int(k) for k in dps.keys()}

    station_count = _dp38_station_count(dps)
    if station_count == 4:
        return DeviceModel.IIC_400
    if station_count == 6:
        return DeviceModel.IIC_600_V35
    if station_count == 8:
        return DeviceModel.IIC_800

    # A DP38 payload is not always included in every snapshot. Retain the
    # previous IIC-400 fallback only when no station-count discriminator exists.
    if 110 in dp_keys and 111 in dp_keys:
        val_110 = dps.get("110", dps.get(110))
        val_111 = dps.get("111", dps.get(111))
        if isinstance(val_110, bool) and isinstance(val_111, bool):
            return DeviceModel.IIC_400

    iic800_hits = dp_keys & IIC_800_SIGNATURE_DPS
    if len(iic800_hits) >= 2:
        return DeviceModel.IIC_800

    iic600_hits = dp_keys & IIC_600_SIGNATURE_DPS
    if len(iic600_hits) >= 3:
        return DeviceModel.IIC_600

    return None


def get_profile(model: DeviceModel) -> DeviceProfile:
    """Get the device profile for a model."""
    return PROFILES[model]
