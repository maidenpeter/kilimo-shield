#include "store.h"

#include <SD_MMC.h>
#include <algorithm>

#include "config.h"

static bool ready = false;

bool storeBegin() {
  // 1-bit mode frees GPIO 4, 12 and 13 (the flash LED and the modem UART use them).
  if (!SD_MMC.begin("/sdcard", true)) {
    ready = false;
    return false;
  }
  if (SD_MMC.cardType() == CARD_NONE) {
    ready = false;
    return false;
  }
  if (!SD_MMC.exists(QUEUE_DIR)) SD_MMC.mkdir(QUEUE_DIR);
  if (!SD_MMC.exists(REJECTED_DIR)) SD_MMC.mkdir(REJECTED_DIR);
  ready = true;
  return true;
}

bool storeReady() { return ready; }

bool storePut(const uint8_t *data, size_t len, uint32_t epoch, uint32_t seq, uint16_t batteryMv) {
  if (!ready) return false;
  char path[64];
  snprintf(path, sizeof(path), "%s/%010lu_%06lu_%04u.jpg", QUEUE_DIR, (unsigned long)epoch,
           (unsigned long)(seq % 1000000UL), (unsigned)(batteryMv > 9999 ? 9999 : batteryMv));
  String tmp = String(path) + ".part";       // written under a temporary name, renamed when complete
  File f = SD_MMC.open(tmp, FILE_WRITE);
  if (!f) return false;
  size_t written = f.write(data, len);
  f.close();
  if (written != len) {
    SD_MMC.remove(tmp);
    return false;
  }
  return SD_MMC.rename(tmp, path);
}

static bool parseName(const String &name, QueuedPhoto &out) {
  // <epoch>_<seq>_<mv>.jpg
  unsigned long epoch = 0, seq = 0;
  unsigned mv = 0;
  if (!name.endsWith(".jpg")) return false;
  if (sscanf(name.c_str(), "%10lu_%6lu_%4u.jpg", &epoch, &seq, &mv) != 3) return false;
  out.epoch = epoch;
  out.seq = seq;
  out.batteryMv = mv;
  return true;
}

static std::vector<QueuedPhoto> listAll() {
  std::vector<QueuedPhoto> all;
  if (!ready) return all;
  File dir = SD_MMC.open(QUEUE_DIR);
  if (!dir || !dir.isDirectory()) return all;
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    if (f.isDirectory()) continue;
    String name = f.name();
    int slash = name.lastIndexOf('/');
    if (slash >= 0) name = name.substring(slash + 1);
    QueuedPhoto p;
    if (parseName(name, p)) {
      p.path = String(QUEUE_DIR) + "/" + name;
      p.size = f.size();
      all.push_back(p);
    } else if (name.endsWith(".part")) {
      String stale = String(QUEUE_DIR) + "/" + name;   // a write cut off by a brown-out
      f.close();
      SD_MMC.remove(stale);
    }
  }
  std::sort(all.begin(), all.end(), [](const QueuedPhoto &a, const QueuedPhoto &b) {
    return a.epoch != b.epoch ? a.epoch < b.epoch : a.seq < b.seq;
  });
  return all;
}

std::vector<QueuedPhoto> storeOldest(size_t max) {
  std::vector<QueuedPhoto> all = listAll();
  if (all.size() > max) all.resize(max);
  return all;
}

size_t storeCount() { return listAll().size(); }

bool storeRemove(const QueuedPhoto &p) { return SD_MMC.remove(p.path); }

bool storeReject(const QueuedPhoto &p) {
  String name = p.path.substring(p.path.lastIndexOf('/') + 1);
  return SD_MMC.rename(p.path, String(REJECTED_DIR) + "/" + name);
}

size_t storeTrim(size_t maxFiles) {
  std::vector<QueuedPhoto> all = listAll();
  size_t dropped = 0;
  for (size_t i = 0; all.size() - i > maxFiles; i++) {
    if (SD_MMC.remove(all[i].path)) dropped++;
  }
  return dropped;
}

String messageId(const QueuedPhoto &p) {
  // Stable across retries and reboots, so the server stores each photo once (idempotent uploads).
  return String(DEVICE_ID) + "-" + String((unsigned long)p.epoch) + "-" + String((unsigned long)p.seq);
}
