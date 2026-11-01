# Phase 4: hardware layer (milestone 9)

Branch `work/phase4-hardware`, from main at 73a377e. Migration `0005` (`0005_devices.py`), written against `0003`; the
integrator re-points `down_revision` to main's `0004` (photos). New tables only.

**Device data is for checking the satellite index and reducing basis risk only. It is never a trigger source.**
The pricing package and the trigger and payout code do not import the device package (a test reads the source and
imports those modules in a fresh interpreter), and the underwriter's Devices pages say so at the top.

## What was built

| Part | Where | State |
|---|---|---|
| Device registry: per-device key (shown once, SHA-256 hash only), rotate, retire; LoRaWAN network server integrations | `src/agroshield_platform/devices/registry.py`, `python -m agroshield_platform.devices` | Built, tested |
| Ingestion over HTTPS: readings batches (`/api/devices/v1/readings`) and camera photos (`/api/devices/v1/images`) | `devices/ingest.py`, `web/devices.py` | Built, tested |
| Ingestion over MQTT: bridge subscribing to `agroshield/v1/devices/+/up`, answers on `.../ack` | `devices/mqtt.py` | Built, tested with a stand-in client (no live broker) |
| Ingestion over LoRaWAN: The Things Stack and ChirpStack uplink webhook (`/api/devices/v1/lorawan/uplink`) | `devices/lorawan.py` | Built, tested |
| Validation (ranges per reading and device kind, timestamps) and idempotency (device message id; duplicate vs conflict) | `devices/ingest.py` | Built, tested |
| Time-series storage: `device_message`, `device_reading`, `device_image`, `device_issue` | `models.py` (milestone 9 block), migration 0005 | Built, tested (models equal migrations) |
| Device health: last heard from, battery (low flag), signal, problems, messages sent late | `devices/ingest.py` | Built, tested |
| Underwriter pages `/uw/devices` and `/uw/devices/<id>` (+ photos), "Devices" in the underwriter nav | `web/devices.py`, `uw_devices.html`, `uw_device.html`, `base.html` | Built, tested at 1280 px and 375 px |
| Sentinel camera firmware (ESP32-CAM, OV2640): schedule, 1 to 3 photos a day, SD store-and-forward, GSM (SIM800L via TinyGSM) or Wi-Fi, deep sleep | `firmware/sentinel-camera` | Compiles (both environments); not run on hardware |
| Greenness index per photo (green chromatic coordinate, excess green, plant share) | `devices/greenness.py` | Built, tested |
| Soil moisture node: binary LoRaWAN payload (documented bytes), Python decoder, TTN JavaScript decoder, calibration notes | `devices/lorawan.py`, `firmware/soil-node/ttn_decoder.js`, `docs/hardware/SOIL_NODE.md` | Built, tested (JS and Python agree) |
| Rain gauge: tips to mm (per-gauge mm per tip), CHIRPS outlier flags, TAHMO adapter interface | `devices/rain.py`, `docs/hardware/RAIN_GAUGE.md` | Built, tested; TAHMO Blocked |
| Device simulator | `tools/devices/simulate.py` | Built; a test runs it end to end |
| Docs: overview and API, camera, soil node, rain gauge, bill of materials, enclosures, known issues | `docs/hardware/` | Written (BOM and enclosure notes DRAFT) |

## Results from runs in this phase

Firmware, `pio run -e esp32cam -e esp32cam-wifi` on 1 November 2026 (PlatformIO 6.2.0 installed into the venv,
platform espressif32 6.9.0, Arduino core 3.20017.241212, TinyGSM 0.12.0, ArduinoHttpClient 0.6.1):

| Environment | Result | RAM | Flash |
|---|---|---|---|
| esp32cam (GSM) | SUCCESS | 29,656 of 327,680 bytes (9.1%) | 504,205 of 3,145,728 bytes (16.0%) |
| esp32cam-wifi | SUCCESS | 52,196 of 327,680 bytes (15.9%) | 1,101,377 of 3,145,728 bytes (35.0%) |

The first Wi-Fi build failed: on Windows, ArduinoHttpClient's `HttpClient.h` shadowed the core's `HTTPClient.h`
(case-insensitive file system). Fixed by giving only the GSM environment the GSM libraries.

