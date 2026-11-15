"""40 features of a 10-minute window (PLAN §10). One code path for offline
training (ml/make_windows.py) and the backend.

Vital signs enter as z-scores against the personal norm, so the model does not
depend on who the person is. Missing values are NaN; the trees handle them.
"""

import math
from collections.abc import Sequence

from vigil.core.context import Ctx
from vigil.core.pipeline import MinuteResult, slope_per_min

WINDOW_MIN = 10
MIN_WINDOW_MIN = 5  # fewer minutes than this: no features
Z_METRICS = ("hr", "spo2", "rr", "skin_t")
NAN = float("nan")

FEATURES: tuple[str, ...] = (
    *(
        f"{m}_z_{stat}"
        for m in Z_METRICS
        for stat in ("last", "mean", "min", "max", "slope", "valid")
    ),
    "hrv_z_last",
    "act_mean", "act_max", "act_std",
    "ctx_rest", "ctx_active", "ctx_sleep",
    "ppco2_mean", "ppco2_slope",
    "press_dev", "press_slope",
    "sqi_mean", "sqi_min", "worn_frac",
    "tod_sin", "tod_cos",
)  # fmt: skip
assert len(FEATURES) == 40


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else NAN


def _slope(points: list[tuple[int, float]]) -> float:
    s = slope_per_min(points)
    return NAN if s is None else s


def features(window: Sequence[MinuteResult]) -> list[float] | None:
    """Features of the last WINDOW_MIN results (oldest first), or None if too few."""
    win = list(window)[-WINDOW_MIN:]
    if len(win) < MIN_WINDOW_MIN:
        return None
    last = win[-1]
    out: list[float] = []

    for m in Z_METRICS:
        pts = [(r.minute.ts, r.evals[m].z) for r in win if r.evals[m].z is not None]
        zs = [z for _, z in pts]
        last_z = last.evals[m].z
        out += [
            NAN if last_z is None else last_z,
            _mean(zs),
            min(zs) if zs else NAN,
            max(zs) if zs else NAN,
            _slope(pts),
            len(zs) / len(win),
        ]
    hrv_z = last.evals["hrv"].z
    out.append(NAN if hrv_z is None else hrv_z)

    acts = [r.minute.act_mg for r in win if r.minute.act_mg is not None]
    act_mean = _mean(acts)
    out += [
        act_mean,
        max(acts) if acts else NAN,
        math.sqrt(_mean([(a - act_mean) ** 2 for a in acts])) if acts else NAN,
    ]
    out += [float(last.ctx == c) for c in (Ctx.REST, Ctx.ACTIVE, Ctx.SLEEP)]

    co2 = [(r.minute.ts, r.minute.ppco2) for r in win if r.minute.ppco2 is not None]
    out += [_mean([v for _, v in co2]), _slope(co2)]

    press = [
        (r.minute.ts, r.minute.press_hpa) for r in win if r.minute.press_hpa is not None
    ]
    median = last.env.press_median
    cur = last.minute.press_hpa
    out += [
        NAN if cur is None or not median else (cur - median) / median * 100.0,
        _slope(press),
    ]

    sqis = [r.minute.sqi for r in win if r.minute.sqi is not None]
    out += [
        _mean(sqis),
        min(sqis) if sqis else NAN,
        _mean([r.minute.worn_frac for r in win]),
    ]

    angle = 2 * math.pi * (last.minute.ts % 86400) / 86400
    out += [math.sin(angle), math.cos(angle)]
    return out
