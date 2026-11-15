#include "net.h"
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <time.h>
#include "config.h"
#include "log.h"
#include "protocol.h"
#include "secrets.h"
#include "state.h"

namespace {

WebSocketsClient ws;
bool wsStarted = false, wsConnected = false, wifiUp = false, ntpStarted = false;

TelemetryRecord s_queue[NET_QUEUE_LEN];
uint16_t qHead = 0, qCount = 0;
uint8_t s_seq = 0;          // seq в кадре: 0…255, +1 на кадр
uint32_t s_lastTs = 0;      // ts последнего сформированного кадра (строго растёт)
uint32_t s_sent = 0, s_dropped = 0;
uint8_t s_tx[NET_TX_BUF];

// unix-время в секундах; 0 — NTP ещё не синхронизировал
uint32_t epochSec() {
  const time_t t = time(nullptr);
  return t > 1700000000 ? static_cast<uint32_t>(t) : 0;
}

void onWsEvent(WStype_t type, uint8_t* payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      LOGI("WS: connected (%u frames queued)", static_cast<unsigned>(qCount));
      break;
    case WStype_DISCONNECTED:
      if (wsConnected) LOGW("WS: disconnected");
      wsConnected = false;
      break;
    case WStype_TEXT:
      Protocol::onMessage(payload, len, false);
      break;
    case WStype_BIN:
      Protocol::onMessage(payload, len, true);
      break;
    case WStype_ERROR:
      LOGW("WS: error");
      break;
    default:
      break;
  }
}

void startWs() {
  // CA = nullptr → setInsecure(): TLS-шифрование без проверки сертификата.
  // protocol = "" → без Sec-WebSocket-Protocol.
  ws.beginSslWithCA(WS_HOST, WS_PORT, WS_PATH, nullptr, "");
  ws.setExtraHeaders("");  // убираем дефолтный "Origin: file://" библиотеки
  ws.onEvent(onWsEvent);
  ws.setReconnectInterval(NET_WS_RECONNECT_MS);
  ws.enableHeartbeat(NET_WS_PING_MS, NET_WS_PONG_TIMEOUT_MS, NET_WS_PONG_FAILS);
  wsStarted = true;
  LOGI("WS: wss://%s:%d%s, dev_id=%d", WS_HOST, WS_PORT, WS_PATH, DEVICE_NUM_ID);
}

// Один кадр на каждую новую секунду UTC. Если ядро было занято (TLS-handshake)
// и секунды пропущены — просто идём дальше: ts всё равно строго растёт.
void enqueueFrame(uint32_t ts) {
  TelemetryRecord& r = s_queue[qHead];  // при полной очереди перезаписываем самую старую
  r.seq = s_seq++;
  r.tsSec = ts;
  r.v = State::getVitals();
  qHead = (qHead + 1) % NET_QUEUE_LEN;
  if (qCount < NET_QUEUE_LEN) qCount++;
  else s_dropped++;
}

// Синим: что именно ушло на сервер, в человеческих единицах ("--" = код «нет данных»)
void logSent(bool history) {
#if DEBUG_VITALS
  Protocol::VigilFrame f;
  memcpy(&f, s_tx, sizeof f);
  char hr[8], sp[8], hv[8], sk[10], am[10], co[8], ac[8], pr[10], bt[6];
  auto u = [](char* d, size_t n, uint16_t v, float div, int prec) {
    if (v == Protocol::NO_U16) snprintf(d, n, "--");
    else snprintf(d, n, "%.*f", prec, static_cast<double>(v / div));
  };
  auto i = [](char* d, size_t n, int16_t v) {
    if (v == Protocol::NO_I16) snprintf(d, n, "--");
    else snprintf(d, n, "%.2f", static_cast<double>(v / 100.0f));
  };
  u(hr, sizeof hr, f.hr_x10, 10.0f, 1);
  u(sp, sizeof sp, f.spo2_x10, 10.0f, 1);
  u(hv, sizeof hv, f.hrv_ms, 1.0f, 0);
  u(co, sizeof co, f.co2_ppm, 1.0f, 0);
  u(ac, sizeof ac, f.act_mg, 1.0f, 0);
  u(pr, sizeof pr, f.press_x10, 10.0f, 1);
  i(sk, sizeof sk, f.skin_t_x100);
  i(am, sizeof am, f.amb_t_x100);
  if (f.batt == Protocol::NO_U8) snprintf(bt, sizeof bt, "--");
  else snprintf(bt, sizeof bt, "%u", f.batt);
  LOGBLU("SENT seq=%u ts=%lu | hr=%s spo2=%s hrv=%s skin=%s amb=%s co2=%s act=%s press=%s batt=%s | sqi=%u flags=0x%02X%s%s%s%s",
         f.seq, static_cast<unsigned long>(f.ts), hr, sp, hv, sk, am, co, ac, pr, bt, f.sqi, f.flags,
         (f.flags & Protocol::F_WORN) ? " WORN" : "", (f.flags & Protocol::F_ECG_CONTACT) ? " ECG" : "",
         (f.flags & Protocol::F_MOTION_ARTIFACT) ? " MOTION" : "", history ? " HISTORY" : "");
#else
  (void)history;
#endif
}

