#include "sensors.h"
#include <Wire.h>
#include <Adafruit_BMP3XX.h>
#include "SparkFun_BMI270_Arduino_Library.h"
#include "alerts.h"
#include "config.h"
#include "ecg.h"
#include "log.h"
#include "ppg.h"
#include "state.h"
#include "util.h"

namespace {

// ================= helpers =================
bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

// ================= MAX30205 =================
bool readMax30205(float& t) {
  Wire.beginTransmission(ADDR_MAX30205);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(static_cast<uint8_t>(ADDR_MAX30205), static_cast<uint8_t>(2)) != 2) return false;
  const uint8_t hi = Wire.read();
  const uint8_t lo = Wire.read();
  t = static_cast<int16_t>((hi << 8) | lo) * 0.00390625f;
  return t > -20.0f && t < 60.0f;  // битый пакет даёт 0.00 / 255.99 — отсекаем
}

// ================= SCD41 =================
class Scd41 {
public:
  bool begin() {
    cmd(0x3F86);                         // stop_periodic_measurement
    delay(500);
    if (!cmdArg(0x2416, 0)) return false;  // ASC off (не персистентно — ставим при каждом старте)
    delay(1);
    return cmd(0x21B1);                  // start_periodic_measurement, 5 с
  }
  // 1 — новые данные, 0 — ещё нет, -1 — ошибка шины
  int poll(uint16_t& co2, float& t, float& rh) {
    uint16_t st = 0;
    if (!read(0xE4B8, &st, 1)) return -1;  // get_data_ready_status
    if ((st & 0x07FF) == 0) return 0;
    uint16_t w[3];
    if (!read(0xEC05, w, 3)) return -1;    // read_measurement
    co2 = w[0];
    t = -45.0f + 175.0f * w[1] / 65535.0f;
    rh = 100.0f * w[2] / 65535.0f;
    return 1;
  }
  bool setAmbientPressure(float hPa) { return cmdArg(0xE000, static_cast<uint16_t>(hPa + 0.5f)); }

private:
  static uint8_t crc8(const uint8_t* d, int n) {
    uint8_t c = 0xFF;
    for (int i = 0; i < n; i++) {
      c ^= d[i];
      for (int b = 0; b < 8; b++) c = (c & 0x80) ? static_cast<uint8_t>((c << 1) ^ 0x31) : static_cast<uint8_t>(c << 1);
    }
    return c;
  }
  bool cmd(uint16_t c) {
    Wire.beginTransmission(ADDR_SCD41);
    Wire.write(static_cast<uint8_t>(c >> 8));
    Wire.write(static_cast<uint8_t>(c & 0xFF));
    return Wire.endTransmission() == 0;
  }
  bool cmdArg(uint16_t c, uint16_t arg) {
    const uint8_t a[2] = {static_cast<uint8_t>(arg >> 8), static_cast<uint8_t>(arg & 0xFF)};
    Wire.beginTransmission(ADDR_SCD41);
    Wire.write(static_cast<uint8_t>(c >> 8));
    Wire.write(static_cast<uint8_t>(c & 0xFF));
    Wire.write(a, 2);
    Wire.write(crc8(a, 2));
    return Wire.endTransmission() == 0;
  }
  bool read(uint16_t c, uint16_t* out, int words) {
    if (!cmd(c)) return false;
    delay(1);
    const int n = words * 3;
    if (Wire.requestFrom(static_cast<uint8_t>(ADDR_SCD41), static_cast<uint8_t>(n)) != n) return false;
    for (int i = 0; i < words; i++) {
      uint8_t b[3];
      for (int j = 0; j < 3; j++) b[j] = static_cast<uint8_t>(Wire.read());
      if (crc8(b, 2) != b[2]) return false;
      out[i] = static_cast<uint16_t>((b[0] << 8) | b[1]);
    }
    return true;
  }
};

// ================= температура кожи: сглаживание + прогноз =================
class SkinTemp {
public:
  void reset() { *this = SkinTemp(); }

