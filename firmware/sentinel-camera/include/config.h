// Sentinel camera settings. Per-device values (device id, key, APN, Wi-Fi, server certificate) live in
// include/secrets.h, which is never committed: copy secrets.example.h to secrets.h and fill it in.
#pragma once
#include <stdint.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"          // placeholders: builds, but the server will refuse the key
#endif

#define FIRMWARE_VERSION "cam-0.1.0"

// ---------------------------------------------------------------- server (AgroShield device ingestion API)
#ifndef SERVER_HOST
#define SERVER_HOST "devices.agroshield.example"   // placeholder host name
#endif
#ifndef SERVER_PORT
#define SERVER_PORT 443
#endif
#define IMAGES_PATH "/api/devices/v1/images"
#define READINGS_PATH "/api/devices/v1/readings"

// ---------------------------------------------------------------- schedule
// Local hours (East Africa Time, UTC+3) at which a photo is taken: 1 to 3 entries. Midday light gives the
// steadiest greenness readings; avoid early morning dew and low sun.
static const uint8_t PHOTO_HOURS[] = {10, 13};
static const uint8_t PHOTO_SLOTS = sizeof(PHOTO_HOURS) / sizeof(PHOTO_HOURS[0]);
#define UTC_OFFSET_SECONDS (3 * 3600)
#define SLOT_WINDOW_SECONDS (45 * 60)          // a wake up to 45 minutes after the slot still takes the photo
#define RETRY_SLEEP_SECONDS (60 * 60)          // no clock yet, or no network: try again in an hour
#define MIN_SLEEP_SECONDS 60

// ---------------------------------------------------------------- store and forward (SD card)
#define QUEUE_DIR "/queue"
#define REJECTED_DIR "/rejected"
#define QUEUE_MAX_FILES 400                    // about 130 days at 3 photos a day; the oldest are dropped first
#define MAX_UPLOADS_PER_WAKE 12                // bounds the time (and battery) one wake may spend uploading

// ---------------------------------------------------------------- camera
#define PHOTO_FRAME_SIZE FRAMESIZE_UXGA        // 1600 x 1200
#define PHOTO_JPEG_QUALITY 12                  // 0 best .. 63 worst
#define WARMUP_FRAMES 2                        // discarded while auto exposure settles

// ---------------------------------------------------------------- GSM modem (SIM800L through TinyGSM)
// With the SD card in 1-bit mode, GPIO 12 and 13 are free. GPIO 12 is a boot strapping pin, so it is used as
// the ESP32 TX (an output the modem never drives); GPIO 13 receives.
#define MODEM_RX_PIN 13
#define MODEM_TX_PIN 12
#define MODEM_BAUD 57600
// GPIO 4 drives the flash LED on the board; with the LED's transistor removed it switches the modem's
// power MOSFET (see docs/hardware/ENCLOSURE.md). -1 leaves the modem powered all the time.
#define MODEM_POWER_PIN 4
#ifndef GSM_APN
#define GSM_APN "internet"
#endif
#ifndef GSM_USER
#define GSM_USER ""
#endif
#ifndef GSM_PASS
#define GSM_PASS ""
#endif

// ---------------------------------------------------------------- battery
// The GSM build reads the battery through the modem (AT+CBC). The Wi-Fi build has no free ADC1 pin on the
// AI-Thinker board, so it reports no battery unless a divider is wired to BATTERY_ADC_PIN.
#define BATTERY_ADC_PIN -1
#define BATTERY_DIVIDER 2.0f
