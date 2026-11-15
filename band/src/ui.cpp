#include "ui.h"
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_GC9A01A.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>
#include <Fonts/FreeSansBold24pt7b.h>
#include "config.h"
#include "log.h"
#include "state.h"
#include "util.h"

namespace {

constexpr int W = 240, H = 240, CX = 120;

// RGB565
constexpr uint16_t C_BG       = 0x0000;
constexpr uint16_t C_WHITE    = 0xFFFF;
constexpr uint16_t C_LABEL    = 0x8C71;  // серый 140
constexpr uint16_t C_DIM      = 0x4208;  // тёмно-серый
constexpr uint16_t C_FRAME    = 0x18C3;  // рамка графика
constexpr uint16_t C_OK       = 0x2E4F;  // зелёно-бирюзовый
constexpr uint16_t C_WARN     = 0xFD40;  // янтарный
constexpr uint16_t C_CRIT     = 0xF186;  // красный
constexpr uint16_t C_CRIT_DIM = 0x5800;  // тёмно-красный (мигание)
constexpr uint16_t C_ECG      = 0x2E4F;
constexpr uint16_t C_PPG      = 0x065F;  // голубой

Adafruit_GC9A01A* tft = nullptr;
GFXcanvas16* cv = nullptr;

// ---------- текст ----------
// Для GFX-шрифтов y — базовая линия, для встроенного (font = nullptr) — верх строки.
void text(const char* s, int cx, int y, const GFXfont* font, uint16_t color) {
  cv->setFont(font);
  cv->setTextSize(1);
  cv->setTextColor(color);
  int16_t x1, y1;
  uint16_t w, h;
  cv->getTextBounds(s, 0, y, &x1, &y1, &w, &h);
  cv->setCursor(cx - static_cast<int>(w) / 2 - x1, y);
  cv->print(s);
}

uint16_t levelColor(Level l) {
  switch (l) {
    case Level::Crit: return C_CRIT;
    case Level::Warn: return C_WARN;
    default: return C_OK;
  }
}

uint16_t valueColor(bool valid, Level l) {
  if (!valid) return C_DIM;
  switch (l) {
    case Level::Crit: return C_CRIT;
    case Level::Warn: return C_WARN;
    default: return C_WHITE;
  }
}

void flush() {
  tft->startWrite();
  tft->setAddrWindow(0, 0, W, H);
  tft->writePixels(cv->getBuffer(), static_cast<uint32_t>(W) * H);
  tft->endWrite();
}

// ---------- статус сети / батареи ----------
void drawStatus(const Vitals& v, const NetStatus& n, int baseline) {
  const char* lbl;
  uint16_t dot;
  switch (n.state) {
    case NetState::Online:   lbl = "LINK";    dot = C_OK;   break;
    case NetState::WifiOnly: lbl = "WIFI";    dot = C_WARN; break;
    default:                 lbl = "OFFLINE"; dot = C_DIM;  break;
  }
  char s[32];
  int len = snprintf(s, sizeof s, "%s", lbl);
  if (n.queued > 0 && len < static_cast<int>(sizeof s))
    len += snprintf(s + len, sizeof s - len, " Q%u", static_cast<unsigned>(n.queued));
  if (v.battValid && len < static_cast<int>(sizeof s))
    snprintf(s + len, sizeof s - len, "  %u%%", static_cast<unsigned>(v.battPct));

  cv->setFont(&FreeSans9pt7b);
  cv->setTextSize(1);
  int16_t x1, y1;
  uint16_t w, h;
  cv->getTextBounds(s, 0, baseline, &x1, &y1, &w, &h);
  const int x = CX - static_cast<int>(w) / 2 + 7;  // место под точку слева
  cv->fillCircle(x - 10, baseline - 5, 4, dot);
  cv->setTextColor(C_LABEL);
  cv->setCursor(x - x1, baseline);
  cv->print(s);
}

// ---------- графики ----------
void drawEcgTrace(int x0, int w, int yT, int yB) {
  constexpr int kDec = 4;  // 4 сэмпла на пиксель → 180 px = 2.9 с
  const uint32_t need = static_cast<uint32_t>(w) * kDec;
  const uint32_t head = EcgRing::head();
  if (head < need) return;
  const uint32_t start = head - need;

  int mn = 4095, mx = 0;
  for (uint32_t i = 0; i < need; i++) {
    const int s = EcgRing::at(start + i);
    if (s < mn) mn = s;
    if (s > mx) mx = s;
  }
  int span = mx - mn;
  if (span < 150) {
    const int mid = (mx + mn) / 2;
    mn = mid - 75;
    span = 150;
  }
  const int hgt = yB - yT;
  auto Y = [&](int s) {
    int y = yB - (s - mn) * hgt / span;
    return y < yT ? yT : (y > yB ? yB : y);
  };

  int prevY = -1;
  for (int px = 0; px < w; px++) {
    int lo = 4095, hi = 0, lastS = 0;
    for (int k = 0; k < kDec; k++) {
      lastS = EcgRing::at(start + static_cast<uint32_t>(px * kDec + k));
      if (lastS < lo) lo = lastS;
      if (lastS > hi) hi = lastS;
    }
    int y1 = Y(hi), y2 = Y(lo);  // min/max в столбце — R-пики не теряются
    if (prevY >= 0) {
      if (prevY < y1) y1 = prevY;
      if (prevY > y2) y2 = prevY;
    }
    cv->drawFastVLine(x0 + px, y1, y2 - y1 + 1, C_ECG);
    prevY = Y(lastS);
  }
}

void drawPpgTrace(int x0, int w, int yT, int yB) {
  constexpr int kDec = 2;  // 100 Гц, 2 сэмпла на пиксель → 3.6 с
  const uint32_t need = static_cast<uint32_t>(w) * kDec;
  const uint32_t head = PpgRing::head();
  if (head < need) return;
  const uint32_t start = head - need;

  float mn = 1e9f, mx = -1e9f;
  for (uint32_t i = 0; i < need; i++) {
    const float s = PpgRing::at(start + i);
    if (s < mn) mn = s;
    if (s > mx) mx = s;
  }
  float span = mx - mn;
  if (span < 20.0f) {
    const float mid = 0.5f * (mx + mn);
    mn = mid - 10.0f;
    span = 20.0f;
  }
  const int hgt = yB - yT;
  int prevY = -1;
  for (int px = 0; px < w; px++) {
    float acc = 0;
    for (int k = 0; k < kDec; k++) acc += PpgRing::at(start + static_cast<uint32_t>(px * kDec + k));
    int y = yB - static_cast<int>((acc / kDec - mn) * hgt / span);
    if (y < yT) y = yT;
    if (y > yB) y = yB;
    if (prevY >= 0) cv->drawLine(x0 + px - 1, prevY, x0 + px, y, C_PPG);
    prevY = y;
  }
}

void drawWave(const Vitals& v) {
  constexpr int x0 = 30, w = 180, yT = 106, yB = 142;
  cv->drawRoundRect(x0 - 3, yT - 3, w + 6, (yB - yT) + 6, 5, C_FRAME);
  const char* tag = nullptr;
  if (!v.ecgLeadsOff) {
    drawEcgTrace(x0, w, yT, yB);
    tag = "ECG";
  } else if (v.fingerOn) {
    drawPpgTrace(x0, w, yT, yB);
    tag = "PPG";
  } else {
    text("NO SIGNAL", CX, yT + 14, nullptr, C_DIM);
  }
  if (tag) {
    cv->setFont(nullptr);
    cv->setTextSize(1);
    cv->setTextColor(C_DIM);
    cv->setCursor(x0 + 1, yT);
    cv->print(tag);
  }
}

// ---------- кольцо состояния ----------
void drawRing(Level l, bool blink) {
  uint16_t c = levelColor(l);
  int th = 2;
  if (l == Level::Crit) {
    th = 5;
    if (!blink) c = C_CRIT_DIM;
  }
  for (int i = 0; i < th; i++) cv->drawCircle(CX, CX, 119 - i, c);
}

// ---------- дашборд (норма / warn) ----------
void drawDashboard(const Vitals& v, const AlertState& a, const NetStatus& n) {
  char b[24];
  drawStatus(v, n, 34);

  // Пульс
  if (v.hrValid) snprintf(b, sizeof b, "%d", static_cast<int>(lroundf(v.hr)));
  else strcpy(b, "--");
  text(b, CX, 86, &FreeSansBold24pt7b, valueColor(v.hrValid, a.level[mi(Metric::HR)]));
  text("bpm", CX, 101, &FreeSans9pt7b, C_LABEL);

  drawWave(v);

  // SpO2 (* = оценка без калибровки)
  text("SpO2*", 80, 150, nullptr, C_LABEL);
  if (v.spo2Valid) snprintf(b, sizeof b, "%d%%", static_cast<int>(lroundf(v.spo2)));
  else strcpy(b, "--");
  text(b, 80, 177, &FreeSansBold12pt7b, valueColor(v.spo2Valid, a.level[mi(Metric::SpO2)]));

  // Кожа: при прогреве показываем прогноз с «~»
  const bool skinShowPred = v.skinValid && v.skinWarming;
  text(skinShowPred ? "SKIN ~C" : "SKIN C", 160, 150, nullptr, C_LABEL);
  if (v.skinValid) snprintf(b, sizeof b, "%.1f", skinShowPred ? v.skinPred : v.skinT);
  else strcpy(b, "--");
  text(b, 160, 177, &FreeSansBold12pt7b, valueColor(v.skinValid && v.skinOnBody, a.level[mi(Metric::SkinT)]));

  // CO2
  text("CO2 ppm", 84, 184, nullptr, C_LABEL);
  if (v.co2Valid) snprintf(b, sizeof b, "%u", static_cast<unsigned>(v.co2));
  else strcpy(b, "--");
  text(b, 84, 210, &FreeSansBold12pt7b, valueColor(v.co2Valid, a.level[mi(Metric::CO2)]));

  // Давление (BMP390), а если его нет — температура воздуха с SCD41
  if (v.bmpOk) {
    text("P hPa", 156, 184, nullptr, C_LABEL);
    if (v.presValid) snprintf(b, sizeof b, "%.0f", v.pressure);
    else strcpy(b, "--");
    text(b, 156, 210, &FreeSansBold12pt7b, valueColor(v.presValid, a.level[mi(Metric::Pressure)]));
  } else {
    text("AIR C", 156, 184, nullptr, C_LABEL);
    if (v.co2Valid) snprintf(b, sizeof b, "%.1f", v.airT);
    else strcpy(b, "--");
    text(b, 156, 210, &FreeSansBold12pt7b, valueColor(v.co2Valid, Level::Ok));
  }

  // Подсказка внизу — одна, по приоритету
  const char* msg = nullptr;
  if (!v.ppgOk && !v.imuOk && !v.bmpOk && !v.scdOk && !v.skinOk) msg = "NO SENSORS";
  else if (v.moving) msg = "MOTION";
  else if (v.ppgOk && !v.fingerOn) msg = "PLACE FINGER";
  else if (v.skinValid && v.skinWarming) msg = "TEMP SETTLING";
  else if (ECG_ENABLED && v.ecgLeadsOff) msg = "ECG LEADS OFF";
  if (msg) text(msg, CX, 216, nullptr, C_DIM);
}

// ---------- фокус-экран (crit) ----------
void fmtOr(char* dst, size_t cap, bool valid, const char* fmt, float val) {
  if (valid) snprintf(dst, cap, fmt, val);
  else snprintf(dst, cap, "--");
}

void drawFocus(const Vitals& v, const AlertState& a, const NetStatus& n, bool blink) {
  char val[16] = "--", dev[40] = "";
  const char* name = "";
  const char* unit = "";

  switch (a.focus) {
    case Metric::HR:
      name = "HEART RATE";
      unit = "bpm";
      snprintf(val, sizeof val, "%d", static_cast<int>(lroundf(v.hr)));
      snprintf(dev, sizeof dev, "%+d vs rest %d", static_cast<int>(lroundf(v.hr - Cfg::HR_REST)),
               static_cast<int>(Cfg::HR_REST));
      break;
    case Metric::SpO2:
      name = "SpO2";
      unit = "% (estimate)";
      snprintf(val, sizeof val, "%d", static_cast<int>(lroundf(v.spo2)));
      snprintf(dev, sizeof dev, "%+d vs norm %d", static_cast<int>(lroundf(v.spo2 - Cfg::SPO2_NORM)),
               static_cast<int>(Cfg::SPO2_NORM));
      break;
    case Metric::SkinT:
      name = "SKIN TEMP";
      unit = "C";
      snprintf(val, sizeof val, "%.1f", v.skinT);
      snprintf(dev, sizeof dev, "%+.1f vs norm %.1f", v.skinT - Cfg::SKIN_T_NORM, Cfg::SKIN_T_NORM);
      break;
    case Metric::CO2:
      name = "CO2";
      unit = "ppm";
      snprintf(val, sizeof val, "%u", static_cast<unsigned>(v.co2));
      snprintf(dev, sizeof dev, "limit %u ppm", static_cast<unsigned>(Cfg::CO2_CRIT));
      break;
    case Metric::Pressure:
      name = "PRESSURE";
      unit = "hPa";
      snprintf(val, sizeof val, "%.1f", v.pressure);
      if (v.presRateValid && fabsf(v.presRate) >= Cfg::PRES_RATE_WARN)
        snprintf(dev, sizeof dev, "%+.1f hPa/min", v.presRate);
      else
        snprintf(dev, sizeof dev, "%+.1f vs base", v.pressure - v.presBase);
      break;
    default:
      break;
  }

  text("ALERT", CX, 44, &FreeSans9pt7b, blink ? C_CRIT : C_CRIT_DIM);
  text(name, CX, 72, &FreeSansBold12pt7b, C_WHITE);
  text(val, CX, 126, &FreeSansBold24pt7b, blink ? C_CRIT : C_WHITE);
  text(unit, CX, 146, &FreeSans9pt7b, C_LABEL);
  text(dev, CX, 172, &FreeSans9pt7b, C_WARN);

  // Остальные витальные — мелко
  char hr[8], sp[8], tk[8], sec[40];
  fmtOr(hr, sizeof hr, v.hrValid, "%.0f", v.hr);
  fmtOr(sp, sizeof sp, v.spo2Valid, "%.0f", v.spo2);
  fmtOr(tk, sizeof tk, v.skinValid, "%.1f", v.skinT);
  snprintf(sec, sizeof sec, "HR %s  SpO2 %s  T %s", hr, sp, tk);
  text(sec, CX, 196, nullptr, C_LABEL);

  drawStatus(v, n, 224);
}

void renderFrame() {
  const Vitals v = State::getVitals();
  const AlertState a = State::getAlerts();
  const NetStatus n = State::getNet();
  const bool blink = (millis() / 300) & 1;

  cv->fillScreen(C_BG);
  if (a.overall == Level::Crit) drawFocus(v, a, n, blink);
  else drawDashboard(v, a, n);
  drawRing(a.overall, blink);
  flush();
}

void uiTask(void*) {
  wdtAddThisTask();
  const TickType_t period = pdMS_TO_TICKS(1000 / UI_FPS);
  TickType_t last = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&last, period);
    renderFrame();
    wdtFeed();
  }
}

}  // namespace

