#pragma once
#include <Arduino.h>
#include <esp_task_wdt.h>
#include <esp_arduino_version.h>
#include "config.h"

// Task watchdog: если задача сенсоров или UI зависнет (например, на I2C) — перезагрузка.
inline void wdtSetup() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t cfg = {};
  cfg.timeout_ms     = WDT_TIMEOUT_MS;
  cfg.idle_core_mask = 0;      // idle-задачи не следим: TLS-handshake может надолго занять ядро 0
  cfg.trigger_panic  = true;
  if (esp_task_wdt_reconfigure(&cfg) != ESP_OK) esp_task_wdt_init(&cfg);
#else
  esp_task_wdt_init(WDT_TIMEOUT_MS / 1000, true);
#endif
}

inline void wdtAddThisTask() { esp_task_wdt_add(nullptr); }
inline void wdtFeed() { esp_task_wdt_reset(); }

inline uint32_t umin(uint32_t a, uint32_t b) { return a < b ? a : b; }