Simulator, `python tools/devices/simulate.py --in-process --days 10` (seed 7, ending 2026-11-01 15:00 UTC): 1,039
requests; 1,036 messages accepted, 2 duplicates (the resent first message after each catch-up, stored once) and 1
rejected (the deliberate 150% soil reading). The ward-a camera caught up 4 photos and the ward-a soil node 48 hourly
readings after a two-day outage. Simulated rain (not real data): ward-a 15.5 mm, ward-b 55.2 mm over the 10 days.
About 40 seconds on this machine with the scratch database settings described in the simulator.

## Tests

New: `tests/test_devices.py` (19 tests) and `tests/test_device_simulator.py` (3 tests, the simulator over 6 days
against the app through FastAPI's TestClient). Changed: `tests/test_navbar.py` (the underwriter's link list now ends
with Devices). Full suite on the final code: 361 passed in 869.61 s (`python -m pytest -q`, browser tests included).

Note for anyone running the suite in a fresh worktree: `tests/test_uw.py::test_pricing_runs_and_reports` needs the
pricing run folders under `runs/`, which are git-ignored and so absent from a new checkout. It failed for that reason
only; with the folders copied from the main tree (not committed) it passes. Not caused by this phase.

## Blocked

- **TAHMO station data.** Needs a TAHMO API account (username and password or token) issued under a data-sharing
  agreement with TAHMO, plus the codes of the stations nearest each pilot ward. Nobody signed up or made contact (brief).
  Built instead: `rain.TahmoAdapter`, a labelled stub with the same interface as the CHIRPS source, raising
  `TahmoBlocked` with this text; no network call. To unblock: set `TAHMO_API_USER` and `TAHMO_API_PASSWORD`, add station
  codes to gauge settings and implement `TahmoAdapter.daily` against TAHMO's API documentation.
- **Hardware testing.** No board was available. The camera firmware compiles; deep-sleep current, the modem power
  switch, SD behaviour at low battery and a full queue catch-up need a bench test before the field.

Not blocked, but not built (outside what the brief asked): soil node and rain gauge firmware (the payload format they
must send is specified and decoded), a web screen for registering devices (a command for now), and a live MQTT broker
test.

## Decisions (defaults used)

Listed in full in `docs/DECISIONS_LOG.md` under "Phase 4". In short:

1. Underwriters see every pilot-ward device; wards where their insurer has cover come first (pending owner confirmation).
2. New credential type for devices (officer auth and roles unchanged): per-device 256-bit key, SHA-256 hash only, sent in
   headers over TLS or in the MQTT payload, never in a URL. LoRaWAN devices are authenticated by the network; the
   network server uses an integration key (hash only).
3. Idempotency on device and message id; "duplicate" is harmless, "conflict" is not stored.
4. Validation window: up to 10 minutes in the future, not before 2024, at most 90 days old; any bad value refuses the
   whole message.
5. Health: late after two report intervals, "Not heard from" after six or 24 hours; battery low 3.45 V camera, 3.3 V
   others (DRAFT).
6. Greenness: green chromatic coordinate, excess green, plant share above 0.10 (DRAFT).
7. Photos stored as files next to the database or in `AGROSHIELD_DEVICE_STORE`, shown only to underwriters; retention
   needs approval.
8. CHIRPS check on 10-day totals (30 mm and factor 3) plus a single-day check (DRAFT); flags never change data.
9. Camera photos at 10:00 and 13:00 EAT; GSM by default, Wi-Fi build available.
10. Device administration through `python -m agroshield_platform.devices`, leaving `cli.py` untouched.
11. Underwriter nav links use 8 px side padding so eight links fit (app.css).

## Shared files touched

- `src/agroshield_platform/models.py`: milestone 9 models appended at the end (with their own `Index` import).
- `src/agroshield_platform/web/app.py`: three lines registering `web/devices.py`.
- `src/agroshield_platform/web/templates/base.html`: "Devices" in the underwriter nav.
- `src/agroshield_platform/web/static/app.css`: tighter link padding for the underwriter bar only.
- `pyproject.toml`: optional extra `hardware = ["paho-mqtt>=2"]`.
- `.gitignore`: firmware build output and per-device `secrets.h`.
- `tests/test_navbar.py`, `docs/DECISIONS_LOG.md`.

