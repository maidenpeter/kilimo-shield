// AgroShield sentinel field camera: wake, photograph the crop at the scheduled hours, queue the photo on the SD
// card, upload the queue (oldest first), report health, deep-sleep until the next slot.
//
// Device data is for checking satellite rainfall and reducing basis risk only. It never decides a payout.
#include <Arduino.h>
#include <SD_MMC.h>
#include <driver/rtc_io.h>
#include <esp_camera.h>
#include <esp_sleep.h>
#include <time.h>

#include "camera_pins.h"
#include "config.h"
#include "schedule.h"
#include "store.h"
#include "uplink.h"

// Kept in RTC memory through deep sleep (lost only when power is cut).
RTC_DATA_ATTR uint32_t photoSeq = 0;
RTC_DATA_ATTR int32_t doneDay = -1;
RTC_DATA_ATTR uint8_t doneMask = 0;
RTC_DATA_ATTR uint32_t wakeCount = 0;
RTC_DATA_ATTR uint16_t lastBatteryMv = 0;
RTC_DATA_ATTR uint16_t offlineWakes = 0;

static const int MAX_ERRORS = 6;
static String errors[MAX_ERRORS];
static int nErrors = 0;

static void note(const String &e) {
  Serial.println(e);
  if (nErrors < MAX_ERRORS) errors[nErrors++] = e;
}

static bool clockValid() { return time(nullptr) >= 1704067200; }   // 1 January 2024

static bool cameraBegin() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;
  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;
  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;
  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;
  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = PHOTO_FRAME_SIZE;
  c.jpeg_quality = PHOTO_JPEG_QUALITY;
  c.fb_count = 1;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  rtc_gpio_hold_dis(GPIO_NUM_32);
  if (esp_camera_init(&c) != ESP_OK) return false;
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    s->set_whitebal(s, 1);      // automatic white balance: greenness is a colour ratio
    s->set_awb_gain(s, 1);
    s->set_exposure_ctrl(s, 1);
  }
  return true;
}

static void cameraOff() {
  esp_camera_deinit();
  pinMode(PWDN_GPIO_NUM, OUTPUT);
  digitalWrite(PWDN_GPIO_NUM, HIGH);              // OV2640 powered down
  rtc_gpio_hold_en(GPIO_NUM_32);                   // and kept down through deep sleep
}

static bool takePhoto(uint32_t epoch) {
  for (int i = 0; i < WARMUP_FRAMES; i++) {
    camera_fb_t *warm = esp_camera_fb_get();
    if (warm) esp_camera_fb_return(warm);
  }
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    note("camera capture failed");
    return false;
  }
  bool ok = storePut(fb->buf, fb->len, epoch, ++photoSeq, lastBatteryMv);
  esp_camera_fb_return(fb);
  if (!ok) note("could not write the photo to the SD card");
  return ok;
}

static void uploadQueue() {
  std::vector<QueuedPhoto> batch = storeOldest(MAX_UPLOADS_PER_WAKE);
  for (const QueuedPhoto &p : batch) {
    File f = SD_MMC.open(p.path, FILE_READ);
    if (!f) {
      note("queued photo unreadable");
      storeReject(p);
      continue;
    }
    Header h[] = {{"X-Device-Id", String(DEVICE_ID)},
                  {"X-Device-Key", String(DEVICE_KEY)},
                  {"X-Msg-Id", messageId(p)},
                  {"X-Observed-At", String((unsigned long)p.epoch)},
                  {"X-Battery-mV", String(p.batteryMv)}};
    int status = uplinkPostFile(IMAGES_PATH, f, p.size, "image/jpeg", h, sizeof(h) / sizeof(h[0]));
    f.close();
    if (status == 200 || status == 201) {
      storeRemove(p);                                // stored, or already stored earlier (duplicate)
    } else if (status == 400 || status == 409 || status == 413 || status == 415 || status == 422) {
      storeReject(p);                                // refused for good: kept aside, not retried
      note("photo refused by the server (" + String(status) + ")");
    } else if (status == 401 || status == 403) {
      note("server refused the device key");
      return;
    } else {
      note("upload failed (" + String(status) + "); photos kept for the next wake");
      return;
    }
  }
}

static void sendHeartbeat(uint32_t epoch, int signalDbm, size_t queued) {
  String body = "{\"messages\":[{\"msg_id\":\"" + String(DEVICE_ID) + "-hb-" + String((unsigned long)epoch) +
                "\",\"observed_at\":" + String((unsigned long)epoch) + ",\"firmware\":\"" FIRMWARE_VERSION
                "\",\"readings\":{\"queue_depth\":" + String((unsigned long)queued);
  if (lastBatteryMv > 0) body += ",\"battery_v\":" + String(lastBatteryMv / 1000.0f, 3);
  if (signalDbm != 0) body += ",\"signal_dbm\":" + String(signalDbm);
  body += "},\"errors\":[";
  for (int i = 0; i < nErrors; i++) body += (i ? ",\"" : "\"") + errors[i] + "\"";
  body += "]}]}";
  Header h[] = {{"X-Device-Id", String(DEVICE_ID)}, {"X-Device-Key", String(DEVICE_KEY)}};
  uplinkPostJson(READINGS_PATH, body, h, 2);
}

static void sleepFor(uint32_t seconds) {
  Serial.printf("sleeping %lu s\n", (unsigned long)seconds);
  Serial.flush();
  esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  esp_deep_sleep_start();
}

void setup() {
  Serial.begin(115200);
  wakeCount++;
  bool sdOk = storeBegin();
  if (!sdOk) note("SD card missing or unreadable");

  bool online = false;
  if (!clockValid()) {                               // first boot, or power was lost: get the time first
    online = uplinkBegin();
    if (online) uplinkSyncTime();
  }
  if (!clockValid()) {
    if (online) uplinkEnd();
    sleepFor(RETRY_SLEEP_SECONDS);                   // a photo without a valid time would be refused
  }

  uint32_t now = (uint32_t)time(nullptr);
  int slot = dueSlot(now, doneDay, doneMask);
  if (slot >= 0) {
    if (cameraBegin()) {
      if (sdOk) takePhoto(now);
      else note("photo not kept: no SD card");
      cameraOff();
    } else {
      note("camera did not start");
    }
    if (doneDay != localDay(now)) {
      doneDay = localDay(now);
      doneMask = 0;
    }
    doneMask |= (uint8_t)(1 << slot);
  }

  if (!online) online = uplinkBegin();
  if (online) {
    uplinkSyncTime();                                // corrects the RTC drift of the sleep timer every wake
    uint16_t mv = uplinkBatteryMv();
    if (mv > 0) lastBatteryMv = mv;
    int dbm = uplinkSignalDbm();
    if (offlineWakes) note(String(offlineWakes) + " wakes without network since the last report");
    if (sdOk) {
      size_t dropped = storeTrim(QUEUE_MAX_FILES);
      if (dropped) note("SD queue full: " + String((unsigned long)dropped) + " oldest photos dropped");
      uploadQueue();
    }
    sendHeartbeat((uint32_t)time(nullptr), dbm, sdOk ? storeCount() : 0);
    offlineWakes = 0;
    uplinkEnd();
  } else {
    offlineWakes++;                                  // photos stay on the card for the next wake
  }
  sleepFor(secondsToNextSlot((uint32_t)time(nullptr)));
}

void loop() {}                                       // never reached: every wake ends in deep sleep
