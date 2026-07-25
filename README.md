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
- 📡 **Connection mode sensor** — shows whether running on local or cloud

## Supported Devices

- **Inkbird IIC-600-WIFI** (6-zone sprinkler controller)
- **Inkbird IIC-800-WIFI** (8-zone, untested but likely compatible)

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
| `sensor.inkbird_iic_600_connection_mode` | Sensor | Connection mode (local/cloud) |

## Cloud Fallback (Optional)

The device's local Tuya protocol can occasionally become unresponsive (error 914). To prevent the integration from going unavailable, you can provide optional Tuya Cloud API credentials during setup.

**How it works:**
1. Integration uses local connection (fastest, ~50ms)
2. If local fails 2 consecutive times → automatically switches to cloud API (~300ms)
3. Periodically retries local in the background
4. When local recovers → switches back automatically

**To enable cloud fallback**, provide these optional fields during setup:
- **Cloud API Key** — from your Tuya IoT Platform project
- **Cloud API Secret** — from your Tuya IoT Platform project  
- **Cloud API Region** — `eu`, `us`, `cn`, etc.

Without cloud credentials, the integration works local-only (original behavior).

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

- **Protocol**: Tuya local protocol v3.4
- **Communication**: Direct LAN (UDP/TCP on device IP)
- **Polling interval**: 15 seconds
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
