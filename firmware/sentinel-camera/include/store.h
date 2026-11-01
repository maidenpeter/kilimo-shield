// Store and forward queue on the SD card. Each photo is one file, named so that the oldest sorts first and
// the server message id can be rebuilt after any number of reboots:
//   /queue/<epoch, 10 digits>_<sequence, 6 digits>_<battery mV, 4 digits>.jpg
#pragma once
#include <Arduino.h>
#include <FS.h>
#include <vector>

struct QueuedPhoto {
  String path;          // full path on the card
  uint32_t epoch;       // when the photo was taken (UTC seconds)
  uint32_t seq;
  uint16_t batteryMv;   // 0 when unknown
  size_t size;
};

bool storeBegin();
bool storeReady();
bool storePut(const uint8_t *data, size_t len, uint32_t epoch, uint32_t seq, uint16_t batteryMv);
std::vector<QueuedPhoto> storeOldest(size_t max);
size_t storeCount();
bool storeRemove(const QueuedPhoto &p);
bool storeReject(const QueuedPhoto &p);   // the server refused it for good: keep it aside for a technician
size_t storeTrim(size_t maxFiles);        // drop the oldest beyond the limit; returns how many were dropped
String messageId(const QueuedPhoto &p);
