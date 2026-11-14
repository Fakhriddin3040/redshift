from enum import IntEnum

from vigil.core import thresholds as th
from vigil.core.minute import Minute


class Ctx(IntEnum):
    OFF = 0
    SLEEP = 1
    REST = 2
    ACTIVE = 3

    @property
    def label(self) -> str:
        return self.name.lower()


class ContextTracker:
    def __init__(self) -> None:
        self.last_active_ts: int | None = None
        self.low_act_run = 0
        self._last_ts: int | None = None

    def classify(self, m: Minute, rest_hr_median: float | None = None) -> Ctx:
        contiguous = self._last_ts is not None and m.ts - self._last_ts == 60
        self._last_ts = m.ts

        low = m.act_mg is not None and m.act_mg <= th.SLEEP_ACT_MG
        if not low:
            self.low_act_run = 0
        else:
            self.low_act_run = self.low_act_run + 1 if contiguous else 1

        if m.worn_frac < th.OFF_WORN_FRAC or (m.sqi or 0) < th.OFF_SQI:
            self.low_act_run = 0
            return Ctx.OFF

        if m.exercise or (m.act_mg is not None and m.act_mg >= th.ACTIVE_ACT_MG):
            self.last_active_ts = m.ts
            return Ctx.ACTIVE
        if (
            self.last_active_ts is not None
            and m.ts - self.last_active_ts <= th.ACTIVE_COOLDOWN_S
        ):
            return Ctx.ACTIVE

        if self.low_act_run >= th.SLEEP_RUN_MIN:
            rest = (
                th.SLEEP_DEFAULT_REST_HR if rest_hr_median is None else rest_hr_median
            )
            if m.hr is None or m.hr <= rest + th.SLEEP_HR_MARGIN:
                return Ctx.SLEEP
        return Ctx.REST
