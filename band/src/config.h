#pragma once
#include <Arduino.h>

// ============================================================
//  Astro Band — конфигурация прошивки
//  Секреты (Wi-Fi, сервер, токен, сертификат) — в secrets.h
// ============================================================

#define FW_VERSION "0.1.0"

// ---------- Пины: ESP32-S3-Zero (ESP32-S3FH4R2) ----------
#define PIN_TFT_SCLK 12
#define PIN_TFT_MOSI 11
#define PIN_TFT_DC   10
#define PIN_TFT_CS    9
#define PIN_TFT_RST   8

#define PIN_I2C_SDA   5
#define PIN_I2C_SCL   6

#define PIN_ECG_OUT   1   // AD8232 OUTPUT — только ADC1 (ADC2 мёртв при Wi-Fi)
#define PIN_ECG_LO_P  4   // AD8232 LO+
#define PIN_ECG_LO_N  7   // AD8232 LO-

#define PIN_PPG_INT  13   // MAX30102 INT — зарезервирован, FIFO опрашивается по таймеру
#define PIN_BATT_ADC  2   // делитель 100k/100k с батареи (ADC1)

// ---------- I2C ----------
#define I2C_FREQ_HZ      100000
#define I2C_TIMEOUT_MS   50
#define ADDR_MAX30205    0x48
#define ADDR_MAX30102    0x57
#define ADDR_SCD41       0x62
#define ADDR_BMI270      0x68
#define ADDR_BMP390      0x77
#define I2C_DEV_MAX_FAILS 10        // подряд ошибок → устройство «потеряно», recovery шины, переинициализация
#define SENSOR_RETRY_MS   10000     // как часто пробовать поднять отсутствующие датчики

// ---------- Дисплей GC9A01 ----------
#define TFT_USE_SOFT_SPI 1          // 1 — программный SPI: медленно (~2–3 FPS), но заводится всегда
#define TFT_SPI_HZ       10000000    // на дюпонтах 10 МГц; после пайки коротких проводов — 27/40 МГц
#define UI_FPS           10

// ---------- ECG (AD8232) ----------
#ifndef ECG_ENABLED
#define ECG_ENABLED         0       // 0 — AD8232 не используется (задача не запускается)
#endif
#define ECG_FS_HZ           250
#define ECG_RING_SIZE       1024    // степень двойки, ~4 с при 250 Гц
#define ECG_LO_ON_SAMPLES   3       // антидребезг leads-off: столько подряд → электроды сняты
#define ECG_LO_OFF_SAMPLES  50      // столько подряд → электроды на месте (200 мс)

// ---------- PPG (MAX30102) ----------
#define PPG_LED_CURRENT     0x1F    // 0x1F ≈ 6.4 мА. Для запястья (отражение) поднимать до 0x3F..0x7F
#define PPG_FINGER_DC_MIN   50000   // IR DC выше порога — палец/кожа на датчике
#define PPG_DISP_RING       512     // степень двойки
#define SPO2_CAL_A          110.0f  // SpO2 = A - B*R. НЕ ОТКАЛИБРОВАНО — только оценка!
#define SPO2_CAL_B          25.0f

// ---------- IMU (BMI270) ----------
#define IMU_PERIOD_MS        40     // 25 Гц
#define IMU_MOTION_THRESH_G  0.08f  // выше — рука двигается, PPG не доверяем

// ---------- Батарея ----------
#define BATT_ENABLED        0       // 1 — когда подключён делитель на PIN_BATT_ADC
#define BATT_DIVIDER        2.0f
#define BATT_V_EMPTY        3.30f
#define BATT_V_FULL         4.20f

// ---------- Watchdog ----------
#define WDT_TIMEOUT_MS      10000

// ---------- Сеть ----------
// Кадр формируется на смене секунды UTC (NTP) — ts строго растёт, ровно 1 кадр/с.
#define NET_QUEUE_LEN           120     // буфер кадров в офлайне: 2 мин; после реконнекта уходят с флагом HISTORY
#define NET_HISTORY_AGE_S       2       // кадр старше — помечается HISTORY
#define NET_TX_BUF              64
#define PROTO_SEND_SPO2         1       // 0 — не слать SpO2 (оценка без калибровки, сервер проверяет жёсткие пороги)
#define NET_FLUSH_BUDGET        10      // сколько кадров из очереди за один проход
#define NET_WIFI_RETRY_MS       15000
// Мощность TX Wi-Fi. На S3-Zero / Super Mini на максимуме LDO проседает → обрывы.
// WIFI_POWER_8_5dBm — проверенное значение; при слабом сигнале попробуй WIFI_POWER_11dBm.
#define NET_WIFI_TX_POWER       WIFI_POWER_8_5dBm
#define NET_WS_RECONNECT_MS     5000
#define NET_WS_PING_MS          15000
#define NET_WS_PONG_TIMEOUT_MS  5000
#define NET_WS_PONG_FAILS       2
#define NET_NTP1 "pool.ntp.org"
#define NET_NTP2 "time.google.com"
#define NET_WARMUP_TIMEOUT_MS    12000

// ---------- Логи ----------
// 1 — «отдаём что есть»: значение уходит, как только оно посчитано, без проверок на движение,
//     число ударов и свежесть. «Нет данных» остаётся только когда датчика нет на шине,
//     на оптике нет пальца или значение ещё ни разу не посчитано.
// 0 — строгий режим (пороги качества).
#define RELAXED_VALIDITY 1
#define DEBUG_VITALS 1
#define LOG_COLOR 1                  // ANSI-цвета в Serial (в PlatformIO нужен monitor_filters = direct)               // 1 — раз в секунду подробная строка по каждому датчику и каждый отправленный кадр
#define LOG_LEVEL 3                 // 0 — выкл, 1 — ошибки, 2 — +warn, 3 — +info

namespace Cfg {
// Профиль пользователя — база для отклонений на экране
constexpr float HR_REST     = 70.0f;
constexpr float SKIN_T_NORM = 33.0f;
constexpr float SPO2_NORM   = 95.0f;

// Пороги тревог
constexpr float HR_WARN_LO = 50.0f, HR_WARN_HI = 110.0f;
constexpr float HR_CRIT_LO = 40.0f, HR_CRIT_HI = 140.0f;

constexpr float SPO2_WARN = 94.0f, SPO2_CRIT = 90.0f;

constexpr float SKIN_ONBODY_MIN = 24.5f;      // было 27
constexpr float SKIN_WARN_LO = 25.0f, SKIN_WARN_HI = 36.5f;   // было 30
constexpr float SKIN_CRIT_LO = 24.0f, SKIN_CRIT_HI = 38.0f;   // было 28

constexpr uint16_t CO2_WARN = 1500, CO2_CRIT = 3000;  // ppm

constexpr float PRES_DRIFT_WARN = 10.0f, PRES_DRIFT_CRIT = 30.0f;  // гПа от базы
constexpr float PRES_RATE_WARN  = 2.0f,  PRES_RATE_CRIT  = 5.0f;   // гПа/мин (разгерметизация)
constexpr int   PRES_BASE_SAMPLES = 30;                            // база = среднее первых N секунд

// Гистерезис: состояние должно продержаться столько, чтобы смениться
constexpr uint32_t ALERT_RAISE_MS = 3000;
constexpr uint32_t ALERT_CLEAR_MS = 5000;
}  // namespace Cfg
