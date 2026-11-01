// The path to the server: GSM (SIM800L through TinyGSM) or Wi-Fi, chosen at build time (platformio.ini).
#pragma once
#include <Arduino.h>
#include <FS.h>

struct Header {
  const char *name;
  String value;
};

bool uplinkBegin();                 // power up and attach (GPRS) or join (Wi-Fi)
bool uplinkSyncTime();              // set the system clock (network time or NTP); true when it is valid
int uplinkSignalDbm();              // 0 when unknown
uint16_t uplinkBatteryMv();         // 0 when unknown
// POST a body; returns the HTTP status code, or a negative number when the request did not complete.
int uplinkPostFile(const char *path, fs::File &body, size_t len, const char *contentType, const Header *headers,
                   size_t nHeaders);
int uplinkPostJson(const char *path, const String &body, const Header *headers, size_t nHeaders);
void uplinkEnd();                   // disconnect and power the modem down before deep sleep