  void add(float t, uint32_t now) {
    buf_[idx_] = t;
    idx_ = (idx_ + 1) % N;
    if (cnt_ < N) cnt_++;
    float s = 0;
    for (int i = 0; i < cnt_; i++) s += buf_[i];
    smooth_ = s / cnt_;
    valid_ = true;

    if (cnt_ == N && (histN_ == 0 || now - lastHist_ >= HIST_MS)) {
      lastHist_ = now;
      if (histN_ < 3) {
        hist_[histN_++] = smooth_;
      } else {
        hist_[0] = hist_[1];
        hist_[1] = hist_[2];
        hist_[2] = smooth_;
      }
    }

    if (histN_ < 3) {  // ещё не знаем, устоялось ли
      warming_ = true;
      pred_ = smooth_;
      return;
    }
    const float a = hist_[0], b = hist_[1], c = hist_[2];
    const bool rising  = a < b && b < c && (c - a) > 0.05f;
    const bool falling = a > b && b > c && (a - c) > 0.05f;
    warming_ = rising || falling;
    pred_ = warming_ ? extrapolate(a, b, c, rising) : smooth_;
  }

  bool valid() const { return valid_; }
  bool warming() const { return warming_; }
  float smooth() const { return smooth_; }
  float predicted() const { return pred_; }

private:
  // Экстраполяция Эйткена: куда сойдётся экспонента по трём равноотстоящим точкам
  static float extrapolate(float a, float b, float c, bool rising) {
    const float den = a + c - 2 * b;
    if (fabsf(den) < 0.005f) return c;
    const float p = (a * c - b * b) / den;
    const float lo = rising ? c : c - 5.0f;
    const float hi = rising ? c + 5.0f : c;
    return (p < lo || p > hi) ? c : p;
  }

  static constexpr int N = 5;              // скользящее среднее, 5 с
  static constexpr uint32_t HIST_MS = 10000;
  float buf_[N] = {};
  int cnt_ = 0, idx_ = 0;
  float hist_[3] = {};
  int histN_ = 0;
  uint32_t lastHist_ = 0;
  float smooth_ = 0, pred_ = 0;
  bool valid_ = false, warming_ = true;
};

// ================= давление: база + скорость изменения =================
class PressureTrack {
public:
  void reset() { *this = PressureTrack(); }

  void add(float p, uint32_t now) {
    cur_ = p;
    valid_ = true;
    if (!baseValid_) {
      baseSum_ += p;
      if (++baseN_ >= Cfg::PRES_BASE_SAMPLES) {
        base_ = baseSum_ / baseN_;
        baseValid_ = true;
      }
    }
    if (histN_ == 0 || now - lastPush_ >= HIST_MS) {
      lastPush_ = now;
      hp_[hIdx_] = p;
      ht_[hIdx_] = now;
      hIdx_ = (hIdx_ + 1) % HN;
      if (histN_ < HN) histN_++;
    }
    if (histN_ >= 2) {
      const int newest = (hIdx_ + HN - 1) % HN;
      const int oldest = (hIdx_ + HN - histN_) % HN;
      const float dtMin = (ht_[newest] - ht_[oldest]) / 60000.0f;
      if (dtMin >= 0.8f) {
        rate_ = (hp_[newest] - hp_[oldest]) / dtMin;
        rateValid_ = true;
      }
    }
  }

  bool valid() const { return valid_; }
  float current() const { return cur_; }
  bool baseValid() const { return baseValid_; }
  float base() const { return base_; }
  bool rateValid() const { return rateValid_; }
  float rate() const { return rate_; }

private:
  static constexpr int HN = 7;             // 7 точек раз в 10 с → окно ~60 с
  static constexpr uint32_t HIST_MS = 10000;
  float cur_ = 0, base_ = 0, baseSum_ = 0, rate_ = 0;
  int baseN_ = 0;
  bool valid_ = false, baseValid_ = false, rateValid_ = false;
  float hp_[HN] = {};
  uint32_t ht_[HN] = {};
  int hIdx_ = 0, histN_ = 0;
  uint32_t lastPush_ = 0;
};

// ================= состояние задачи =================
enum Dev { D_PPG = 0, D_IMU, D_BMP, D_SKIN, D_SCD, D_COUNT };
const char* const kDevName[D_COUNT] = {"MAX30102", "BMI270", "BMP390", "MAX30205", "SCD41"};

Vitals V;  // рабочая копия, принадлежит только этой задаче
Max30102 s_ppgDev;
PpgProcessor s_ppg;
BMI270 s_imu;
Adafruit_BMP3XX s_bmp;
Scd41 s_scd;
SkinTemp s_skin;
PressureTrack s_pres;
AlertEngine s_alerts;
uint8_t s_fail[D_COUNT] = {};
uint32_t s_dbgIr = 0, s_dbgRed = 0;   // последний сырой сэмпл PPG
uint16_t s_dbgPpgN = 0, s_dbgPpgErr = 0;  // сэмплов и ошибок чтения FIFO за секунду
float s_dbgSkinRaw = NAN;
float s_actSum = 0;   // накопитель act_mg за текущую секунду
uint16_t s_actN = 0;
bool s_retryNow = false;

