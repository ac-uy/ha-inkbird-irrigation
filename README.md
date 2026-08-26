# Inkbird Irrigation - Home Assistant Integration

[![GitHub Release](https://img.shields.io/github/release/ac-uy/ha-inkbird-irrigation.svg?style=flat-square)](https://github.com/ac-uy/ha-inkbird-irrigation/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](https://github.com/ac-uy/ha-inkbird-irrigation/blob/master/LICENSE)

A custom Home Assistant integration for the **Inkbird IIC-600-WIFI** smart irrigation controller. Full local control with automatic cloud fallback.

## Features

- 💧 **6 zone control** — turn valves on/off individually
- ⏱️ **Duration settings** — set watering time per zone (1-180 minutes)
- 📊 **Countdown timers** — see remaining time for each active zone
- ⏱️ **Elapsed time** — see how long each zone has been running
- 🏠 **Local first** — communicates directly with the device on your LAN
- ☁️ **Cloud fallback** — optional Tuya Cloud API fallback when local is unavailable
- 🔄 **Auto-recovery** — switches back to local when connection restores
- 🌧️ **Rain sensor status** — see if rain sensor is enabled
- 🔄 **Sequential zones** — queue multiple zones, they run one at a time (hardware behavior)
- 📡 **Connection selector** — choose Auto, Local only, or Cloud only
- 📡 **Connection mode sensor** — shows the transport currently serving state

## Supported Models

| Model | Status |
|-------|--------|
| IIC-600 WIFI | ✅ Fully supported with the legacy DP layout |
| IIC-600 WIFI (v3.5 / DP45) | 🧪 Beta — six-zone DP45 profile; please report results |
| IIC-800 WIFI | 🧪 Beta (testing in progress with community) |
| IIC-400 WIFI | ⚠️ Experimental (untested — community testers needed! See [issue #1](https://github.com/ac-uy/ha-inkbird-irrigation/issues/1)) |

## Prerequisites

Before installing this integration, you need your device's **Local Key** from the Tuya IoT Platform. This is a one-time setup.

### Getting Your Device Credentials

1. **Create a Tuya IoT account** at https://iot.tuya.com
2. **Create a Cloud Project** → select "Smart Home" as development method and your data center region (e.g., Central Europe for EU)
3. **Pair your IIC-600 with the Smart Life app** (not the Inkbird app):
   - Remove the device from the Inkbird app first
   - Download the **Smart Life** app (or **Tuya Smart** app)
   - Reset the IIC-600 to pairing mode and add it as a new device in Smart Life
4. **Link your Smart Life account** to the IoT Platform:
   - Go to Devices → Link Tuya App Account → scan the QR code with the Smart Life app
   - Make sure the data center matches your Smart Life account region
5. **Get the Local Key** via API Explorer:
   - Go to Cloud → API Explorer → Device Management → Get Device Information
   - Enter your Device ID and click Send Request
   - The response JSON contains the `local_key` field
6. **Find the device IP** on your router (look for the IIC-600 or run `python -m tinytuya scan`)

> ⚠️ **Important**: Set a **static IP** for your IIC-600 in your router's DHCP settings. If the IP changes, the integration will lose connection and you'll need to reconfigure it.

> 💡 **Tip**: If you don't know your Device ID, run `python -m tinytuya scan` on a computer on the same network — it will find Tuya devices and show their IDs.

### Device Credentials You Need

| Field | Where to find it |
|-------|-----------------|
| Device ID | Tuya IoT Platform or `python -m tinytuya scan` |
| Local Key | Tuya IoT Platform API Explorer |
| Device IP | Your router's connected devices list |

## Installation

### Via HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Go to **Integrations** → **⋮ (menu)** → **Custom repositories**
3. Add repository: `https://github.com/ac-uy/ha-inkbird-irrigation`
4. Select category: **Integration**
5. Find **Inkbird Irrigation** and click **Install**
6. Restart Home Assistant

### Manual Installation

1. Copy `custom_components/inkbird_irrigation` to your HA `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **"Inkbird"**
3. Enter your device credentials (Device ID, Local Key, IP address)
4. Click **Submit**

To update connection credentials later, open the integration’s **Configure** action and choose one of two independently verified, labelled paths:

- **Local connection** — use this when normal local access is unavailable after a Local Key change or IP-address change. The integration briefly stops its own local listener, performs one read-only local status request, then saves and reloads with the new values only after verification.
- **Tuya Cloud API credentials** — enter the Cloud Access ID, Access Secret, and region. The integration verifies them with a read-only cloud-status request before saving and reloading.

A failed Local verification restores the prior listener with the unchanged configuration. Neither path sends an irrigation command or requires deleting and recreating the integration.

## Entities Created

| Entity | Type | Description |
|--------|------|-------------|
| `switch.inkbird_iic_600_zone_1` - `zone_6` | Switch | Zone valve on/off |
| `switch.inkbird_iic_600_main_valve` | Switch | Main valve control |
| `switch.inkbird_iic_600_rain_sensor` | Switch | Rain sensor enable/disable |
| `switch.inkbird_iic_600_power` | Switch | System power |
| `number.inkbird_iic_600_zone_1_duration` - `zone_6` | Number | Duration setting (1-180 minutes) |
| `sensor.inkbird_iic_600_zone_1_time_remaining` - `zone_6` | Sensor | Countdown (minutes remaining) |
| `sensor.inkbird_iic_600_zone_1_time_elapsed` - `zone_6` | Sensor | Elapsed time (minutes running) |
| `sensor.inkbird_iic_600_mode` | Sensor | Operating mode (auto/manual) |
| `select.inkbird_iic_600_connection_preference` | Select | Requested transport: Auto, Local, or Cloud |
| `sensor.inkbird_iic_600_connection_mode` | Sensor | Active transport (`local`, `cloud`, or `unavailable`) |

## Connection Modes and Cloud Fallback (Optional)

The integration keeps one persistent local Tuya session for event-driven updates. Its listener runs as a Home Assistant background task, so waiting for device updates never delays Home Assistant startup. Optional Tuya Cloud credentials add a **Connection preference** selector:

- **Auto** (default): use the local listener when it is available. If its socket fails, verify cloud status and switch to bounded cloud polling; retry local every five minutes and switch back only after a successful local connection.
- **Local**: use only the local listener. The integration never sends a cloud command or polls cloud while this preference is selected.
- **Cloud**: first verify a Tuya Cloud status response, then close the local socket and poll cloud once per minute. If verification fails, the current working transport and selector value are unchanged.

The **Connection mode** sensor reports the currently active transport and exposes the selected preference and cloud availability as attributes.

**Cloud control coverage:** zone start/stop is supported. For IIC-600, main-valve and skip-schedule controls use the verified `water_control` and `control_skip` cloud codes. Controls without a confirmed cloud code are rejected in Cloud mode rather than silently issuing a local command.

### Tuya Cloud API limitation and alternatives

This integration's Cloud mode uses the Tuya IoT Core API. Tuya can expire its trial or paid IoT Core subscription, which prevents cloud status and control requests even when the controller remains online in the Inkbird app. When that happens, Cloud mode cannot be activated; Local mode remains fully independent and continues to work on the LAN.

Home Assistant's built-in **Tuya** integration is a separate cloud option that uses Tuya's Device Sharing SDK with QR sign-in through the Tuya Smart or Smart Life app, rather than this integration's IoT Core API credentials. It creates separate cloud entities and is **not** an automatic fallback transport for Inkbird Irrigation. IIC-600 irrigation DP/entity coverage has not yet been verified, so inspect the entities it discovers before relying on it for state or control. Do not reset or re-pair a working controller solely to test it: re-pairing may change its Local Key and interrupt the local integration.

To enable Auto fallback or Cloud mode, provide these optional setup fields:
- **Cloud API Key** — from your Tuya IoT Platform project
- **Cloud API Secret** — from your Tuya IoT Platform project
- **Cloud API Region** — `eu`, `us`, `cn`, etc.

Without cloud credentials, the integration remains local-only.

## Companion Card

For a dedicated Lovelace card with zone controls, progress bars, schedules, and connection status, install the **[Inkbird Irrigation Card](https://github.com/ac-uy/ha-inkbird-irrigation-card)**.

## Usage

### Turn on a zone for 15 minutes

Set the duration, then turn on the switch. The zone will run for the configured time and auto-stop.

```yaml
- service: number.set_value
  target:
    entity_id: number.inkbird_iic_600_zone_1_duration
  data:
    value: 15
- service: switch.turn_on
  target:
    entity_id: switch.inkbird_iic_600_zone_1
```

> **Tip**: The duration is remembered — if you've already set it, just turn on the switch next time.

### Automation: Water front garden every morning

```yaml
automation:
  - alias: "Morning watering"
    trigger:
      platform: time
      at: "07:00:00"
    action:
      - service: number.set_value
        target:
          entity_id: number.inkbird_iic_600_zone_1_duration
        data:
          value: 20
      - service: switch.turn_on
        target:
          entity_id: switch.inkbird_iic_600_zone_1
```

## Technical Details

- **Protocol**: Tuya local protocol varies by controller. The last protocol that returned a valid DP snapshot is stored in the config entry and tried first on later local reconnects.
- **Communication**: Direct LAN (UDP/TCP on device IP)
- **Dependency**: TinyTuya is pinned to `1.19.0`, matching the version used by the installed Tuya Local integration's tested persistent-session implementation.
- **Polling interval**: Event-driven local updates over one persistent Tuya session, with a non-waiting 10-second heartbeat and a 30-second read-only status reconciliation. The connection limits TinyTuya to one internal retry; the coordinator owns the bounded socket reset and protocol-rediscovery policy. On a local failure, it retries the persisted verified protocol first and performs one serialized v3.4/v3.3/v3.5 rediscovery cycle only after every third failed recovery attempt.
- **Session-lock limitation**: These transport safeguards reduce stale-session and retry churn risks, but cannot unlock a controller that has already begun rejecting every authenticated local session. That controller-side state requires a recovery action outside the local Tuya protocol.
- **Startup recovery**: If neither selected transport is initially reachable, the config entry stays loaded with unavailable entities. Its first local retry waits 30 seconds, then uses capped background recovery instead of repeatedly re-running Home Assistant entry setup.
- **Stable topology**: Model auto-detection runs before platforms are created. After setup, the integration retains that profile so a later recovery response cannot replace entities with an incompatible model layout.
- **No cloud dependency**: Works entirely on your local network
- **Zones**: Sequential only — one zone runs at a time (hardware limitation)
- **Duration**: 1-180 minutes per zone, configurable via number entity

## Development

### Local Testing (without HACS)

For development, you can copy the integration directly to your HA instance via Samba share:

```powershell
# Windows — copy to HA after code changes
xcopy /E /Y "custom_components\inkbird_irrigation\*" "\\YOUR_HA_IP\config\custom_components\inkbird_irrigation\"
```

Then reload the integration in HA (Settings → Devices & Services → Inkbird → ⋮ → Reload).

### Setup

```bash
git clone https://github.com/ac-uy/ha-inkbird-irrigation.git
cd ha-inkbird-irrigation
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install tinytuya
```

### Device Scanning

```bash
# Find Tuya devices on your network
python -m tinytuya scan

# Probe device data points
python local/probe_device.py
```

### Data Point Reference

| DP | Function | Type | Direction |
|----|----------|------|-----------|
| 1-6 | Zone 1-6 switch | bool | Read/Write |
| 13-18 | Zone 1-6 countdown | int (minutes) | Read (Write to start with duration) |
| 25-30 | Zone 1-6 elapsed time | int (minutes) | Read-only |
| 40 | Main valve control | str (`"on"`/`"off"`) | Read/Write |
| 43 | Skip schedule | bool | Read/Write |
| 101 | Mode | str (`"auto"`/`"manual"`) | Read |
| 102 | Power switch | bool | Read/Write |
| 103 | Auto-irrigation remaining time | int (minutes) | Read |
| 107 | Rain sensor enabled | bool | Read/Write |
| 109 | Seasonal adjustment | int (%) | Read/Write |
| 110 | Active zone bitmask | int | Read (Write to start zone with duration) |
| 111 | Queued zone bitmask | int | Read |

### Starting a Zone with Custom Duration

To start a zone with a specific duration, send the countdown DP and zone bitmask together:

```python
# Start Zone 3 for 15 minutes
payload = device.generate_payload(tinytuya.CONTROL, {"15": 15, "110": 4})
device.send(payload)
```

Zone bitmask values: Zone 1=1, Zone 2=2, Zone 3=4, Zone 4=8, Zone 5=16, Zone 6=32

## Troubleshooting

### Cannot connect to device

- Verify the device IP hasn't changed (set a static IP in your router)
- Check the Local Key is current (it can change if you re-pair the device)
- Ensure the device is on the same network as Home Assistant

### Local Key changed

If you re-pair the device with any app, the Local Key changes. Get the new one from Tuya IoT Platform.

### Device not found on network scan

- Make sure the IIC-600 is powered on and connected to WiFi
- Run `python -m tinytuya scan` from a machine on the same network

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

The MIT License allows you to:
- ✅ Use this software for any purpose
- ✅ Copy, modify, and distribute it
- ✅ Include it in proprietary applications

The only requirement is to include the license and copyright notice.

## Disclaimer

This is an unofficial integration. Inkbird is not affiliated with this project. Use at your own risk.

## Credits

- Built for Home Assistant
- Uses [tinytuya](https://github.com/jasonacox/tinytuya) for local Tuya protocol communication
- First integration to provide local control of Inkbird irrigation controllers

---

**Questions or Issues?** [Open an issue on GitHub](https://github.com/ac-uy/ha-inkbird-irrigation/issues)

## Support

If you find this useful, consider buying me a coffee ☕ or some tokens 🤖:

[![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-pink?logo=github)](https://github.com/sponsors/ac-uy)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-blue.svg?style=flat-square&logo=paypal)](https://paypal.me/AndresCastro965?locale.x=es_ES&country.x=ES)
