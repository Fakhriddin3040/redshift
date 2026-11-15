import math
from collections import deque
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from vigil.core import thresholds as th
from vigil.core.context import Ctx
from vigil.core.minute import Minute


class Level(IntEnum):
    USUAL = 0
    WATCH = 1
    ALERT = 2
    CRITICAL = 3


def _round(x: float) -> int:
    return math.floor(x + 0.5)


def hard_level(metric: str, value: float | None, ctx: Ctx) -> int:
    if value is None or ctx == Ctx.OFF:
        return 0
    v = _round(value)
    if metric == "spo2":
        if v <= th.SPO2_CRITICAL_MAX:
            return Level.CRITICAL
        return Level.ALERT if v <= th.SPO2_ALERT_MAX else 0
    if metric == "hr" and ctx in (Ctx.REST, Ctx.SLEEP):
        if v >= th.HR_CRITICAL_MIN:
            return Level.CRITICAL
        if v >= th.HR_ALERT_MIN:
            return Level.ALERT
        if v <= th.HR_LOW_MAX:
            return Level.CRITICAL if ctx == Ctx.REST else Level.ALERT
        return 0
    if metric == "rr" and ctx in (Ctx.REST, Ctx.SLEEP):
        if v <= th.RR_CRITICAL_LOW_MAX or v >= th.RR_CRITICAL_HIGH_MIN:
            return Level.CRITICAL
        return Level.ALERT if v >= th.RR_ALERT_MIN else 0
    return 0


def directional_z(metric: str, z: float) -> float:
    """Magnitude that counts toward a level; SpO2 only counts downward."""
    if metric == "spo2":
        return max(-z, 0.0)
    return abs(z)


class ZRun:
    """Consecutive-minute counters for one metric (§7.1)."""

    __slots__ = ("n_watch", "n_alert", "last_ts")

    def __init__(self) -> None:
        self.n_watch = 0
        self.n_alert = 0
        self.last_ts: int | None = None

    def update(self, ts: int, dz: float | None) -> int:
        if self.last_ts is None or ts - self.last_ts != 60:
            self.n_watch = self.n_alert = 0
        self.last_ts = ts
        if dz is None:
            self.n_watch = self.n_alert = 0
            return 0
        self.n_watch = self.n_watch + 1 if dz >= th.WATCH_Z else 0
        self.n_alert = self.n_alert + 1 if dz >= th.ALERT_Z else 0
        if self.n_alert >= th.ALERT_RUN_MIN:
            return Level.ALERT
        if self.n_watch >= th.WATCH_RUN_MIN:
            return Level.WATCH
        return 0


@dataclass(slots=True)
class EnvEval:
    ppco2_mean: float | None = None
    ppco2_level: int = 0
    press: float | None = None
    press_level: int = 0
    press_median: float | None = None  # over the last 24 h


class EnvTracker:
    def __init__(self) -> None:
        self.ppco2: deque[tuple[int, float]] = deque()
        self.press: deque[tuple[int, float]] = deque()
        self._press_median: float | None = None
        self._press_median_at: int | None = None

    def push(self, ts: int, ppco2: float | None, press: float | None) -> None:
        if ppco2 is not None:
            self.ppco2.append((ts, ppco2))
        while self.ppco2 and self.ppco2[0][0] <= ts - th.PPCO2_WINDOW_S:
            self.ppco2.popleft()
        if press is not None:
            self.press.append((ts, press))
        while self.press and self.press[0][0] <= ts - th.PRESS_MEDIAN_WINDOW_S:
            self.press.popleft()

    def update(self, m: Minute) -> EnvEval:
        self.push(m.ts, m.ppco2, m.press_hpa)
        out = EnvEval()
        if len(self.ppco2) >= th.PPCO2_MIN_VALUES:
            out.ppco2_mean = sum(v for _, v in self.ppco2) / len(self.ppco2)
            if out.ppco2_mean > th.PPCO2_CRITICAL:
                out.ppco2_level = Level.CRITICAL
            elif out.ppco2_mean > th.PPCO2_ALERT:
                out.ppco2_level = Level.ALERT
            elif out.ppco2_mean > th.PPCO2_WATCH:
                out.ppco2_level = Level.WATCH
        if m.press_hpa is not None:
            out.press = m.press_hpa
            out.press_level = self._press_level(m.ts, m.press_hpa)
            out.press_median = self._press_median
        return out

    def _press_level(self, ts: int, cur: float) -> int:
        if (
            self._press_median_at is None
            or ts - self._press_median_at >= th.PRESS_MEDIAN_REFRESH_S
        ):
            self._press_median = float(np.median([v for _, v in self.press]))
            self._press_median_at = ts
        if cur < self._press_median * (1 - th.PRESS_MEDIAN_CRITICAL):
            return Level.CRITICAL
        recent_max = cur
        for t, v in reversed(self.press):
            if t < ts - th.PRESS_DROP_WINDOW_S:
                break
            recent_max = max(recent_max, v)
        if recent_max > 0 and (recent_max - cur) / recent_max > th.PRESS_DROP_ALERT:
            return Level.ALERT
        return 0


class Hysteresis:
    def __init__(self, level: int = 0) -> None:
        self.level = level
        self.below = 0

    def update(self, raw: int) -> int:
        if raw > self.level:
            self.level, self.below = raw, 0
        elif raw < self.level:
            self.below += 1
            if self.below >= th.LEVEL_DOWN_MIN:
                self.level -= 1
                self.below = 0
        else:
            self.below = 0
        return self.level
