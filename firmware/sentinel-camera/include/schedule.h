// Photo schedule: pure functions of the time, so they are easy to check by hand.
#pragma once
#include <stdint.h>

#include "config.h"

inline int32_t localDay(uint32_t epoch) { return (int32_t)((epoch + UTC_OFFSET_SECONDS) / 86400UL); }
inline uint32_t localSecondOfDay(uint32_t epoch) { return (epoch + UTC_OFFSET_SECONDS) % 86400UL; }

// The slot due now (inside its window and not yet taken today), or -1.
inline int dueSlot(uint32_t epoch, int32_t doneDay, uint8_t doneMask) {
  uint8_t mask = doneDay == localDay(epoch) ? doneMask : 0;
  uint32_t sod = localSecondOfDay(epoch);
  for (uint8_t i = 0; i < PHOTO_SLOTS; i++) {
    uint32_t start = (uint32_t)PHOTO_HOURS[i] * 3600UL;
    if (sod >= start && sod < start + SLOT_WINDOW_SECONDS && !(mask & (1 << i))) return i;
  }
  return -1;
}

// Seconds from `epoch` to the start of the next slot (today or tomorrow).
inline uint32_t secondsToNextSlot(uint32_t epoch) {
  uint32_t sod = localSecondOfDay(epoch);
  uint32_t best = 86400UL;
  for (uint8_t i = 0; i < PHOTO_SLOTS; i++) {
    uint32_t start = (uint32_t)PHOTO_HOURS[i] * 3600UL;
    uint32_t wait = start > sod ? start - sod : start + 86400UL - sod;
    if (wait < best) best = wait;
  }
  return best < MIN_SLEEP_SECONDS ? MIN_SLEEP_SECONDS : best;
}