bool* okFlag(Dev d) {
  switch (d) {
    case D_PPG: return &V.ppgOk;
    case D_IMU: return &V.imuOk;
    case D_BMP: return &V.bmpOk;
    case D_SKIN: return &V.skinOk;
    default: return &V.scdOk;
  }
}

void invalidate(Dev d) {
  switch (d) {
    case D_PPG:
      s_ppg.reset();
      V.fingerOn = V.hrValid = V.spo2Valid = V.hrvValid = false;
      V.ppgQuality = 0;
      break;
    case D_IMU:
      V.imuValid = V.moving = V.actValid = false;
      V.motion = 0;
      break;
    case D_BMP:
      V.presValid = V.presRateValid = false;  // базу давления сохраняем
      break;
    case D_SKIN:
      s_skin.reset();
      V.skinValid = V.skinOnBody = false;
      V.skinWarming = true;
      break;
    case D_SCD:
      V.co2Valid = false;
      break;
    default:
      break;
  }
}

void busRecover() {
  LOGW("I2C: bus recovery");
  V.i2cRecoveries++;
  Wire.end();
  pinMode(PIN_I2C_SDA, INPUT_PULLUP);
  pinMode(PIN_I2C_SCL, OUTPUT_OPEN_DRAIN);
  digitalWrite(PIN_I2C_SCL, HIGH);
  delayMicroseconds(10);
  // До 9 тактов SCL, пока slave не отпустит SDA
  for (int i = 0; i < 9 && digitalRead(PIN_I2C_SDA) == LOW; i++) {
    digitalWrite(PIN_I2C_SCL, LOW);
    delayMicroseconds(10);
    digitalWrite(PIN_I2C_SCL, HIGH);
    delayMicroseconds(10);
  }
  // STOP: SDA low → high при SCL high
  pinMode(PIN_I2C_SDA, OUTPUT_OPEN_DRAIN);
  digitalWrite(PIN_I2C_SDA, LOW);
  delayMicroseconds(10);
  digitalWrite(PIN_I2C_SDA, HIGH);
  delayMicroseconds(10);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, I2C_FREQ_HZ);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
}

void devOk(Dev d) { s_fail[d] = 0; }

void devFail(Dev d) {
  V.i2cErrors++;
  if (++s_fail[d] < I2C_DEV_MAX_FAILS) return;
  s_fail[d] = 0;
  *okFlag(d) = false;
  invalidate(d);
  LOGW("%s: lost after %d errors", kDevName[d], I2C_DEV_MAX_FAILS);
  busRecover();
  s_retryNow = true;
}

void initMissing() {
  if (!V.ppgOk && i2cPresent(ADDR_MAX30102)) {
    V.ppgOk = s_ppgDev.begin(Wire, ADDR_MAX30102, PPG_LED_CURRENT);
    s_ppg.reset();
    LOGI("MAX30102: %s", V.ppgOk ? "OK" : "config FAILED");
  }
  if (!V.imuOk && i2cPresent(ADDR_BMI270)) {
    V.imuOk = s_imu.beginI2C(ADDR_BMI270, Wire) == BMI2_OK;  // грузит 8 КБ конфига, ~1 с
    LOGI("BMI270: %s", V.imuOk ? "OK" : "FAILED");
  }
  if (!V.bmpOk && i2cPresent(ADDR_BMP390)) {
    V.bmpOk = s_bmp.begin_I2C(ADDR_BMP390, &Wire);
    if (V.bmpOk) {
      s_bmp.setTemperatureOversampling(BMP3_OVERSAMPLING_2X);
      s_bmp.setPressureOversampling(BMP3_OVERSAMPLING_8X);
      s_bmp.setIIRFilterCoeff(BMP3_IIR_FILTER_COEFF_3);
      s_bmp.setOutputDataRate(BMP3_ODR_50_HZ);
    }
    LOGI("BMP390: %s", V.bmpOk ? "OK" : "FAILED");
  }
  if (!V.skinOk) {
    V.skinOk = i2cPresent(ADDR_MAX30205);
    if (V.skinOk) LOGI("MAX30205: OK");
  }
  if (!V.scdOk && i2cPresent(ADDR_SCD41)) {
    V.scdOk = s_scd.begin();
    LOGI("SCD41: %s", V.scdOk ? "OK" : "FAILED");
  }
}

