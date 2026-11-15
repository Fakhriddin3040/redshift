#include "state.h"
#include <atomic>

static_assert((ECG_RING_SIZE & (ECG_RING_SIZE - 1)) == 0, "ECG_RING_SIZE must be a power of 2");
static_assert((PPG_DISP_RING & (PPG_DISP_RING - 1)) == 0, "PPG_DISP_RING must be a power of 2");

static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static Vitals s_vitals;
static AlertState s_alerts;
static NetStatus s_net;

namespace State {

void setVitals(const Vitals& v) {
  portENTER_CRITICAL(&s_mux);
  s_vitals = v;
  portEXIT_CRITICAL(&s_mux);
}

Vitals getVitals() {
  portENTER_CRITICAL(&s_mux);
  Vitals v = s_vitals;
  portEXIT_CRITICAL(&s_mux);
  return v;
}

void setAlerts(const AlertState& a) {
  portENTER_CRITICAL(&s_mux);
  s_alerts = a;
  portEXIT_CRITICAL(&s_mux);
}

AlertState getAlerts() {
  portENTER_CRITICAL(&s_mux);
  AlertState a = s_alerts;
  portEXIT_CRITICAL(&s_mux);
  return a;
}

void setNet(const NetStatus& n) {
  portENTER_CRITICAL(&s_mux);
  s_net = n;
  portEXIT_CRITICAL(&s_mux);
}

NetStatus getNet() {
  portENTER_CRITICAL(&s_mux);
  NetStatus n = s_net;
  portEXIT_CRITICAL(&s_mux);
  return n;
}

}  // namespace State

// ---------------- ECG ring ----------------
namespace {
uint16_t s_ecgBuf[ECG_RING_SIZE];
std::atomic<uint32_t> s_ecgHead{0};
float s_ppgBuf[PPG_DISP_RING];
std::atomic<uint32_t> s_ppgHead{0};
}  // namespace

namespace EcgRing {
void push(uint16_t v) {
  const uint32_t h = s_ecgHead.load(std::memory_order_relaxed);
  s_ecgBuf[h & (ECG_RING_SIZE - 1)] = v;
  s_ecgHead.store(h + 1, std::memory_order_release);
}
uint32_t head() { return s_ecgHead.load(std::memory_order_acquire); }
uint16_t at(uint32_t idx) { return s_ecgBuf[idx & (ECG_RING_SIZE - 1)]; }
}  // namespace EcgRing

namespace PpgRing {
void push(float v) {
  const uint32_t h = s_ppgHead.load(std::memory_order_relaxed);
  s_ppgBuf[h & (PPG_DISP_RING - 1)] = v;
  s_ppgHead.store(h + 1, std::memory_order_release);
}
uint32_t head() { return s_ppgHead.load(std::memory_order_acquire); }
float at(uint32_t idx) { return s_ppgBuf[idx & (PPG_DISP_RING - 1)]; }
}  // namespace PpgRing
