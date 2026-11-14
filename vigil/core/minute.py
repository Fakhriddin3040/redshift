from dataclasses import dataclass
from statistics import fmean, median

from vigil.core import thresholds as th
from vigil.core.frame import Frame

VITALS = ("hr", "spo2", "rr", "skin_t", "hrv")
CABIN = ("co2_ppm", "press_hpa", "amb_t")


def ppco2(co2_ppm: float | None, press_hpa: float | None) -> float | None:
    if co2_ppm is None:
        return None
    press = th.STD_PRESSURE_HPA if press_hpa is None else press_hpa
    return co2_ppm * 1e-6 * press * th.MMHG_PER_HPA


@dataclass(slots=True)
class Minute:
    ts: int
    hr: float | None = None
    spo2: float | None = None
    rr: float | None = None
    skin_t: float | None = None
    hrv: float | None = None
    co2_ppm: float | None = None
    press_hpa: float | None = None
    amb_t: float | None = None
    act_mg: float | None = None
    sqi: float | None = None
    worn_frac: float = 0.0
    valid_s: int | None = None
    exercise: bool = False
    summary: bool = False  # came as a type-2 frame

    @property
    def ppco2(self) -> float | None:
        return ppco2(self.co2_ppm, self.press_hpa)

    def get(self, metric: str) -> float | None:
        if metric == "ppco2":
            return self.ppco2
        if metric == "press":
            return self.press_hpa
        return getattr(self, metric)


def _median_of(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return median(vals) if len(vals) >= th.MIN_VALID_SECONDS else None


def aggregate(minute_ts: int, seconds: list[Frame]) -> Minute:
    good = [f for f in seconds if f.sqi >= th.SQI_VALID]
    m = Minute(ts=minute_ts)
    for name in VITALS:
        setattr(m, name, _median_of([getattr(f, name) for f in good]))
    for name in CABIN:
        setattr(m, name, _median_of([getattr(f, name) for f in seconds]))
    acts = [f.act_mg for f in seconds if f.act_mg is not None]
    m.act_mg = fmean(acts) if acts else None
    m.sqi = fmean(f.sqi for f in seconds)
    m.worn_frac = sum(f.worn for f in seconds) / len(seconds)
    m.valid_s = sum(f.hr is not None for f in good)
    m.exercise = sum(f.exercise for f in seconds) * 2 > len(seconds)
    return m


def from_minute_frame(f: Frame) -> Minute:
    return Minute(
        ts=f.ts - f.ts % 60,
        hr=f.hr,
        spo2=f.spo2,
        rr=f.rr,
        skin_t=f.skin_t,
        hrv=f.hrv,
        co2_ppm=f.co2_ppm,
        press_hpa=f.press_hpa,
        amb_t=f.amb_t,
        act_mg=f.act_mg,
        sqi=float(f.sqi),
        worn_frac=1.0 if f.worn else 0.0,
        exercise=f.exercise,
        summary=True,
    )


class MinuteAggregator:
    """Buffers second frames; a minute closes when a frame of a later minute arrives."""

    def __init__(self) -> None:
        self._minute_ts: int | None = None
        self._seconds: list[Frame] = []

    def add(self, f: Frame) -> Minute | None:
        minute_ts = f.ts - f.ts % 60
        closed = self.close_before(minute_ts)
        self._minute_ts = minute_ts
        self._seconds.append(f)
        return closed

    def close_before(self, minute_ts: int) -> Minute | None:
        if self._minute_ts is None or self._minute_ts >= minute_ts:
            return None
        return self.flush()

    def flush(self) -> Minute | None:
        if not self._seconds:
            return None
        closed = aggregate(self._minute_ts, self._seconds)
        self._minute_ts, self._seconds = None, []
        return closed