void applyPpg(const PpgResult& r) {
  V.fingerOn = r.fingerOn;
  V.hrValid = r.hrValid;     V.hr = r.hr;
  V.spo2Valid = r.spo2Valid; V.spo2 = r.spo2;
  V.hrvValid = r.hrvValid;   V.rmssd = r.rmssd;
  V.perfusion = r.perfusion;
  V.ppgQuality = r.quality;
}

void pollPpg() {
  static uint32_t red[32], ir[32];
  const int n = s_ppgDev.readFifo(red, ir, 32);
  if (n < 0) {
    s_dbgPpgErr++;
    devFail(D_PPG);
    return;
  }
  devOk(D_PPG);
  s_dbgPpgN += n;
  if (n > 0) {
    s_dbgIr = ir[n - 1];
    s_dbgRed = red[n - 1];
  }
  for (int i = 0; i < n; i++) {
    s_ppg.process(red[i], ir[i], V.moving);
    PpgRing::push(s_ppg.displaySample());
  }
  applyPpg(s_ppg.result());
}

void readImu() {
  if (s_imu.getSensorData() != BMI2_OK) {
    devFail(D_IMU);
    return;
  }
  devOk(D_IMU);
  V.ax = s_imu.data.accelX; V.ay = s_imu.data.accelY; V.az = s_imu.data.accelZ;
  V.gx = s_imu.data.gyroX;  V.gy = s_imu.data.gyroY;  V.gz = s_imu.data.gyroZ;
  const float a = sqrtf(V.ax * V.ax + V.ay * V.ay + V.az * V.az);
  const float g = sqrtf(V.gx * V.gx + V.gy * V.gy + V.gz * V.gz);
  s_actSum += fabsf(a - 1.0f) * 1000.0f;  // milli-g
  s_actN++;
  const float inst = fabsf(a - 1.0f) + g / 500.0f;
  V.motion += 0.2f * (inst - V.motion);
  V.moving = V.motion > IMU_MOTION_THRESH_G;
  V.imuValid = true;
}

void readSlow(uint32_t now) {
  static uint32_t tScdComp = 0;

  // --- act_mg: среднее за прошедшую секунду ---
  if (V.imuOk && s_actN > 0) {
    const float m = s_actSum / s_actN;
    V.actMg = static_cast<uint16_t>(m > 65534.0f ? 65534.0f : m + 0.5f);
    V.actValid = true;
  } else {
    V.actValid = false;
  }
  s_actSum = 0;
  s_actN = 0;

  // --- MAX30205 ---
  if (V.skinOk) {
    float t;
    if (readMax30205(t)) {
      devOk(D_SKIN);
      s_dbgSkinRaw = t;
      s_skin.add(t, now);
    } else {
      devFail(D_SKIN);
    }
  }
  V.skinValid   = V.skinOk && s_skin.valid();
  V.skinT       = s_skin.smooth();
  V.skinPred    = s_skin.predicted();
  V.skinWarming = s_skin.warming();
  V.skinOnBody  = V.skinValid && V.skinT >= Cfg::SKIN_ONBODY_MIN;

  // --- BMP390 ---
  if (V.bmpOk) {
    if (s_bmp.performReading()) {
      devOk(D_BMP);
      s_pres.add(static_cast<float>(s_bmp.pressure) / 100.0f, now);
      V.bmpT = static_cast<float>(s_bmp.temperature);
    } else {
      devFail(D_BMP);
    }
  }
  V.presValid     = V.bmpOk && s_pres.valid();
  V.pressure      = s_pres.current();
  V.presBaseValid = s_pres.baseValid();
  V.presBase      = s_pres.base();
  V.presRateValid = V.presValid && s_pres.rateValid();
  V.presRate      = s_pres.rate();

  // --- SCD41 ---
  if (V.scdOk) {
    uint16_t co2;
    float t, rh;
    const int r = s_scd.poll(co2, t, rh);
    if (r < 0) {
      devFail(D_SCD);
    } else {
      devOk(D_SCD);
      if (r > 0) {
        V.co2 = co2;
        V.airT = t;
        V.rh = rh;
        V.co2Valid = true;
      }
      // Компенсация SCD41 по давлению с BMP390 раз в минуту
      if (V.presValid && (tScdComp == 0 || now - tScdComp >= 60000)) {
        if (s_scd.setAmbientPressure(V.pressure)) tScdComp = now;
      }
    }
  }

  // --- Батарея (меряет задача ECG — она владелец АЦП) ---
  V.battValid = Ecg::battValid();
  if (V.battValid) {
    V.battV = Ecg::battVolts();
    float pct = (V.battV - BATT_V_EMPTY) / (BATT_V_FULL - BATT_V_EMPTY) * 100.0f;
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;
    V.battPct = static_cast<uint8_t>(pct);
  }
}

