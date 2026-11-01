// Wi-Fi uplink, for cameras hosted where a school or SACCO office network reaches the field.
#if defined(UPLINK_WIFI)

#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "config.h"
#include "uplink.h"

#if !defined(ROOT_CA_PEM) && !defined(ALLOW_INSECURE_TLS)
#error "Set ROOT_CA_PEM in secrets.h (or ALLOW_INSECURE_TLS for a bench test only)"
#endif

static WiFiClientSecure tls;

bool uplinkBegin() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > 30000) return false;
    delay(250);
  }
#if defined(ROOT_CA_PEM)
  tls.setCACert(ROOT_CA_PEM);
#else
  tls.setInsecure();                             // bench test only
#endif
  tls.setTimeout(30);
  return true;
}

bool uplinkSyncTime() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  uint32_t start = millis();
  while (time(nullptr) < 1704067200) {           // 1 January 2024
    if (millis() - start > 15000) return false;
    delay(200);
  }
  return true;
}

int uplinkSignalDbm() { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }

uint16_t uplinkBatteryMv() {
#if BATTERY_ADC_PIN >= 0
  uint32_t mv = analogReadMilliVolts(BATTERY_ADC_PIN);
  return (uint16_t)(mv * BATTERY_DIVIDER);
#else
  return 0;
#endif
}

static int post(const char *path, Stream *body, size_t len, const char *contentType, const Header *headers,
                size_t nHeaders) {
  HTTPClient http;
  if (!http.begin(tls, SERVER_HOST, SERVER_PORT, path, true)) return -1;
  http.setTimeout(30000);
  http.addHeader("Content-Type", contentType);
  for (size_t i = 0; i < nHeaders; i++) http.addHeader(headers[i].name, headers[i].value);
  int status = http.sendRequest("POST", body, len);
  http.end();
  return status;
}

int uplinkPostFile(const char *path, fs::File &body, size_t len, const char *contentType, const Header *headers,
                   size_t nHeaders) {
  return post(path, &body, len, contentType, headers, nHeaders);
}

int uplinkPostJson(const char *path, const String &body, const Header *headers, size_t nHeaders) {
  HTTPClient http;
  if (!http.begin(tls, SERVER_HOST, SERVER_PORT, path, true)) return -1;
  http.setTimeout(30000);
  http.addHeader("Content-Type", "application/json");
  for (size_t i = 0; i < nHeaders; i++) http.addHeader(headers[i].name, headers[i].value);
  int status = http.POST(body);
  http.end();
  return status;
}

void uplinkEnd() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

#endif  // UPLINK_WIFI
