// ============================================================
//  Astro Band — прошивка браслета мониторинга (NASA Space Apps)
//  ESP32-S3-Zero (S3FH4R2) + GC9A01 + MAX30102 + MAX30205 + SCD41 + BMP390 + BMI270 + AD8232
//
//  Задачи FreeRTOS:
//    core 1: ecg (prio 6, 250 Гц) > sensors (prio 4, I2C) > ui (prio 2, 10 FPS)
//    core 0: net (prio 3, Wi-Fi + WSS)
//  Настройки — config.h, секреты — secrets.h, протокол сервера — protocol.cpp
// ============================================================
#include "config.h"
#include "ecg.h"
#include "log.h"
#include "net.h"
#include "sensors.h"
#include "state.h"
#include "ui.h"
#include "util.h"

void setup() {
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT && ARDUINO_USB_MODE
  // Без подключённого USB-хоста не блокируемся на выводе в Serial (питание от пауэрбанка)
  Serial.setTxTimeoutMs(0);
#endif
  delay(300);
  LOGI("Astro Band fw %s, heap %lu, psram %lu", FW_VERSION, static_cast<unsigned long>(ESP.getFreeHeap()),
       static_cast<unsigned long>(ESP.getFreePsram()));

  analogReadResolution(12);
  wdtSetup();

  Ui::begin();
  Ecg::start();
  Sensors::start();
  Ui::start();
  Net::start();
}

void loop() {
  vTaskDelete(nullptr);  // вся работа в задачах
}
