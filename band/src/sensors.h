#pragma once

// Задача sensors — единственный владелец шины I2C.
// MAX30102 опрос FIFO 50 Гц, BMI270 25 Гц, MAX30205/BMP390/SCD41 1 Гц.
// Публикует Vitals и AlertState 10 раз в секунду.
namespace Sensors {
void start();
}
