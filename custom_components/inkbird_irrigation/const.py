"""Constants for the Inkbird Irrigation integration."""

DOMAIN = "inkbird_irrigation"

# Tuya protocol
TUYA_VERSION = 3.4

# ─── IIC-600 Data Point Mapping (kept for backward compat) ────────────────────

# Number of zones on the IIC-600
NUM_ZONES = 6

# Zone switches (bool): True = valve open
DP_ZONE_SWITCH = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}

# Zone countdown timers (int): seconds remaining
DP_ZONE_COUNTDOWN = {1: 13, 2: 14, 3: 15, 4: 16, 5: 17, 6: 18}

# Zone elapsed time counters (int): minutes elapsed since zone started
DP_ZONE_ELAPSED = {1: 25, 2: 26, 3: 27, 4: 28, 5: 29, 6: 30}

# Zone duration settings — read-only elapsed-time counters
DP_ZONE_DURATION = {1: 25, 2: 26, 3: 27, 4: 28, 5: 29, 6: 30}

# System DPs
DP_SYSTEM_POWER = 40
DP_SKIP_SCHEDULE = 43
DP_MODE = 101
DP_POWER_SWITCH = 102
DP_AUTO_REMAINING = 103
DP_RAIN_SENSOR_ENABLED = 107
DP_SEASONAL_ADJUST = 109
DP_ACTIVE_ZONE = 110
DP_QUEUED_ZONE = 111

# ─── Config entry keys ─────────────────────────────────────────────────────────

CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_DEVICE_IP = "device_ip"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_MODEL = "device_model"
# Last local protocol that returned a valid DP snapshot for this controller.
CONF_LOCAL_PROTOCOL = "local_protocol"

# Persistent user-selected transport policy (stored in ConfigEntry.options).
CONF_CONNECTION_MODE = "connection_mode"
CONNECTION_MODE_AUTO = "auto"
CONNECTION_MODE_LOCAL = "local"
CONNECTION_MODE_CLOUD = "cloud"
CONNECTION_MODES = frozenset(
    {CONNECTION_MODE_AUTO, CONNECTION_MODE_LOCAL, CONNECTION_MODE_CLOUD}
)

# Optional cloud fallback credentials
CONF_CLOUD_API_KEY = "cloud_api_key"
CONF_CLOUD_API_SECRET = "cloud_api_secret"
CONF_CLOUD_API_REGION = "cloud_api_region"
