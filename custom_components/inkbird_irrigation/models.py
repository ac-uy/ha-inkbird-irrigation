"""Device model profiles for Inkbird Irrigation controllers.

Each model class defines the DP mapping and zone-control semantics for a
specific hardware revision.  The API layer uses these profiles to interpret
data and issue commands without hard-coding any particular DP layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeviceModel(str, Enum):
    """Supported device models."""

    IIC_600 = "IIC-600"
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
    # Zone switches: zone_number → DP id (IIC-600 has per-zone bool DPs)
    dp_zone_switch: dict[int, int] = field(default_factory=dict)

    # Zone countdown timers: zone_number → DP id
    dp_zone_countdown: dict[int, int] = field(default_factory=dict)

    # Zone elapsed time: zone_number → DP id
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
    dp_normal_time: int | None = None           # DP 38 — schedule/timer config (String)
    dp_irrigation_mode: int | None = None       # DP 44 — "order" / "together" (Enum)
    dp_irrigation_time_all: int | None = None   # DP 45 — per-zone durations (Raw bytes)
    dp_operation_mode: int | None = None        # DP 101 — "OFF"/"Manual"/"Auto" (Enum)
    dp_reset_device: int | None = None          # DP 105 — reset (Boolean)
    dp_timeerror_alarm: int | None = None       # DP 106 — time error alarm (Boolean)
    dp_cancel_alarm_voice: int | None = None    # DP 109 — cancel alarm voice (Boolean)
    dp_merge_history: int | None = None         # DP 104 — history integer

    # Control semantics
    zone_control_method: str = "countdown"  # "countdown" (IIC-600) or "bitmask_raw" (IIC-800)

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
# - DP 45 (irrigation_time_all): Raw bytes encoding per-zone durations (8 zones)
# - DP 107 (zonerun_state): bitmask of currently running zones (8 bits)
# - DP 108 (pendingzone_state): bitmask of queued zones (8 bits)
# - DP 44 (irrigation_mode): "order" (sequential) or "together" (parallel)
# - DP 101 (operation_mode): "OFF" / "Manual" / "Auto"
# - DP 38 (normal_time): schedule config string
#
# Zone control hypothesis:
#   To start zones, write DP 45 with durations then set DP 101 to "Manual".
#   The device will run zones per the mode in DP 44.

IIC_800_PROFILE = DeviceProfile(
    model=DeviceModel.IIC_800,
    num_zones=8,
    product_id="h71ip90tp4mfd6mx",
    category="ggq",
    tuya_version=3.4,
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


# ─── Lookup helpers ───────────────────────────────────────────────────────────

PROFILES: dict[DeviceModel, DeviceProfile] = {
    DeviceModel.IIC_600: IIC_600_PROFILE,
    DeviceModel.IIC_800: IIC_800_PROFILE,
}

# Product IDs used for auto-detection
PRODUCT_ID_MAP: dict[str, DeviceModel] = {
    "h71ip90tp4mfd6mx": DeviceModel.IIC_800,
}

# DPs that uniquely identify a model (used for auto-detection from status)
# IIC-600 has DPs 1-6 (zone switches), IIC-800 has DP 44/45
IIC_600_SIGNATURE_DPS = {1, 2, 3, 4, 5, 6, 13, 14, 15, 16, 17, 18}
IIC_800_SIGNATURE_DPS = {38, 44, 45, 107, 108}


def detect_model_from_dps(dps: dict[str, Any]) -> DeviceModel | None:
    """Attempt to detect the device model from the returned DP keys."""
    dp_keys = {int(k) for k in dps.keys()}

    # Check IIC-800 signature DPs first (more unique)
    iic800_hits = dp_keys & IIC_800_SIGNATURE_DPS
    if len(iic800_hits) >= 2:
        return DeviceModel.IIC_800

    # Check IIC-600 signature DPs
    iic600_hits = dp_keys & IIC_600_SIGNATURE_DPS
    if len(iic600_hits) >= 3:
        return DeviceModel.IIC_600

    return None


def get_profile(model: DeviceModel) -> DeviceProfile:
    """Get the device profile for a model."""
    return PROFILES[model]
