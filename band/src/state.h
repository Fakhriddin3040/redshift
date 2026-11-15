#pragma once
#include <Arduino.h>
#include "config.h"

// ============================================================
//  Общее состояние между задачами.
//  Писатель Vitals/Alerts — только задача sensors, NetStatus — только net.
//  Читатели получают копию (снапшот) под критической секцией.
// ============================================================

enum class Level : uint8_t { Ok = 0, Warn = 1, Crit = 2 };
enum class Metric : uint8_t { HR = 0, SpO2, SkinT, CO2, Pressure, Count };
constexpr int METRIC_COUNT = static_cast<int>(Metric::Count);
inline int mi(Metric m) { return static_cast<int>(m); }

struct Vitals {
  // MAX30102
  bool ppgOk = false, fingerOn = false;
  bool hrValid = false;   float hr = 0;          // bpm
  bool spo2Valid = false; float spo2 = 0;        // %, оценка без калибровки
  bool hrvValid = false;  float rmssd = 0;       // мс
  float perfusion = 0;                           // %
  uint8_t ppgQuality = 0;                        // 0..100
  // MAX30205
  bool skinOk = false, skinValid = false, skinOnBody = false, skinWarming = true;
  float skinT = 0, skinPred = 0;                 // °C
  // SCD41
  bool scdOk = false, co2Valid = false;
  uint16_t co2 = 0; float airT = 0, rh = 0;
  // BMP390
  bool bmpOk = false, presValid = false, presBaseValid = false, presRateValid = false;
  float pressure = 0, presBase = 0, presRate = 0, bmpT = 0;  // гПа, гПа, гПа/мин, °C
  // BMI270
  bool imuOk = false, imuValid = false, moving = false;
  float ax = 0, ay = 0, az = 0;                  // g
  float gx = 0, gy = 0, gz = 0;                  // °/с
  float motion = 0;
  bool actValid = false; uint16_t actMg = 0;   // среднее | |a| - 1g | за секунду, milli-g
  // AD8232
  bool ecgLeadsOff = true;
  // Питание
  bool battValid = false; float battV = 0; uint8_t battPct = 0;
  // true, когда каждый подключённый датчик выдал первое значение (или вышел таймаут прогрева)
  bool ready = false;
  // Диагностика
  uint32_t i2cErrors = 0, i2cRecoveries = 0, freeHeap = 0;
};

struct AlertState {
  Level level[METRIC_COUNT] = {};
  Level overall = Level::Ok;
  Metric focus = Metric::HR;
};

enum class NetState : uint8_t { Offline, WifiOnly, Online };

struct NetStatus {
  NetState state = NetState::Offline;
  uint16_t queued = 0;
  uint32_t sent = 0, dropped = 0;
  bool timeSynced = false;
  int8_t rssi = 0;
};

namespace State {
void setVitals(const Vitals& v);
Vitals getVitals();
void setAlerts(const AlertState& a);
AlertState getAlerts();
void setNet(const NetStatus& n);
NetStatus getNet();
}  // namespace State

// Кольцевые буферы: один писатель, много читателей. Индексы монотонные (не по модулю).
// Читатель обязан держать (head - idx) < размера буфера.
namespace EcgRing {
void push(uint16_t v);
uint32_t head();
uint16_t at(uint32_t idx);
}  // namespace EcgRing

namespace PpgRing {
void push(float v);
uint32_t head();
float at(uint32_t idx);
}  // namespace PpgRing
