#include "ppg.h"
#include "config.h"

// ---------------- регистры MAX30102 ----------------
namespace {
constexpr uint8_t REG_INT_EN1   = 0x02;
constexpr uint8_t REG_INT_EN2   = 0x03;
constexpr uint8_t REG_FIFO_WR   = 0x04;
constexpr uint8_t REG_FIFO_OVF  = 0x05;
constexpr uint8_t REG_FIFO_RD   = 0x06;
constexpr uint8_t REG_FIFO_DATA = 0x07;
constexpr uint8_t REG_FIFO_CFG  = 0x08;
constexpr uint8_t REG_MODE      = 0x09;
constexpr uint8_t REG_SPO2_CFG  = 0x0A;
constexpr uint8_t REG_LED1_PA   = 0x0C;  // Red
constexpr uint8_t REG_LED2_PA   = 0x0D;  // IR
constexpr uint8_t REG_PART_ID   = 0xFF;

constexpr uint8_t PART_ID       = 0x15;
constexpr uint8_t MODE_RESET    = 0x40;
constexpr uint8_t MODE_SPO2     = 0x03;  // Red + IR
constexpr uint8_t FIFO_CFG_VAL  = 0x50;  // SMP_AVE=4, rollover on, A_FULL=0
constexpr uint8_t SPO2_CFG_VAL  = 0x2F;  // ADC 4096 нА, 400 sps, 411 мкс / 18 бит
constexpr int     FIFO_DEPTH    = 32;
constexpr int     BYTES_PER_SMP = 6;
constexpr int     CHUNK_SMP     = 16;    // 96 байт за транзакцию < буфера Wire (128)
}  // namespace

bool Max30102::write(uint8_t reg, uint8_t val) {
  w_->beginTransmission(addr_);
  w_->write(reg);
  w_->write(val);
  return w_->endTransmission() == 0;
}