namespace Ui {

bool begin() {
#if TFT_USE_SOFT_SPI
  tft = new Adafruit_GC9A01A(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_MOSI, PIN_TFT_SCLK, PIN_TFT_RST);
  tft->begin();
#else
  SPI.begin(PIN_TFT_SCLK, -1, PIN_TFT_MOSI, -1);  // CS не отдаём SPI-периферии — им управляет библиотека
  tft = new Adafruit_GC9A01A(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);
  tft->begin(TFT_SPI_HZ);
#endif
  tft->setRotation(0);
  tft->fillScreen(C_BG);

  cv = new GFXcanvas16(W, H);
  if (!cv->getBuffer()) {
    LOGE("UI: framebuffer alloc failed (%d bytes)", W * H * 2);
    delete cv;
    cv = nullptr;
    return false;
  }

  cv->fillScreen(C_BG);
  for (int i = 0; i < 2; i++) cv->drawCircle(CX, CX, 119 - i, C_OK);
  text("ASTRO BAND", CX, 112, &FreeSansBold12pt7b, C_WHITE);
  char fw[24];
  snprintf(fw, sizeof fw, "fw %s", FW_VERSION);
  text(fw, CX, 130, nullptr, C_LABEL);
  text("starting...", CX, 146, nullptr, C_DIM);
  flush();
  LOGI("UI: display ready");
  return true;
}

void start() {
  if (!cv) {
    LOGE("UI: not started (no framebuffer)");
    return;
  }
  xTaskCreatePinnedToCore(uiTask, "ui", 6144, nullptr, 2, nullptr, 1);
}

}  // namespace Ui
