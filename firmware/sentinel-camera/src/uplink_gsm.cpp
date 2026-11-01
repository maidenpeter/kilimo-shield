// GSM uplink: SIM800L through TinyGSM, TLS through the modem (TinyGsmClientSecure).
// Known limit: the SIM800L's own TLS stack is old and does not check the server certificate; see
// docs/hardware/KNOWN_ISSUES.md for the modem to prefer in the field.
#if defined(UPLINK_GSM)

#define TINY_GSM_RX_BUFFER 1024
#include <ArduinoHttpClient.h>
#include <TinyGsmClient.h>
#include <driver/rtc_io.h>
#include <sys/time.h>
#include <time.h>

#include "config.h"
#include "uplink.h"

#define SerialAT Serial1

static TinyGsm modem(SerialAT);
static TinyGsmClientSecure client(modem);
static HttpClient http(client, SERVER_HOST, SERVER_PORT);

bool uplinkBegin() {
#if MODEM_POWER_PIN >= 0
  rtc_gpio_hold_dis((gpio_num_t)MODEM_POWER_PIN);
  pinMode(MODEM_POWER_PIN, OUTPUT);
  digitalWrite(MODEM_POWER_PIN, HIGH);
  delay(3000);                                   // the SIM800L needs a moment after power is applied
#endif
  SerialAT.begin(MODEM_BAUD, SERIAL_8N1, MODEM_RX_PIN, MODEM_TX_PIN);
  delay(300);
  if (!modem.restart() && !modem.init()) return false;
  if (!modem.waitForNetwork(90000L)) return false;
  if (!modem.gprsConnect(GSM_APN, GSM_USER, GSM_PASS)) return false;
  http.setTimeout(30000);
  return true;
}

bool uplinkSyncTime() {
  modem.NTPServerSync("pool.ntp.org", 0);        // modem clock in UTC; harmless if the network has no NTP
  int y = 0, mo = 0, d = 0, h = 0, mi = 0, s = 0;
  float tz = 0;
  if (!modem.getNetworkTime(&y, &mo, &d, &h, &mi, &s, &tz) || y < 2024) return false;
  struct tm t = {};
  t.tm_year = y - 1900;
  t.tm_mon = mo - 1;
  t.tm_mday = d;
  t.tm_hour = h;
  t.tm_min = mi;
  t.tm_sec = s;
  setenv("TZ", "UTC0", 1);
  tzset();
  time_t epoch = mktime(&t) - (time_t)(tz * 3600.0f);
  struct timeval tv = {epoch, 0};
  settimeofday(&tv, nullptr);
  return true;
}

int uplinkSignalDbm() {
  int csq = modem.getSignalQuality();            // 0..31, 99 unknown
  if (csq <= 0 || csq == 99) return 0;
  return -113 + 2 * csq;
}

uint16_t uplinkBatteryMv() {
  int mv = modem.getBattVoltage();               // AT+CBC
  return mv > 0 ? (uint16_t)mv : 0;
}

static void sendHeaders(const char *contentType, size_t len, const Header *headers, size_t nHeaders) {
  http.sendHeader("Content-Type", contentType);
  http.sendHeader("Content-Length", (int)len);
  for (size_t i = 0; i < nHeaders; i++) http.sendHeader(headers[i].name, headers[i].value.c_str());
}

int uplinkPostFile(const char *path, fs::File &body, size_t len, const char *contentType, const Header *headers,
                   size_t nHeaders) {
  http.beginRequest();
  if (http.post(path) != 0) {
    http.stop();
    return -1;
  }
  sendHeaders(contentType, len, headers, nHeaders);
  http.beginBody();
  uint8_t buf[1024];
  size_t sent = 0;
  while (sent < len) {
    size_t n = body.read(buf, sizeof(buf));
    if (n == 0) break;
    if (http.write(buf, n) != n) break;
    sent += n;
  }
  http.endRequest();
  int status = sent == len ? http.responseStatusCode() : -2;
  http.stop();
  return status;
}

int uplinkPostJson(const char *path, const String &body, const Header *headers, size_t nHeaders) {
  http.beginRequest();
  if (http.post(path) != 0) {
    http.stop();
    return -1;
  }
  sendHeaders("application/json", body.length(), headers, nHeaders);
  http.beginBody();
  http.print(body);
  http.endRequest();
  int status = http.responseStatusCode();
  http.stop();
  return status;
}

void uplinkEnd() {
  modem.gprsDisconnect();
  modem.poweroff();
#if MODEM_POWER_PIN >= 0
  digitalWrite(MODEM_POWER_PIN, LOW);
  rtc_gpio_hold_en((gpio_num_t)MODEM_POWER_PIN); // keep the modem off through deep sleep
#endif
}

#endif  // UPLINK_GSM
