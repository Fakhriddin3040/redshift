#include "alerts.h"
#include "config.h"

namespace {

Level maxLevel(Level a, Level b) { return a > b ? a : b; }

Level classifyHr(float hr) {
  if (hr < Cfg::HR_CRIT_LO || hr > Cfg::HR_CRIT_HI) return Level::Crit;
  if (hr < Cfg::HR_WARN_LO || hr > Cfg::HR_WARN_HI) return Level::Warn;
  return Level::Ok;
}

Level classifySpo2(float s) {
  if (s < Cfg::SPO2_CRIT) return Level::Crit;
  if (s < Cfg::SPO2_WARN) return Level::Warn;
  return Level::Ok;
}

Level classifySkin(float t) {
  if (t < Cfg::SKIN_CRIT_LO || t > Cfg::SKIN_CRIT_HI) return Level::Crit;
  if (t < Cfg::SKIN_WARN_LO || t > Cfg::SKIN_WARN_HI) return Level::Warn;
  return Level::Ok;
}

Level classifyCo2(uint16_t c) {
  if (c >= Cfg::CO2_CRIT) return Level::Crit;
  if (c >= Cfg::CO2_WARN) return Level::Warn;
  return Level::Ok;
}

Level classifyPressure(const Vitals& v) {
  Level l = Level::Ok;
  const float drift = fabsf(v.pressure - v.presBase);
  if (drift >= Cfg::PRES_DRIFT_CRIT) l = Level::Crit;
  else if (drift >= Cfg::PRES_DRIFT_WARN) l = Level::Warn;
  if (v.presRateValid) {
    const float rate = fabsf(v.presRate);
    if (rate >= Cfg::PRES_RATE_CRIT) l = maxLevel(l, Level::Crit);
    else if (rate >= Cfg::PRES_RATE_WARN) l = maxLevel(l, Level::Warn);
  }
  return l;
}

}  // namespace

Level AlertEngine::step(Track& t, bool valid, Level raw, uint32_t now) {
  if (!valid) {
    t.level = t.pending = Level::Ok;
    t.since = now;
    return t.level;
  }
  if (raw == t.level) {
    t.pending = raw;
    t.since = now;
    return t.level;
  }
  if (raw != t.pending) {
    t.pending = raw;
    t.since = now;
  }
  const uint32_t need = raw > t.level ? Cfg::ALERT_RAISE_MS : Cfg::ALERT_CLEAR_MS;
  if (now - t.since >= need) t.level = raw;
  return t.level;
}

AlertState AlertEngine::update(const Vitals& v, uint32_t now) {
  AlertState s;

  s.level[mi(Metric::HR)] =
      step(t_[mi(Metric::HR)], v.hrValid, v.hrValid ? classifyHr(v.hr) : Level::Ok, now);

  s.level[mi(Metric::SpO2)] =
      step(t_[mi(Metric::SpO2)], v.spo2Valid, v.spo2Valid ? classifySpo2(v.spo2) : Level::Ok, now);

  const bool skinUsable = v.skinValid && v.skinOnBody && !v.skinWarming;
  s.level[mi(Metric::SkinT)] =
      step(t_[mi(Metric::SkinT)], skinUsable, skinUsable ? classifySkin(v.skinT) : Level::Ok, now);

  s.level[mi(Metric::CO2)] =
      step(t_[mi(Metric::CO2)], v.co2Valid, v.co2Valid ? classifyCo2(v.co2) : Level::Ok, now);

  const bool presUsable = v.presValid && v.presBaseValid;
  s.level[mi(Metric::Pressure)] =
      step(t_[mi(Metric::Pressure)], presUsable, presUsable ? classifyPressure(v) : Level::Ok, now);

  // Общий уровень и метрика в фокусе (приоритет при равенстве)
  static const Metric priority[] = {Metric::SpO2, Metric::HR, Metric::Pressure, Metric::CO2, Metric::SkinT};
  s.overall = Level::Ok;
  for (Metric m : priority) s.overall = maxLevel(s.overall, s.level[mi(m)]);
  s.focus = Metric::HR;
  for (Metric m : priority) {
    if (s.level[mi(m)] == s.overall) { s.focus = m; break; }
  }
  return s;
}

const char* levelName(Level l) {
  switch (l) {
    case Level::Warn: return "warn";
    case Level::Crit: return "crit";
    default: return "ok";
  }
}

const char* metricName(Metric m) {
  switch (m) {
    case Metric::HR: return "hr";
    case Metric::SpO2: return "spo2";
    case Metric::SkinT: return "skin_t";
    case Metric::CO2: return "co2";
    case Metric::Pressure: return "pressure";
    default: return "none";
  }
}