void flushQueue(int budget) {
  const uint32_t now = epochSec();
  while (qCount > 0 && budget-- > 0) {
    const uint16_t tail = (qHead + NET_QUEUE_LEN - qCount) % NET_QUEUE_LEN;
    const TelemetryRecord& r = s_queue[tail];
    const bool history = now > r.tsSec + NET_HISTORY_AGE_S;
    Protocol::FrameType t;
    const size_t n = Protocol::encodeTelemetry(r, history, s_tx, sizeof s_tx, t);
    if (n == 0) {
      LOGE("NET: encode failed — frame skipped");
      qCount--;
      continue;
    }
    const bool ok = (t == Protocol::FrameType::Binary) ? ws.sendBIN(s_tx, n) : ws.sendTXT(s_tx, n);
    if (!ok) return;  // не ушло — остаётся в очереди
    s_sent++;
    qCount--;
    logSent(history);
  }
}

void publishStatus() {
  NetStatus s;
  s.state = wsConnected ? NetState::Online : (wifiUp ? NetState::WifiOnly : NetState::Offline);
  s.queued = qCount;
  s.sent = s_sent;
  s.dropped = s_dropped;
  s.timeSynced = epochSec() != 0;
  s.rssi = wifiUp ? static_cast<int8_t>(WiFi.RSSI()) : 0;
  State::setNet(s);
}

void netTask(void*) {
  WiFi.persistent(false);
  WiFi.setHostname(DEVICE_ID);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  WiFi.setTxPower(NET_WIFI_TX_POWER);  // после begin — иначе на части плат не применяется
  LOGI("WiFi: connecting to \"%s\"", WIFI_SSID);

  uint32_t tKick = millis(), tStat = 0;
  bool loggedTime = false;

  for (;;) {
    const uint32_t now = millis();
    const bool up = WiFi.status() == WL_CONNECTED;

    if (up && !wifiUp) {
      LOGI("WiFi: connected, IP %s, RSSI %d", WiFi.localIP().toString().c_str(), WiFi.RSSI());
      if (!ntpStarted) {
        configTime(0, 0, NET_NTP1, NET_NTP2);  // UTC
        ntpStarted = true;
      }
      if (!wsStarted) startWs();
    } else if (!up && wifiUp) {
      LOGW("WiFi: lost");
      if (wsConnected) ws.disconnect();
      wsConnected = false;
      tKick = now;
    }
    wifiUp = up;

    if (!up && now - tKick >= NET_WIFI_RETRY_MS) {
      tKick = now;
      LOGI("WiFi: retry");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      WiFi.setTxPower(NET_WIFI_TX_POWER);
    }

    if (up && wsStarted) ws.loop();

    // Кадры — только с валидным UTC: без него сервер отбросит их как stale
    const uint32_t sec = epochSec();
    if (sec != 0) {
      if (!loggedTime) {
        LOGI("NTP: time synced, ts=%lu", static_cast<unsigned long>(sec));
        loggedTime = true;
      }
      // Пока датчики не выдали первые значения, кадры не формируем — пустые не шлём
      if (sec > s_lastTs && State::getVitals().ready) {
        s_lastTs = sec;
        enqueueFrame(sec);
      }
    }

    if (wsConnected) flushQueue(NET_FLUSH_BUDGET);

    if (now - tStat >= 250) {
      tStat = now;
      publishStatus();
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

}  // namespace

namespace Net {
void start() { xTaskCreatePinnedToCore(netTask, "net", 12288, nullptr, 3, nullptr, 0); }
}  // namespace Net
