from collections import deque
from dataclasses import dataclass

import numpy as np

from vigil.core import thresholds as th
from vigil.core.context import Ctx

METRICS = ("hr", "spo2", "rr", "skin_t", "hrv")
LEARN_BIT = {m: 1 << i for i, m in enumerate(METRICS)}
BASELINE_CTX = (Ctx.SLEEP, Ctx.REST, Ctx.ACTIVE)


@dataclass(frozen=True, slots=True)
class Norm:
    med: float
    sig: float

    @property
    def lo(self) -> float:
        return self.med - th.BAND_SIGMAS * self.sig

    @property
    def hi(self) -> float:
        return self.med + th.BAND_SIGMAS * self.sig

    def z(self, x: float) -> float:
        return (x - self.med) / self.sig


@dataclass(frozen=True, slots=True)
class Lookup:
    norm: Norm | None
    learning: bool


def tod(ts: int, ctx: Ctx) -> int:
    return 0 if ctx == Ctx.ACTIVE else (ts // 3600 % 24) // th.TOD_HOURS


def robust_norm(metric: str, values: np.ndarray) -> Norm:
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    return Norm(med, max(th.MAD_TO_SIGMA * mad, th.SIGMA_FLOOR[metric]))


def is_ready(ts: np.ndarray) -> bool:
    return (
        len(ts) >= th.CELL_READY_VALUES
        and len(np.unique(ts // 86400)) >= th.CELL_READY_DAYS
    )


class Cell:
    __slots__ = ("ts", "values", "dirty", "norm", "ready", "_ts_arr", "_val_arr")

    def __init__(self) -> None:
        self.ts: deque[int] = deque()
        self.values: deque[float] = deque()
        self.dirty = False
        self.norm: Norm | None = None
        self.ready = False
        self._ts_arr = np.empty(0, dtype=np.int64)
        self._val_arr = np.empty(0)

    def add(self, ts: int, value: float) -> None:
        self.ts.append(ts)
        self.values.append(value)
        self.dirty = True

    def needs_recompute(self, now_ts: int) -> bool:
        return self.dirty or (
            bool(self.ts) and self.ts[0] <= now_ts - th.BASELINE_WINDOW_S
        )

    def recompute(self, metric: str, now_ts: int) -> None:
        cutoff = now_ts - th.BASELINE_WINDOW_S
        while self.ts and self.ts[0] <= cutoff:
            self.ts.popleft()
            self.values.popleft()
        self._ts_arr = np.fromiter(self.ts, dtype=np.int64, count=len(self.ts))
        self._val_arr = np.fromiter(self.values, dtype=float, count=len(self.values))
        self.norm = robust_norm(metric, self._val_arr) if len(self._val_arr) else None
        self.ready = is_ready(self._ts_arr)
        self.dirty = False

    @property
    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        return self._ts_arr, self._val_arr


class Baseline:
    """Personal norm of one crew member: cells keyed by (metric, ctx, time-of-day)."""

    def __init__(self) -> None:
        self.cells: dict[tuple[str, Ctx, int], Cell] = {}
        self.pooled: dict[tuple[str, Ctx], tuple[Norm | None, bool, int]] = {}
        self._hour: int | None = None

    def add(self, metric: str, ctx: Ctx, ts: int, value: float) -> None:
        key = (metric, ctx, tod(ts, ctx))
        cell = self.cells.get(key)
        if cell is None:
            cell = self.cells[key] = Cell()
        cell.add(ts, value)

    def maybe_recompute(self, now_ts: int) -> None:
        hour = now_ts // 3600
        if hour != self._hour:
            self.recompute(now_ts)

    def recompute(self, now_ts: int) -> None:
        self._hour = now_ts // 3600
        touched: set[tuple[str, Ctx]] = set()
        for (metric, ctx, _), cell in self.cells.items():
            if cell.needs_recompute(now_ts):
                cell.recompute(metric, now_ts)
                touched.add((metric, ctx))
        for metric, ctx in touched:
            parts = [
                c.arrays
                for (m, cx, _), c in self.cells.items()
                if m == metric and cx == ctx
            ]
            ts = np.concatenate([p[0] for p in parts])
            vals = np.concatenate([p[1] for p in parts])
            norm = robust_norm(metric, vals) if len(vals) else None
            self.pooled[(metric, ctx)] = (norm, is_ready(ts), len(vals))

    def lookup(self, metric: str, ctx: Ctx, ts: int) -> Lookup:
        cell = self.cells.get((metric, ctx, tod(ts, ctx)))
        if cell is not None and cell.ready:
            return Lookup(cell.norm, False)
        norm, ready, _ = self.pooled.get((metric, ctx), (None, False, 0))
        if ready:
            return Lookup(norm, False)
        typical = th.TYPICAL_NORM.get((metric, ctx.label)) or th.TYPICAL_NORM.get(
            (metric, None)
        )
        if typical is None:
            return Lookup(None, True)
        med, sig = typical
        return Lookup(Norm(med, sig * th.TYPICAL_SIGMA_FACTOR), True)

    def rest_hr_median(self) -> float | None:
        norm, _, n = self.pooled.get(("hr", Ctx.REST), (None, False, 0))
        return norm.med if norm is not None and n >= th.REST_HR_MIN_VALUES else None

    def progress(self) -> tuple[int, int]:
        """(ready cells, cells holding at least one value)."""
        nonempty = [c for c in self.cells.values() if c.ts]
        return sum(c.ready for c in nonempty), len(nonempty)
