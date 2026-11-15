#include "ecg.h"
#include <atomic>
#include "config.h"
#include "log.h"
#include "state.h"

#if configTICK_RATE_HZ != 1000
#warning "ECG timing assumes 1 kHz FreeRTOS tick"
#endif

namespace {
std::atomic<bool> s_leadsOff{true};
std::atomic<uint32_t> s_battMv{0};

void ecgTask(void*) {
  pinMode(PIN_ECG_LO_P, INPUT);
  pinMode(PIN_ECG_LO_N, INPUT);

  const TickType_t period = pdMS_TO_TICKS(1000 / ECG_FS_HZ);
  TickType_t last = xTaskGetTickCount();
  uint16_t loCnt = 0, okCnt = 0;
  bool off = true;
#if BATT_ENABLED
  uint32_t n = 0;
#endif

  for (;;) {
    vTaskDelayUntil(&last, period);

    // leads-off с антидребезгом
    const bool loNow = digitalRead(PIN_ECG_LO_P) == HIGH || digitalRead(PIN_ECG_LO_N) == HIGH;
    if (loNow) {
      okCnt = 0;
      if (loCnt < 0xFFFF) loCnt++;
      if (loCnt >= ECG_LO_ON_SAMPLES) off = true;
    } else {
      loCnt = 0;
      if (okCnt < 0xFFFF) okCnt++;
      if (okCnt >= ECG_LO_OFF_SAMPLES) off = false;
    }
    s_leadsOff.store(off, std::memory_order_relaxed);

    EcgRing::push(static_cast<uint16_t>(analogRead(PIN_ECG_OUT)));

#if BATT_ENABLED
    if (++n % ECG_FS_HZ == 0) {  // раз в секунду
      const uint32_t mv = analogReadMilliVolts(PIN_BATT_ADC);
      s_battMv.store(static_cast<uint32_t>(mv * BATT_DIVIDER), std::memory_order_relaxed);
    }
#endif
  }
}
}  // namespace

namespace Ecg {

void start() {
#if !ECG_ENABLED
  LOGI("ECG: disabled (ECG_ENABLED=0)");
  return;
#endif
  xTaskCreatePinnedToCore(ecgTask, "ecg", 3072, nullptr, 6, nullptr, 1);
  LOGI("ECG: started, %d Hz", ECG_FS_HZ);
}

bool leadsOff() { return s_leadsOff.load(std::memory_order_relaxed); }

bool battValid() { return BATT_ENABLED && s_battMv.load(std::memory_order_relaxed) > 0; }

float battVolts() { return s_battMv.load(std::memory_order_relaxed) / 1000.0f; }

}  // namespace Ecg
