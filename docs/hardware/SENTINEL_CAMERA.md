# Sentinel field camera (ESP32-CAM, OV2640)

PlatformIO firmware in `firmware/sentinel-camera`. The camera watches a demonstration plot at a host site (a school
or a SACCO office), photographs the crop at fixed hours, and the server turns each photo into a greenness index. It
shows how the crop is doing on the ground next to what the satellite index says. It never decides a payout.

## What one wake does

1. Mount the SD card (1-bit mode). If the clock is not set (first boot, or power was lost), bring up the uplink and
   set the clock from the network (GSM network time after an NTP sync on the modem, or NTP over Wi-Fi). Without a
   valid clock it sleeps an hour and tries again: a photo without a trustworthy time would be refused by the server.
2. If a photo slot is due (default 10:00 and 13:00 East Africa Time, set in `include/config.h`, 1 to 3 slots, each open
   for 45 minutes), take a photo (two warm-up frames first, for exposure), write it to the SD queue as
   `/queue/<epoch>_<sequence>_<battery mV>.jpg` (written as `.part` and renamed, so a brown-out never leaves half a
   file in the queue), then power the camera down.
3. Bring up the uplink, correct the clock again (the sleep timer drifts), read battery and signal.
4. Upload the queue oldest first, at most 12 photos per wake. Each upload is idempotent: the message id is
   `<device>-<epoch>-<sequence>`, rebuilt from the file name after any number of reboots. 200 (accepted or duplicate):
   delete. 400, 409, 413, 415, 422 (refused for good): move to `/rejected` for a technician. 401 or 403: stop (key
   problem). Anything else: stop and keep the rest for the next wake.
5. Send a heartbeat (`/api/devices/v1/readings`): battery, signal, queue depth, firmware version and any errors noted
   during the wake (SD card missing, camera did not start, uploads failed, wakes without network, oldest photos
   dropped because the queue was full).
6. Power the modem off (held off through deep sleep), then deep-sleep until the next slot.

The queue holds up to 400 photos (about 130 days at 3 a day); beyond that the oldest are dropped and reported.

## Build

    pip install platformio
    cd firmware/sentinel-camera
    cp include/secrets.example.h include/secrets.h     # per device: id, key, APN, Wi-Fi, server certificate
    pio run -e esp32cam          # GSM uplink (SIM800L through TinyGSM 0.12.0, ArduinoHttpClient 0.6.1)
    pio run -e esp32cam-wifi     # Wi-Fi uplink
    pio run -e esp32cam -t upload

Build result on 1 November 2026 (this phase, platform espressif32 6.9.0, Arduino core 3.20017.241212, with the
placeholder `secrets.example.h`):

| Environment | Result | RAM | Flash |
|---|---|---|---|
| esp32cam (GSM) | SUCCESS | 29,656 of 327,680 bytes (9.1%) | 504,205 of 3,145,728 bytes (16.0%) |
| esp32cam-wifi | SUCCESS | 52,196 of 327,680 bytes (15.9%) | 1,101,377 of 3,145,728 bytes (35.0%) |

Not tested on hardware: no board was available in this phase. Bench test before the field: deep-sleep current,
the modem power switch, SD card behaviour at low battery, and a full queue catch-up.

`secrets.h` is git-ignored. With `secrets.example.h` the firmware builds but the server refuses its placeholder key.

## Wiring (AI-Thinker ESP32-CAM)

| Signal | ESP32 pin | Note |
|---|---|---|
| OV2640 camera | fixed on the board | power-down pin GPIO 32, held high through deep sleep |
| microSD | GPIO 14 (CLK), 15 (CMD), 2 (D0) | 1-bit mode, which frees GPIO 4, 12 and 13 |
| Modem RX (ESP32 TX) | GPIO 12 | GPIO 12 is a boot strapping pin; as an ESP32 output the modem never drives it |
| Modem TX (ESP32 RX) | GPIO 13 | |
| Modem power switch | GPIO 4 | normally the flash LED: remove the LED's driver transistor, and drive the gate of the modem's power MOSFET instead |
| Battery (Wi-Fi build) | `BATTERY_ADC_PIN`, default none | the board has no free ADC1 pin; the GSM build reads the battery through the modem (AT+CBC) |

The SIM800L needs its own supply that can deliver about 2 A bursts at 3.4 to 4.4 V (straight from a lithium cell
through the MOSFET, with a large capacitor next to the module), not the ESP32-CAM's 3.3 V regulator.

## Choosing GSM or Wi-Fi

GSM (default) works anywhere with 2G coverage and a data SIM. Check 2G coverage at each site and the network's plans
to switch 2G off before buying SIM800L modules; a 4G Cat-1 modem supported by TinyGSM (for example the SIM7600
family) avoids that risk and gives proper TLS (see [KNOWN_ISSUES.md](KNOWN_ISSUES.md)). Wi-Fi suits a camera within
reach of the host school or SACCO office network.
