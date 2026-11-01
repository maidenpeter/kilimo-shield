# Rain gauge (tipping bucket)

A tipping-bucket gauge with a reed switch. Each tip is a fixed depth of rain; the node counts tips (interrupt with
debounce) and reports the count per interval. Readings are for checking the satellite rainfall (CHIRPS) and spotting
basis risk and broken gauges, never for triggers.

## Tips to millimetres

`rain_mm = tips x mm_per_tip`, where `mm_per_tip` is set per gauge at registration (`--mm-per-tip`, default 0.2 mm).
Both the tip count and the millimetres are stored, so a later recalibration can recompute the history.

**Calibrate each gauge** before deployment and once a season: level the gauge, pour a known volume of water slowly
through the funnel (a rate like steady rain), count the tips, and compute mm per tip = volume / funnel area / tips.
Repeat three times. Tipping buckets under-count in very heavy rain (water is lost while the bucket tips), so also
check at a fast pour rate and record the difference.

## Payload

LoRaWAN FPort 2, 14 bytes, big-endian, version 1:

| Byte | Type | Field |
|---|---|---|
| 0 | u8 | version (1) |
| 1-2 | u16 | sequence number |
| 3-4 | u16 | age in minutes (store and forward) |
| 5 | u8 | flags: bit 0 reed switch fault, bit 3 temperature sensor fault, bit 4 battery low, bit 5 restarted, bit 6 more stored readings waiting |
| 6-7 | u16 | battery, millivolts |
| 8-9 | u16 | tips counted in the interval |
| 10-11 | u16 | interval length, minutes |
| 12-13 | i16 | air temperature, 0.01 C (0x7FFF = no reading) |

Over HTTPS or MQTT the same reading is `{"rain_tips": 12, "interval_min": 60, "air_temp_c": 21.5, "battery_v": 3.58}`.

## Check against CHIRPS (built)

`src/agroshield_platform/devices/rain.py`, shown on the gauge's page. It uses the ward CHIRPS daily files already in
the repo (`data/raw/chirps/ward-a.csv`, `ward-b.csv`: 1 January 1981 to 31 December 2025). A point gauge and a
satellite pixel average differ a lot day to day, so the check compares 10-day totals (dekads) and flags only large
gaps. Thresholds are DRAFT, to be tuned once a season of gauge data is in.

| Flag | Rule | Applies when |
|---|---|---|
| Much wetter than the satellite | gauge - CHIRPS > 30 mm and gauge > 3 x CHIRPS over the dekad | CHIRPS covers the dekad and the gauge reported every day of it |
| Much drier than the satellite | CHIRPS - gauge > 30 mm and gauge < CHIRPS / 3 | as above |
| Possible blocked funnel | as "much drier", with 0 mm at the gauge | as above |
| Unusually heavy day | a day above twice the wettest CHIRPS day on record for that ward and calendar month | always |

Because the repo's CHIRPS files end on 31 December 2025, current-season gauge days get only the single-day check until
newer CHIRPS data is fetched (the pricing package's CHIRPS fetcher). A flag is for a person to look at: it never
changes a reading, an index or a payout.

## TAHMO adapter: Blocked

`rain.TahmoAdapter` is the interface for TAHMO station data (daily rainfall per station, the same shape as the CHIRPS
source), so a gauge can also be cross-checked against the nearest TAHMO station. It is a labelled stub that raises
`TahmoBlocked` and makes no network call.

What is needed to unblock: a TAHMO API account (username and password or token) issued under a data-sharing agreement
with TAHMO, and the codes of the TAHMO stations nearest each pilot ward. Per the brief nobody has signed up or
contacted TAHMO. Once the agreement exists: set `TAHMO_API_USER` and `TAHMO_API_PASSWORD` in the environment, record the
station codes in the gauge's settings, and implement `TahmoAdapter.daily` against TAHMO's API documentation.
