#include "protocol.h"
#include "config.h"
#include "log.h"
#include "secrets.h"

namespace {

// round(value × scale); вне диапазона — прижимаем, но никогда не попадаем в no-data код
uint16_t u16Scaled(bool valid, float v, float scale) {
  if (!valid) return Protocol::NO_U16;
  long x = lroundf(v * scale);
  if (x < 0) x = 0;
  if (x > 0xFFFE) x = 0xFFFE;
  return static_cast<uint16_t>(x);
}

int16_t i16Scaled(bool valid, float v, float scale) {
  if (!valid) return Protocol::NO_I16;
  long x = lroundf(v * scale);
  if (x < -32768) x = -32768;
  if (x > 0x7FFE) x = 0x7FFE;
  return static_cast<int16_t>(x);
}

}  // namespace

namespace Protocol {

uint16_t crc16(const uint8_t* d, size_t n) {
  uint16_t c = 0xFFFF;
  while (n--) {
    c ^= static_cast<uint16_t>(*d++) << 8;
    for (int i = 0; i < 8; i++) c = (c & 0x8000) ? static_cast<uint16_t>((c << 1) ^ 0x1021) : static_cast<uint16_t>(c << 1);
  }
  return c;
}

VigilFrame fromRecord(const TelemetryRecord& r, uint16_t devId, bool history) {
  const Vitals& v = r.v;
  VigilFrame f;
  f.ver = VER;
  f.type = TYPE_SECOND;
  f.dev_id = devId;
  f.ts = r.tsSec;

  f.hr_x10   = u16Scaled(v.hrValid, v.hr, 10.0f);
  f.spo2_x10 = u16Scaled(PROTO_SEND_SPO2 && v.spo2Valid, v.spo2, 10.0f);
  f.rr_x10   = NO_U16;  // частоты дыхания нет
  f.skin_t_x100 = i16Scaled(v.skinValid, v.skinT, 100.0f);
  f.co2_ppm  = v.co2Valid ? (v.co2 > 0xFFFE ? 0xFFFE : v.co2) : NO_U16;
  f.press_x10 = u16Scaled(v.presValid, v.pressure, 10.0f);
  f.act_mg   = v.actValid ? (v.actMg > 0xFFFE ? 0xFFFE : v.actMg) : NO_U16;

  f.sqi = v.fingerOn ? (v.ppgQuality > 100 ? 100 : v.ppgQuality) : 0;

  uint8_t flags = 0;
#if RELAXED_VALIDITY
  if (v.fingerOn || v.skinValid) flags |= F_WORN;   // датчик кожи отвечает — считаем надетым
#else
  if (v.fingerOn || v.skinOnBody) flags |= F_WORN;
#endif
  if (ECG_ENABLED && !v.ecgLeadsOff) flags |= F_ECG_CONTACT;
  if (v.moving) flags |= F_MOTION_ARTIFACT;
  if (history) flags |= F_HISTORY;
  f.flags = flags;

  f.batt = v.battValid ? (v.battPct > 100 ? 100 : v.battPct) : NO_U8;
  f.seq = r.seq;
  f.hrv_ms = u16Scaled(v.hrvValid, v.rmssd, 1.0f);

  // Температура воздуха: SCD41, иначе BMP390
  if (v.co2Valid) f.amb_t_x100 = i16Scaled(true, v.airT, 100.0f);
  else f.amb_t_x100 = i16Scaled(v.presValid, v.bmpT, 100.0f);

  f.crc = crc16(reinterpret_cast<const uint8_t*>(&f), FRAME_SIZE - 2);
  return f;
}

size_t encodeTelemetry(const TelemetryRecord& r, bool history, uint8_t* buf, size_t cap, FrameType& type) {
  type = FrameType::Binary;
  if (cap < FRAME_SIZE) return 0;
  const VigilFrame f = fromRecord(r, DEVICE_NUM_ID, history);
  memcpy(buf, &f, FRAME_SIZE);  // ESP32 little-endian — структура уходит как есть
  return FRAME_SIZE;
}

void onMessage(const uint8_t* data, size_t len, bool binary) {
  (void)data;
  LOGW("WS rx: unexpected %s message, %u bytes (protocol is band→server only)", binary ? "binary" : "text",
       static_cast<unsigned>(len));
}

}  // namespace Protocol