bool Max30102::read(uint8_t reg, uint8_t* buf, size_t n) {
  w_->beginTransmission(addr_);
  w_->write(reg);
  if (w_->endTransmission(false) != 0) return false;
  const size_t got = w_->requestFrom(static_cast<uint8_t>(addr_), static_cast<uint8_t>(n));
  if (got != n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = static_cast<uint8_t>(w_->read());
  return true;
}

bool Max30102::writeVerify(uint8_t reg, uint8_t val) {
  for (int attempt = 0; attempt < 3; attempt++) {
    uint8_t rb = 0;
    if (write(reg, val) && read(reg, &rb, 1) && rb == val) return true;
    delay(5);
  }
  return false;
}

bool Max30102::begin(TwoWire& wire, uint8_t addr, uint8_t ledCurrent) {
  w_ = &wire;
  addr_ = addr;

  uint8_t id = 0;
  if (!read(REG_PART_ID, &id, 1) || id != PART_ID) return false;

  if (!write(REG_MODE, MODE_RESET)) return false;
  for (int i = 0; i < 20; i++) {
    delay(5);
    uint8_t m = 0;
    if (read(REG_MODE, &m, 1) && !(m & MODE_RESET)) break;
  }

  bool ok = true;
  ok = ok && writeVerify(REG_INT_EN1, 0x00);
  ok = ok && writeVerify(REG_INT_EN2, 0x00);
  ok = ok && writeVerify(REG_FIFO_CFG, FIFO_CFG_VAL);
  ok = ok && writeVerify(REG_SPO2_CFG, SPO2_CFG_VAL);
  ok = ok && writeVerify(REG_LED1_PA, ledCurrent);
  ok = ok && writeVerify(REG_LED2_PA, ledCurrent);
  ok = ok && write(REG_FIFO_WR, 0) && write(REG_FIFO_OVF, 0) && write(REG_FIFO_RD, 0);
  ok = ok && writeVerify(REG_MODE, MODE_SPO2);
  return ok;
}

int Max30102::readFifo(uint32_t* red, uint32_t* ir, int maxSamples) {
  uint8_t p[3];  // WR_PTR, OVF_COUNTER, RD_PTR (автоинкремент адреса)
  if (!read(REG_FIFO_WR, p, 3)) return -1;

  int n = (p[0] - p[2]) & (FIFO_DEPTH - 1);
  if (n == 0 && p[1] != 0) n = FIFO_DEPTH;  // переполнение: FIFO полный
  if (n > maxSamples) n = maxSamples;

  int got = 0;
  uint8_t buf[CHUNK_SMP * BYTES_PER_SMP];
  while (got < n) {
    const int chunk = (n - got) < CHUNK_SMP ? (n - got) : CHUNK_SMP;
    if (!read(REG_FIFO_DATA, buf, static_cast<size_t>(chunk * BYTES_PER_SMP))) return got > 0 ? got : -1;
    for (int i = 0; i < chunk; i++) {
      const uint8_t* s = buf + i * BYTES_PER_SMP;
      red[got + i] = ((uint32_t(s[0]) << 16) | (uint32_t(s[1]) << 8) | s[2]) & 0x3FFFF;
      ir[got + i]  = ((uint32_t(s[3]) << 16) | (uint32_t(s[4]) << 8) | s[5]) & 0x3FFFF;
    }
    got += chunk;
  }
  return got;
}

// ================= PpgProcessor =================

void PpgProcessor::reset() { *this = PpgProcessor(); }

void PpgProcessor::resetSignal() {
  const uint32_t n = n_;
  *this = PpgProcessor();
  n_ = n;
}

float PpgProcessor::median(const float* v, uint8_t n) {
  float t[IBI_N];
  for (uint8_t i = 0; i < n; i++) t[i] = v[i];
  for (uint8_t i = 1; i < n; i++) {  // insertion sort, n <= 5
    const float x = t[i];
    int j = i - 1;
    while (j >= 0 && t[j] > x) { t[j + 1] = t[j]; j--; }
    t[j + 1] = x;
  }
  return (n & 1) ? t[n / 2] : 0.5f * (t[n / 2 - 1] + t[n / 2]);
}

void PpgProcessor::process(uint32_t red, uint32_t ir, bool motion) {
  n_++;

  // Детект пальца с гистерезисом
  const float th = static_cast<float>(PPG_FINGER_DC_MIN);
  const bool fingerNow = finger_ ? (ir > th * 0.8f) : (ir > th);
  // Короткая потеря контакта (палец сдвинулся) — не сброс: пережидаем до FINGER_OFF_HOLD,
  // сэмплы без пальца в фильтры не пускаем, посчитанные значения сохраняем.
  if (finger_ && !fingerNow) {
    if (++offCount_ < FINGER_OFF_HOLD) return;
  } else {
    offCount_ = 0;
  }
  if (fingerNow != finger_) {
    resetSignal();
    finger_ = fingerNow;
    fingerSince_ = n_;
    irDc_ = static_cast<float>(ir);
    redDc_ = static_cast<float>(red);
  }
  if (!finger_) return;

  // DC: ФНЧ ~0.5 Гц; AC инвертируем — пик = систола
  constexpr float aDc = 0.03f;
  irDc_  += aDc * (static_cast<float>(ir)  - irDc_);
  redDc_ += aDc * (static_cast<float>(red) - redDc_);
  const float acIr  = -(static_cast<float>(ir)  - irDc_);
  const float acRed = -(static_cast<float>(red) - redDc_);

  // Скользящее среднее на 5 сэмплов — убираем ВЧ-шум
  maSumIr_  += acIr  - maIr_[maIdx_];  maIr_[maIdx_]  = acIr;
  maSumRed_ += acRed - maRed_[maIdx_]; maRed_[maIdx_] = acRed;
  maIdx_ = (maIdx_ + 1) % MA;
  lpPrev_  = lp_;
  lp_      = maSumIr_ / MA;
  lpRed_   = maSumRed_ / MA;

  // Опорная точка удара — максимум крутизны фронта (вершина плоская и «плавает» в шуме),
  // с параболической интерполяцией между сэмплами. Ищется от последнего минимума.
  const float d = lp_ - lpPrev_;
  if (dPrev_ > dPrev2_ && dPrev_ >= d && dPrev_ > maxSlope_) {
    const float den = dPrev2_ - 2.0f * dPrev_ + d;
    float off = den != 0.0f ? 0.5f * (dPrev2_ - d) / den : 0.0f;
    if (off > 0.5f) off = 0.5f;
    if (off < -0.5f) off = -0.5f;
    maxSlope_ = dPrev_;
    maxSlopePos_ = static_cast<float>(n_ - 1) + off;
  }
  dPrev2_ = dPrev_;
  dPrev_ = d;

  // Огибающая — стартовая оценка амплитуды, пока нет принятых ударов
  const float mag = fabsf(lp_);
  env_ *= 0.995f;
  if (mag > env_) env_ = mag;

  if (motion) motionUntil_ = n_ + MOTION_HOLD;
  if (n_ - fingerSince_ < SETTLE_SAMPLES) {
    rising_ = false;
    runMin_ = lp_;
    maxSlope_ = 0.0f;
    return;
  }

  // RMS AC для SpO2 / perfusion (окно ~2 с)
  rmsIr2_  += 0.005f * (lp_ * lp_ - rmsIr2_);
  rmsRed2_ += 0.005f * (lpRed_ * lpRed_ - rmsRed2_);

  // Детектор пиков с гистерезисом: пик подтверждается, когда сигнал упал на h ниже максимума;
  // минимум — когда поднялся на h выше. Шум меньше h и медленный дрейф состояние не переключают.
  // Ударов нет дольше 1.5 с — опорная амплитуда завышена (всплеск от сдвига пальца).
  // Плавно опускаем её, иначе обычные удары не пересекут гистерезис и детектор залипнет.
  if (promRef_ > 0.0f && n_ - (haveBeat_ ? lastBeat_ : fingerSince_) > RECOVER_SAMPLES) promRef_ *= 0.99f;
  const float h = 0.25f * (promRef_ > 0.0f ? promRef_ : env_);
  if (h <= 0.0f) return;
  if (rising_) {
    if (lp_ > runMax_) {
      runMax_ = lp_;
      runMaxIdx_ = n_;
    }
    if (lp_ < runMax_ - h) {
      rising_ = false;
      runMin_ = lp_;
      candidate(runMaxIdx_, runMax_ - trough_);
    }
  } else {
    if (lp_ < runMin_) {
      runMin_ = lp_;
      maxSlope_ = 0.0f;  // фронт ищем от самого нижнего минимума
    }
    if (lp_ > runMin_ + h) {
      rising_ = true;
      trough_ = runMin_;
      runMax_ = lp_;
      runMaxIdx_ = n_;
    }
  }
}

void PpgProcessor::candidate(uint32_t peak, float prom) {
  // Выраженность пика относительно предыдущего минимума, порог адаптивный
  if (promRef_ <= 0.0f) promRef_ = prom;
  if (prom < 0.5f * promRef_) {
    promRef_ *= 0.95f;  // амплитуда реально упала (перфузия, давление датчика) — подстраиваемся
    return;
  }
  if (haveBeat_ && (peak - lastBeat_) < REFRACT_SAMPLES) return;
  // Дикротическая волна: раньше 60% медианного интервала И заметно слабее прошлого удара.
  // Ранний, но полноразмерный пик — реальное учащение ритма, пропускаем: иначе застрянем
  // на половинной частоте.
  if (haveBeat_ && ibiN_ >= 3) {
    const uint32_t early = static_cast<uint32_t>(0.6f * median(ibi_, ibiN_) * FS / 1000.0f);
    if ((peak - lastBeat_) < early && prom < 0.7f * lastProm_) return;
  }
  // Всплеск (в разы выше обычного удара) в опорную амплитуду не пускаем
  promRef_ = 0.8f * promRef_ + 0.2f * (prom > 2.0f * promRef_ ? 2.0f * promRef_ : prom);

  const bool moving = !RELAXED_VALIDITY && n_ < motionUntil_;
  const float fid = maxSlope_ > 0.0f ? maxSlopePos_ : static_cast<float>(peak);
  if (haveBeat_ && !moving) {
    const float ibiMs = (fid - lastFid_) * (1000.0f / FS);
    if (ibiMs >= 300.0f && ibiMs <= 2000.0f) onBeat(ibiMs);
  }
  lastBeat_ = peak;
  lastFid_ = fid;
  lastProm_ = prom;
  haveBeat_ = true;
}

void PpgProcessor::onBeat(float ibi) {
  // Отбраковка выбросов относительно медианы; 3 выброса подряд — ритм реально сменился
  if (ibiN_ >= 3) {
    const float med = median(ibi_, ibiN_);
    if (fabsf(ibi - med) > 0.3f * med) {
      if (++outliers_ < 3) return;
      ibiN_ = ibiIdx_ = 0;
      rrN_ = rrIdx_ = 0;
    }
  }
  outliers_ = 0;

  // Для HRV — только интервалы, согласованные с уже установившимся ритмом
  // (стартовые/пропущенные удары не должны раздувать RMSSD)
  const bool rrUsable = ibiN_ >= 3 && fabsf(ibi - median(ibi_, ibiN_)) <= 0.2f * median(ibi_, ibiN_);

  ibi_[ibiIdx_] = ibi;
  ibiIdx_ = (ibiIdx_ + 1) % IBI_N;
  if (ibiN_ < IBI_N) ibiN_++;
  hr_ = 60000.0f / median(ibi_, ibiN_);

  if (rrUsable) {
    rr_[rrIdx_] = ibi;
    rrIdx_ = (rrIdx_ + 1) % RR_N;
    if (rrN_ < RR_N) rrN_++;
  }
  if (beats_ < 0xFFFF) beats_++;

  // SpO2: ratio of ratios. Без калибровки по эталонному пульсоксиметру — только оценка.
  if (rmsIr2_ > 0 && rmsRed2_ > 0 && irDc_ > 0 && redDc_ > 0) {
    const float R = (sqrtf(rmsRed2_) / redDc_) / (sqrtf(rmsIr2_) / irDc_);
    float s = SPO2_CAL_A - SPO2_CAL_B * R;
    if (s > 100.0f) s = 100.0f;
    if (s < 70.0f) s = 70.0f;
    spo2_ = spo2Init_ ? (0.8f * spo2_ + 0.2f * s) : s;
    spo2Init_ = true;
  }
}

float PpgProcessor::rmssd() const {
  if (rrN_ < 2) return 0;
  const int start = (rrIdx_ + RR_N - rrN_) % RR_N;
  float acc = 0;
  for (int k = 1; k < rrN_; k++) {
    const float d = rr_[(start + k) % RR_N] - rr_[(start + k - 1) % RR_N];
    acc += d * d;
  }
  return sqrtf(acc / (rrN_ - 1));
}

PpgResult PpgProcessor::result() const {
  PpgResult r;
  r.fingerOn = finger_;
  if (!finger_) return r;

  const bool moving = n_ < motionUntil_;
  const bool recent = haveBeat_ && (n_ - lastBeat_) < BEAT_TIMEOUT;

#if RELAXED_VALIDITY
  r.hrValid   = hr_ > 0.0f;                 // есть хотя бы один интервал между ударами
  r.hr        = hr_;
  r.spo2Valid = spo2Init_;
  r.spo2      = spo2_;
  r.hrvValid  = rrN_ >= 2;
  r.rmssd     = r.hrvValid ? rmssd() : 0;
  r.perfusion = irDc_ > 0 ? 2.828f * sqrtf(rmsIr2_) / irDc_ * 100.0f : 0;
  r.quality   = r.hrValid ? ((moving || !recent) ? 60 : 90) : 30;
  return r;
#endif
  r.hrValid   = recent && !moving && ibiN_ >= 3;
  r.hr        = hr_;
  r.spo2Valid = r.hrValid && spo2Init_ && beats_ >= 8;
  r.spo2      = spo2_;
  r.hrvValid  = r.hrValid && rrN_ >= 20;
  r.rmssd     = r.hrvValid ? rmssd() : 0;
  r.perfusion = irDc_ > 0 ? 2.828f * sqrtf(rmsIr2_) / irDc_ * 100.0f : 0;
  r.quality   = moving ? 20 : (!recent ? 30 : (r.hrValid ? 90 : 50));
  return r;
}
