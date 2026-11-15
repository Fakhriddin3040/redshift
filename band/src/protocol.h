#pragma once
#include <Arduino.h>
#include "state.h"

// ============================================================
//  Протокол Vigil v1 (band → server, WSS, только binary).
//  1 кадр = 32 байта, little-endian, 1 кадр в секунду.
//  Сервер ничего не отвечает. ЭКГ в этом протоколе нет.
// ============================================================

struct TelemetryRecord {
  uint8_t seq = 0;       // 0…255, +1 на кадр, переполняется
  uint32_t tsSec = 0;    // unix-время, секунды UTC (строго растёт)
  Vitals v;
};

namespace Protocol {

enum class FrameType : uint8_t { Text, Binary };

constexpr uint8_t  VER          = 1;
constexpr uint8_t  TYPE_SECOND  = 1;
constexpr size_t   FRAME_SIZE   = 32;
constexpr uint16_t NO_U16       = 0xFFFF;
constexpr int16_t  NO_I16       = 0x7FFF;
constexpr uint8_t  NO_U8        = 0xFF;

enum Flag : uint8_t {
  F_WORN            = 1u << 0,
  F_CHARGING        = 1u << 1,
  F_ECG_CONTACT     = 1u << 2,
  F_MOTION_ARTIFACT = 1u << 3,
  F_EXERCISE        = 1u << 4,
  F_HISTORY         = 1u << 7,
};

struct __attribute__((packed)) VigilFrame {
  uint8_t  ver, type;
  uint16_t dev_id;
  uint32_t ts;
  uint16_t hr_x10, spo2_x10, rr_x10;
  int16_t  skin_t_x100;
  uint16_t co2_ppm, press_x10, act_mg;
  uint8_t  sqi, flags, batt, seq;
  uint16_t hrv_ms;
  int16_t  amb_t_x100;
  uint16_t crc;
};
static_assert(sizeof(VigilFrame) == FRAME_SIZE, "VigilFrame must be exactly 32 bytes");

// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, без отражения, без финального XOR)
uint16_t crc16(const uint8_t* d, size_t n);

// Vitals → кадр (no-data коды, масштабирование, флаги). CRC считается здесь же.
VigilFrame fromRecord(const TelemetryRecord& r, uint16_t devId, bool history);

// Кадр в buf. Возвращает длину (32) или 0, если буфер мал.
size_t encodeTelemetry(const TelemetryRecord& r, bool history, uint8_t* buf, size_t cap, FrameType& type);

// Сервер ничего не шлёт; если что-то придёт — только лог.
void onMessage(const uint8_t* data, size_t len, bool binary);

}  // namespace Protocol
