#pragma once
#include <Arduino.h>
#include <Wire.h>

// ============================================================
//  MAX30102: собственный драйвер (с проверкой записи регистров)
//  + обработка PPG: пульс, SpO2 (оценка), HRV (RMSSD), perfusion index.
//  Режим: Red+IR, 400 sps, усреднение 4 → 100 сэмплов/с.
// ============================================================

class Max30102 {
public:
  bool begin(TwoWire& wire, uint8_t addr, uint8_t ledCurrent);
  // Читает до maxSamples сэмплов из FIFO. Возвращает количество, -1 при ошибке шины.
  int readFifo(uint32_t* red, uint32_t* ir, int maxSamples);
  bool readReg(uint8_t reg, uint8_t& v) { return read(reg, &v, 1); }

private:
  bool write(uint8_t reg, uint8_t val);
  bool read(uint8_t reg, uint8_t* buf, size_t n);
  bool writeVerify(uint8_t reg, uint8_t val);
  TwoWire* w_ = nullptr;
  uint8_t addr_ = 0x57;
};

struct PpgResult {
  bool fingerOn = false, hrValid = false, spo2Valid = false, hrvValid = false;
  float hr = 0, spo2 = 0, rmssd = 0, perfusion = 0;
  uint8_t quality = 0;
};

class PpgProcessor {
public:
  static constexpr float FS = 100.0f;

  void reset();
  void process(uint32_t red, uint32_t ir, bool motion);  // один сэмпл 100 Гц
  PpgResult result() const;
  float displaySample() const { return finger_ ? lp_ : 0.0f; }
  // отладка
  float dbgIrDc() const { return irDc_; }
  float dbgAcAmp() const { return env_; }
  uint16_t dbgBeats() const { return beats_; }
  uint8_t dbgIbiN() const { return ibiN_; }

private:
  void resetSignal();
  void candidate(uint32_t peakIdx, float prominence);
  void onBeat(float ibiMs);
  float rmssd() const;
  static float median(const float* v, uint8_t n);

  static constexpr int MA = 5, IBI_N = 5, RR_N = 32;
  static constexpr uint32_t SETTLE_SAMPLES = 150;  // 1.5 с на установление DC после касания
  static constexpr uint32_t REFRACT_SAMPLES = 30;  // 300 мс → максимум 200 bpm
  static constexpr uint32_t BEAT_TIMEOUT = 300;    // 3 с без ударов → пульс невалиден
  static constexpr uint32_t RECOVER_SAMPLES = 150; // 1.5 с без ударов → снижаем опорную амплитуду
  static constexpr uint32_t FINGER_OFF_HOLD = 200; // 2 с без контакта подряд → палец действительно убран
  static constexpr uint32_t MOTION_HOLD = 100;     // 1 с после движения не верим

  uint32_t n_ = 0;
  bool finger_ = false;
  uint32_t fingerSince_ = 0, motionUntil_ = 0, offCount_ = 0;
  float irDc_ = 0, redDc_ = 0;
  float maIr_[MA] = {}, maRed_[MA] = {};
  float maSumIr_ = 0, maSumRed_ = 0;
  uint8_t maIdx_ = 0;
  float lp_ = 0, lpPrev_ = 0, lpRed_ = 0;
  float rmsIr2_ = 0, rmsRed2_ = 0, env_ = 0;
  bool haveBeat_ = false;
  uint32_t lastBeat_ = 0;
  float lastProm_ = 0;                     // выраженность прошлого удара
  float promRef_ = 0;                      // адаптивная опорная выраженность
  bool rising_ = false;                    // состояние детектора с гистерезисом
  float runMax_ = 0, runMin_ = 0, trough_ = 0;
  uint32_t runMaxIdx_ = 0;
  float dPrev_ = 0, dPrev2_ = 0;           // производная lp для опорной точки
  float maxSlope_ = 0, maxSlopePos_ = 0;   // максимум крутизны фронта с прошлого удара
  float lastFid_ = 0;                      // опорная точка прошлого удара, в сэмплах
  float ibi_[IBI_N] = {};
  uint8_t ibiN_ = 0, ibiIdx_ = 0, outliers_ = 0;
  float rr_[RR_N] = {};
  uint8_t rrN_ = 0, rrIdx_ = 0;
  float hr_ = 0, spo2_ = 0;
  bool spo2Init_ = false;
  uint16_t beats_ = 0;
};