// Раз в секунду: что реально видит каждый датчик и почему значение валидно/невалидно
void debugDump() {
#if DEBUG_VITALS
  if (V.ppgOk) {
    uint8_t mode = 0xEE, pa1 = 0xEE, pa2 = 0xEE;
    s_ppgDev.readReg(0x09, mode);
    s_ppgDev.readReg(0x0C, pa1);
    s_ppgDev.readReg(0x0D, pa2);
    LOGD("PPG raw: IR=%lu RED=%lu (порог пальца %d) | %u сэмпл/с (ждём ~100), ошибок FIFO %u | MODE=0x%02X (ждём 0x03) LED=0x%02X/0x%02X",
         static_cast<unsigned long>(s_dbgIr), static_cast<unsigned long>(s_dbgRed), PPG_FINGER_DC_MIN,
         s_dbgPpgN, s_dbgPpgErr, mode, pa1, pa2);
    LOGD("PPG alg: finger=%d moving=%d dc=%.0f ac=%.0f beats=%u ibi=%u/3 | hr=%.1f(%s) spo2=%.1f(%s) rmssd=%.0f(%s) sqi=%u",
         V.fingerOn, V.moving, s_ppg.dbgIrDc(), s_ppg.dbgAcAmp(), s_ppg.dbgBeats(), s_ppg.dbgIbiN(),
         V.hr, V.hrValid ? "ok" : "--", V.spo2, V.spo2Valid ? "ok" : "--", V.rmssd, V.hrvValid ? "ok" : "--",
         V.ppgQuality);
  } else {
    LOGD("PPG: MAX30102 НЕ инициализирован (на шине %s)", i2cPresent(ADDR_MAX30102) ? "отвечает, но конфиг не записался" : "не отвечает");
  }
  LOGD("SKIN: ok=%d raw=%.2f smooth=%.2f onBody=%d (порог %.0f C) settling=%d | SCD: ok=%d co2=%u valid=%d T=%.1f RH=%.0f",
       V.skinOk, s_dbgSkinRaw, V.skinT, V.skinOnBody, Cfg::SKIN_ONBODY_MIN, V.skinWarming, V.scdOk, V.co2,
       V.co2Valid, V.airT, V.rh);
  LOGD("IMU: ok=%d a=[%+.2f %+.2f %+.2f]g motion=%.3f (порог %.2f) act=%u mg | BMP ok=%d | I2C err=%lu rec=%lu | WORN=%d",
       V.imuOk, V.ax, V.ay, V.az, V.motion, IMU_MOTION_THRESH_G, V.actMg, V.bmpOk,
       static_cast<unsigned long>(V.i2cErrors), static_cast<unsigned long>(V.i2cRecoveries),
       (RELAXED_VALIDITY ? (V.fingerOn || V.skinValid) : (V.fingerOn || V.skinOnBody)));

  // Красным — что сейчас мешает данным, зелёным — что в порядке
  if (!V.ppgOk) LOGRED("MAX30102 НЕ ПОДКЛЮЧЁН — пульса, SpO2 и HRV не будет");
  else if (!V.fingerOn) LOGRED("ПАЛЕЦ НЕ ЛЕЖИТ на MAX30102 (IR=%lu, нужно > %d) — пульс, SpO2, HRV не считаются",
                               static_cast<unsigned long>(s_dbgIr), PPG_FINGER_DC_MIN);
  else if (!V.hrValid) LOGRED("Палец есть, пульс ещё не пойман (ударов: %u) — держи неподвижно", s_ppg.dbgBeats());
  else LOGGRN("Пульс %.0f, SpO2 %.0f, sqi %u", V.hr, V.spo2, V.ppgQuality);

  if (!V.skinOk) LOGRED("MAX30205 НЕ ПОДКЛЮЧЁН — температуры кожи не будет");
  else if (!V.skinOnBody) LOGRED("MAX30205 НЕ НА КОЖЕ (%.1f C, на теле > %.0f C) — меряет воздух", V.skinT, Cfg::SKIN_ONBODY_MIN);
  else LOGGRN("Кожа %.1f C", V.skinT);

  if (!V.scdOk) LOGRED("SCD41 НЕ ПОДКЛЮЧЁН — CO2 не будет");
  if (!V.imuOk) LOGRED("BMI270 НЕ ПОДКЛЮЧЁН — активности не будет");
  if (V.moving) LOGRED("ДВИЖЕНИЕ (motion %.3f > %.2f) — сигнал пульса может быть грязным", V.motion, IMU_MOTION_THRESH_G);
  s_dbgPpgN = 0;
  s_dbgPpgErr = 0;
#endif
}

