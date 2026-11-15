#pragma once
#include "state.h"

// ============================================================
//  Оценка состояния: метрика → Ok / Warn / Crit с гистерезисом.
//  Невалидная метрика (нет данных, прогрев) тревогу не поднимает.
// ============================================================

class AlertEngine {
public:
  AlertState update(const Vitals& v, uint32_t nowMs);

private:
  struct Track {
    Level level = Level::Ok;
    Level pending = Level::Ok;
    uint32_t since = 0;
  };
  static Level step(Track& t, bool valid, Level raw, uint32_t now);
  Track t_[METRIC_COUNT];
};

const char* levelName(Level l);
const char* metricName(Metric m);
