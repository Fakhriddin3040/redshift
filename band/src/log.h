#pragma once
#include <Arduino.h>
#include "config.h"

#define LOGE(fmt, ...) do { if (LOG_LEVEL >= 1) Serial.printf("[E] " fmt "\n", ##__VA_ARGS__); } while (0)
#define LOGW(fmt, ...) do { if (LOG_LEVEL >= 2) Serial.printf("[W] " fmt "\n", ##__VA_ARGS__); } while (0)
#define LOGD(fmt, ...) do { if (DEBUG_VITALS) Serial.printf("[D] " fmt "\n", ##__VA_ARGS__); } while (0)
#if LOG_COLOR
#define C_RED "\033[1;31m"
#define C_GRN "\033[32m"
#define C_BLU "\033[1;34m"
#define C_OFF "\033[0m"
#else
#define C_RED ""
#define C_GRN ""
#define C_BLU ""
#define C_OFF ""
#endif
#define LOGRED(fmt, ...) do { if (DEBUG_VITALS) Serial.printf(C_RED "[!] " fmt C_OFF "\n", ##__VA_ARGS__); } while (0)
#define LOGBLU(fmt, ...) do { if (DEBUG_VITALS) Serial.printf(C_BLU "[>] " fmt C_OFF "\n", ##__VA_ARGS__); } while (0)
#define LOGGRN(fmt, ...) do { if (DEBUG_VITALS) Serial.printf(C_GRN "[+] " fmt C_OFF "\n", ##__VA_ARGS__); } while (0)
#define LOGI(fmt, ...) do { if (LOG_LEVEL >= 3) Serial.printf("[I] " fmt "\n", ##__VA_ARGS__); } while (0)