void publish(uint32_t now) {
  // Готовность к отправке: у всех найденных датчиков есть первое значение.
  // Пульс не ждём — он зависит от пальца. SCD41 даёт первый замер через ~5 с.
  static uint32_t tStart = 0;
  if (tStart == 0) tStart = now ? now : 1;
  if (!V.ready) {
    const bool all = (!V.skinOk || V.skinValid) && (!V.scdOk || V.co2Valid) && (!V.imuOk || V.actValid) &&
                     (!V.bmpOk || V.presValid);
    if (all || now - tStart >= NET_WARMUP_TIMEOUT_MS) {
      V.ready = true;
      LOGI("Sensors: first values ready after %lu ms%s", static_cast<unsigned long>(now - tStart),
           all ? "" : " (timeout, some still empty)");
    }
  }
  V.ecgLeadsOff = Ecg::leadsOff();
  V.freeHeap = ESP.getFreeHeap();
  State::setVitals(V);
  State::setAlerts(s_alerts.update(V, now));
}

// Диагностика при старте: уровни линий до инициализации и скан адресов.
// SDA/SCL = 0 в простое → нет подтяжек (модули без питания/не подключены) или КЗ на землю.
void bootDiag() {
  pinMode(PIN_I2C_SDA, INPUT);
  pinMode(PIN_I2C_SCL, INPUT);
  delay(2);
  LOGI("I2C idle: SDA(G%d)=%d SCL(G%d)=%d (ждём 1/1)", PIN_I2C_SDA, digitalRead(PIN_I2C_SDA), PIN_I2C_SCL,
       digitalRead(PIN_I2C_SCL));
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, I2C_FREQ_HZ);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  char found[96];
  int len = 0, cnt = 0;
  found[0] = 0;
  for (uint8_t a = 0x08; a < 0x78; a++) {
    if (i2cPresent(a) && len < static_cast<int>(sizeof found) - 6) {
      len += snprintf(found + len, sizeof found - len, " 0x%02X", a);
      cnt++;
    }
  }
  LOGI("I2C scan: %d device(s):%s", cnt, cnt ? found : " none");
}

void sensorTask(void*) {
  bootDiag();
  initMissing();
  LOGI("Sensors: PPG=%d IMU=%d BMP=%d SKIN=%d SCD=%d", V.ppgOk, V.imuOk, V.bmpOk, V.skinOk, V.scdOk);

  wdtAddThisTask();
  uint32_t tImu = 0, tSlow = 0, tRetry = millis(), tPub = 0;
  TickType_t last = xTaskGetTickCount();

  for (;;) {
    vTaskDelayUntil(&last, pdMS_TO_TICKS(20));
    const uint32_t now = millis();

    if (V.ppgOk) pollPpg();
    if (V.imuOk && now - tImu >= IMU_PERIOD_MS) {
      tImu = now;
      readImu();
    }
    if (now - tSlow >= 1000) {
      tSlow = now;
      readSlow(now);
      debugDump();
    }
    if (s_retryNow || now - tRetry >= SENSOR_RETRY_MS) {
      s_retryNow = false;
      tRetry = now;
      initMissing();
    }
    if (now - tPub >= 100) {
      tPub = now;
      publish(now);
    }
    wdtFeed();
  }
}

}  // namespace

namespace Sensors {
void start() { xTaskCreatePinnedToCore(sensorTask, "sensors", 6144, nullptr, 4, nullptr, 1); }
}  // namespace Sensors
