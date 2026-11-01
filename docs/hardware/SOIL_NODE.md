# Soil moisture node

Capacitive soil moisture sensors at two or three depths (default 10, 30 and 60 cm), a soil temperature probe, and a
LoRaWAN radio. It measures every hour and sends one compact uplink. Readings are for checking the satellite water
balance (and so basis risk), never for triggers.

Status: payload format, server decoder, network console decoder, webhook ingestion and calibration procedure are
built and tested. Node firmware is not written in this phase (the brief asked for the payload format, decoder,
ingestion and calibration notes); the byte layout below is what the firmware must send.

## LoRaWAN payload, version 1

FPort 1. All multi-byte fields are big-endian (most significant byte first). Length 11 + 3n bytes for n depths:
14 bytes for one depth, 17 for two, 20 for three, so it fits the smallest LoRaWAN payload size at the slowest data
rate in common band plans (check the plan used in Kenya before buying radios).

| Byte | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | version | 1 |
| 1-2 | u16 | sequence number | +1 per measurement, wraps at 65535 |
| 3-4 | u16 | age in minutes | 0 = measured now; above 0 = a stored reading sent late (store and forward) |
| 5 | u8 | flags | bit 0-2: sensor at depth 1-3 not responding; bit 3: temperature sensor fault; bit 4: battery low; bit 5: restarted since the last uplink; bit 6: more stored readings waiting |
| 6-7 | u16 | battery | millivolts; 0 = not measured |
| 8 | u8 | n | number of depths, 1 to 3 |
| 9 + 3k | u8 | depth k | centimetres |
| 10 + 3k | u16 | water content at depth k | 0.1 % steps (234 = 23.4 %); 0xFFFF = no reading |
| 9 + 3n | i16 | soil temperature | 0.01 C steps (1925 = 19.25 C); 0x7FFF = no reading |

Example (three depths, sequence 42, battery 3.612 V, 60 cm sensor not responding, restarted):
`01 002A 0000 24 0E1C 03 0A00EA 1E010E 3CFFFF 0785` decodes to 23.4 % at 10 cm, 27.0 % at 30 cm, nothing at 60 cm,
19.25 C. This exact example is a test (`tests/test_devices.py::test_payload_layout_and_round_trip`).

The rain gauge uses FPort 2 with the same header; see [RAIN_GAUGE.md](RAIN_GAUGE.md).

### Decoders

- Server: `src/agroshield_platform/devices/lorawan.py` decodes the raw bytes itself (`decode`), so the network server
  needs no formatter for ingestion to work.
- Network console: `firmware/soil-node/ttn_decoder.js` (The Things Stack custom JavaScript uplink formatter,
  `decodeUplink`). `tests/test_devices.py::test_ttn_javascript_decoder_matches_python` runs it under Node.js and checks
  it gives exactly the Python result.

### Ingestion and idempotency

The network server posts each uplink to `POST /api/devices/v1/lorawan/uplink` with the header `X-Integration-Key`
(from `python -m agroshield_platform.devices add-integration`). The Things Stack and ChirpStack uplink formats are both
accepted. The time measured is the network server's receive time minus the age field. The message id is
`lw<port>-<sequence>-<day measured>`; the identity hash leaves out the age and flags bytes and the radio signal, so a
reading the node sends again later (because it was not acknowledged) is recognised as the same reading and stored
once. A node that restarts and reuses a sequence number on the same day would be refused as a conflict, so the
firmware must keep the sequence number in non-volatile memory.

LoRaWAN devices do not hold an AgroShield device key: the network authenticates them with their own LoRaWAN session
keys, and the network server authenticates to AgroShield with the integration key (stored as a hash only).

## Calibration notes

Capacitive sensors report a raw count that depends on the soil, the sensor and its installation, not water content
directly. The node converts counts to volumetric water content (%) with a per-sensor calibration before sending.

1. **Bench check every sensor** before deployment: raw count in dry air and fully in water, at the node's supply
   voltage. Reject sensors whose counts fall outside the batch's spread; some low-cost boards ship with parts that
   misbehave at 3.3 V, so test the exact board revision.
2. **Soil-specific calibration** for each ward's soil: take soil from the site, pack it into containers at field bulk
   density, and wet it to at least four or five moisture levels from air-dry to saturated. At each level record the
   sensor count, then weigh, oven-dry (105 C, 24 hours) and weigh again to get gravimetric water content; multiply by
   bulk density to get volumetric content. Fit a line (or a quadratic if clearly curved) from count to volumetric
   content. Keep the fit, the samples and the date in the device's records.
3. **Temperature**: capacitive readings shift with soil temperature. Log temperature beside every reading (the payload
   carries it) so a correction can be fitted later from field data; none is applied yet.
4. **Installation**: insert each sensor horizontally into undisturbed soil at its depth from the side of a small pit,
   press soil firmly around it (air gaps read as dry), backfill in layers at the original density, and keep the
   electronics edge above any standing water. Bring cables up through a capped PVC pipe with strain relief.
5. **Checks in season**: after heavy rain the shallow sensor should rise first and the deep one later; a sensor that
   never responds to rain, or jumps without rain, is flagged for a visit. Recheck against a gravimetric sample at
   least once a season (drift, see [KNOWN_ISSUES.md](KNOWN_ISSUES.md)).

The server checks only physical range (0 to 100 %). Calibration constants live on the node in this design; moving them
to the server (sending raw counts) is an option if field recalibration becomes frequent.
