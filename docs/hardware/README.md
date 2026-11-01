# Hardware layer (milestone 9)

Field devices that help check the satellite rainfall index and show where it may miss what happened on the ground
(basis risk). **Device data is never a trigger source.** Triggers and payouts follow the satellite rainfall index in
the policy (`src/agroshield_pricing`, `src/agroshield_platform/monitoring.py`). Neither imports the device package,
and `tests/test_devices.py::test_pricing_triggers_and_payouts_never_import_the_device_module` keeps it that way, both
by reading the source and by importing those modules in a fresh interpreter. No single device, and no device a
farmer controls, can change a payout. The underwriter's Devices page says so at the top.

| Device | Measures | Path to the server | Files |
|---|---|---|---|
| Sentinel field camera (ESP32-CAM, OV2640) | 1 to 3 photos a day, greenness, battery, signal | HTTPS over GSM (SIM800L) or Wi-Fi | `firmware/sentinel-camera`, [SENTINEL_CAMERA.md](SENTINEL_CAMERA.md) |
| Soil moisture node | water content at 2 or 3 depths, soil temperature, battery | LoRaWAN (network server webhook), or HTTPS / MQTT | [SOIL_NODE.md](SOIL_NODE.md), `firmware/soil-node/ttn_decoder.js` |
| Rain gauge (tipping bucket) | bucket tips per interval, air temperature, battery | LoRaWAN, or HTTPS / MQTT | [RAIN_GAUGE.md](RAIN_GAUGE.md) |

Also: [BOM.md](BOM.md) (bill of materials), [ENCLOSURE.md](ENCLOSURE.md) (enclosures and mounting),
[KNOWN_ISSUES.md](KNOWN_ISSUES.md) (theft, power and signal, drift).

## Server side

Code: `src/agroshield_platform/devices/` (registry, ingest, greenness, lorawan, rain, mqtt) and
`src/agroshield_platform/web/devices.py` (routes). Tables (migration `0005_devices.py`): `device`, `device_message`,
`device_reading` (the time series), `device_image`, `device_issue`, `device_integration`.

### Registering a device

Platform staff, on the server:

    python -m agroshield_platform.devices register --uid CAM-A-01 --kind camera --ward ward-a \
        --site-type school --site-label "Primary school demonstration plot (fictional)"
    python -m agroshield_platform.devices register --uid SOIL-A-01 --kind soil --ward ward-a --site-type school \
        --site-label "..." --dev-eui 70B3D57ED0000001 --depths 10,30,60
    python -m agroshield_platform.devices register --uid RAIN-A-01 --kind rain --ward ward-a \
        --site-type sacco_office --site-label "..." --mm-per-tip 0.2
    python -m agroshield_platform.devices add-integration --name "network server"
    python -m agroshield_platform.devices list | rotate-key --uid X | retire --uid X

The device key is printed once. Only its SHA-256 hash is stored: the key is 256 random bits, so a plain hash is as
strong as a slow password hash and stays cheap on every upload. Labels name the host site, never a person (an ID or
phone number in a label is refused).

### Ingestion API

The device signs in with headers `X-Device-Id` and `X-Device-Key` (never in the URL). TLS only in deployment.

`POST /api/devices/v1/readings` with JSON:

    {"messages": [
      {"msg_id": "SOIL-A-01-1793520000", "observed_at": "2026-11-01T08:00:00Z",
       "readings": {"soil_vwc_10cm": 23.4, "soil_vwc_30cm": 27.0, "soil_temp_c": 19.2, "battery_v": 3.92},
       "errors": ["sensor at 60 cm not responding"], "firmware": "soil-0.1.0"}
    ]}

Up to 200 messages per request (store-and-forward catch-up sends many, oldest first). The answer lists each
message's status: `accepted`, `duplicate` (already stored: harmless), `conflict` (the same `msg_id` with different
content: not stored) or `rejected` (with reasons). The device drops a message from its queue on any of the four; it
keeps it only when the request itself failed (network error, 5xx).

`POST /api/devices/v1/images`: the JPEG as the body, with `X-Msg-Id`, `X-Observed-At` (Unix seconds or ISO 8601 with
zone) and optionally `X-Battery-mV`, `X-Signal-dBm`. 200 accepted or duplicate, 409 conflict, 413 over 3 MB, 422
refused (not a JPEG, too dark to measure, bad time).

`POST /api/devices/v1/lorawan/uplink`: a The Things Stack (v3) or ChirpStack (v4) uplink, with the header
`X-Integration-Key`. The device is found by its DevEUI; the payload is decoded on the server.

MQTT: `python -m agroshield_platform.devices mqtt-bridge --host ... --port 8883 --ca ca.pem` subscribes to
`agroshield/v1/devices/+/up` (payload: `{"key": ..., "messages": [...]}`) and answers on `.../<id>/ack`. paho-mqtt is
an optional dependency (`pip install "agroshield[hardware]"`).

### Validation

| Reading | Range | Devices |
|---|---|---|
| `soil_vwc_<depth>cm` (depth 1 to 200) | 0 to 100 % | soil |
| `soil_temp_c` | -10 to 70 | soil |
| `air_temp_c` | -15 to 60 | camera, rain |
| `rain_tips` with `interval_min` (1 to 1440) | 0 to 10,000 tips | rain; stored with `rain_mm` = tips x the gauge's mm per tip |
| `battery_v` | 2.5 to 15 V | all |
| `signal_dbm` | -140 to 0 | all |
| `queue_depth` | 0 to 100,000 | all |
| `greenness_gcc`, `greenness_exg`, `green_fraction` | computed on the server from each photo | camera |

Times must carry a zone, must not be in the future (10 minutes of clock drift allowed), not before 2024 (an unset
device clock) and not more than 90 days old (the store-and-forward window). A message that fails any check is refused
whole and noted on the device's page.

### Health

From the last message received and the device's report interval (camera 720 minutes, soil and rain 60, set per
device): **Reporting**; **Late** after two intervals; **Not heard from** after six intervals or 24 hours, whichever is
longer; **Never reported**. Battery is "low" under the device's threshold (camera 3.45 V, others 3.3 V; DRAFT). A batch
caught up after an outage never overwrites the newest battery or signal reading.

### Greenness

Per usable pixel r, g, b = R, G, B / (R+G+B). `gcc` is the mean g (about 0.33 for grey), `exg` the mean 2g - r - b,
and `green_fraction` the share of pixels with 2g - r - b above 0.10 (DRAFT threshold). Near-black and blown-out pixels
are left out; a photo with under 5% usable pixels is refused as too dark. Compare a camera with itself over the
season, at the same hour, not one camera with another.

## Underwriter pages

`/uw/devices` lists every device in the pilot wards, with wards where the underwriter's insurer has cover first
(decision 4.1). `/uw/devices/<id>` shows the device's facts, health, a 30-day chart and daily table, the CHIRPS check
(rain gauges), the latest photos (cameras), problems and the latest messages. Photos are served only to signed-in
underwriters.

## Simulator

`python tools/devices/simulate.py --in-process --days 10` runs a fictional fleet (per ward: camera, soil node, rain
gauge) through the real API on a temporary database: rain storms, soil drying, crop greening, battery drain, a two-day
outage with store-and-forward catch-up, a resent message and a faulty 150% soil reading.
`tests/test_device_simulator.py` runs it for 6 days and checks the stored data and the pages.

Against a running portal: register devices with `--json`, collect the output in a JSON list, then
`python tools/devices/simulate.py --base-url http://127.0.0.1:8000 --keys keys.json [--integration-key K]`.
