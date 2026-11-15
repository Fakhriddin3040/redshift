#pragma once
#include <Arduino.h>

// AD8232: задача 250 Гц, единственный владелец АЦП (ECG + батарея).
namespace Ecg {
void start();
bool leadsOff();
bool battValid();
float battVolts();
}  // namespace Ecg