## Commits

- `335cc0e` device registry, ingestion API (HTTPS, MQTT, LoRaWAN), readings and photos, health, underwriter Devices page
- `f3ca971` sentinel camera firmware, soil node decoder, device simulator, hardware docs, decisions
- the commit adding this report

## Review (1 November 2026)

A second pass checked the claims above by running them again from a worktree with the import path pointing at its
own `src/`.

Reproduced:

- Simulator, `python tools/devices/simulate.py --in-process --days 10` (seed 7, ending 2026-11-01 15:00 UTC): 1,039
  requests, 1,036 accepted, 2 duplicates, 1 rejected; catch-up of 4 photos (CAM-A-01) and 48 readings (SOIL-A-01);
  simulated rain 15.5 mm (ward-a) and 55.2 mm (ward-b). Same as above, in about 31 seconds.
- Firmware, `pio run -e esp32cam -e esp32cam-wifi`: both SUCCESS with the same RAM and flash figures as above.
- Pricing, index, trigger and payout code, the hashed config files, crypto, services, M-Pesa, settlement,
  underwriting and migrations 0001 to 0003 are unchanged against 73a377e (`git diff --stat` is empty for them).
- No em dashes in the new pages, docs, firmware or tools.

Fixed in the commit "Phase 4 review fixes":

- **A LoRaWAN reading resent across midnight UTC was stored twice.** The age field is in whole minutes. A reading
  measured at 23:59:40 UTC and resent 30.5 minutes later (age 30) got a time just after midnight, and so the next
  day's message id. A probe showed 10 mm of rain stored as 20 mm. The server now also looks for the same reading
  under the neighbouring day's id (within 10 minutes) and answers "duplicate". New test:
  `test_lorawan_resend_across_midnight_is_stored_once`.
- **The Wi-Fi camera could go to the field without checking the server certificate.** `secrets.example.h` turned on
  `ALLOW_INSECURE_TLS`, so a `secrets.h` copied from it got past the build's guard. The template no longer sets it.
  Only the placeholder build (no `secrets.h`) allows it. An unedited copy now stops the `esp32cam-wifi` build with
  the "Set ROOT_CA_PEM" error (checked by building it). The placeholder build still compiles.
- The device list said "mm today" for a rolling 24-hour total. It now says "mm in 24 hours". The note under the
  heading said devices "are hosted" at schools and SACCO offices. It now says "the plan is to host" them, because
  none are deployed yet.
- `register --json` now also prints the ward and DevEUI, which `simulate.py --keys` reads. Before, every device fell
  back to ward-a. The README example's `observed_at` now matches the time in its message id.

Full suite after the fixes: 362 passed in 624.69 s. As noted above, the git-ignored `runs/` folders were copied in
from the main tree for `test_uw.py::test_pricing_runs_and_reports`.

Still open (not fixed in review):

- **Camera wiring needs a bench check.** GPIO 12 (modem TX) is a boot strapping pin. If the modem side pulls it high
  at power-on, the ESP32 picks the wrong flash voltage and does not boot. The SIM800L's serial lines run at 2.8 V, so
  the 3.3 V TX line may need a level shifter. Neither has been tried on a board.
- **SIM800L TLS.** KNOWN_ISSUES already lists this (no certificate check). Also check on the bench that the module can
  make a TLS connection the production server accepts at all.
- **LoRaWAN catch-up rate.** The simulator sends 48 stored soil readings in one burst after an outage. Real node
  firmware (not written yet) has to spread a backlog over time to stay within the network's duty-cycle and fair-use
  limits.
- **Merge note.** The app.css rule that tightens the underwriter nav assumes eight links. If main's Phase 3 changes
  the underwriter nav, run `tests/test_navbar.py` again after the merge.
- Decision 4.1 (who sees which devices) still needs owner confirmation, photo retention still needs approval, and
  TAHMO is still Blocked.
