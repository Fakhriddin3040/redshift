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
        # last minute that (re)starts the cooldown
        self.last_active_ts: int | None = None
        self.active_run = 0  # consecutive minutes at or above ACTIVE_ACT_MG
        self.low_act_run = 0  # quiet-minute score for sleep, see classify()
        self._last_ts: int | None = None

    def classify(self, m: Minute, rest_hr_median: float | None = None) -> Ctx:
        contiguous = self._last_ts is not None and m.ts - self._last_ts == 60
        self._last_ts = m.ts
        if not contiguous:
            self.low_act_run = 0
            self.active_run = 0

        moving = m.act_mg is not None and m.act_mg >= th.ACTIVE_ACT_MG
        self.active_run = self.active_run + 1 if moving else 0

        # Quiet-minute score: +1 for a quiet minute (up to SLEEP_RUN_MIN), a restless
        # minute costs SLEEP_NOISE_PENALTY, real movement or no data resets it.
        # A strict "15 in a row" loses most real sleep: one twitch restarts the count.
        if m.act_mg is None or moving:
            self.low_act_run = 0
        elif m.act_mg <= th.SLEEP_ACT_MG:
            self.low_act_run = min(self.low_act_run + 1, th.SLEEP_RUN_MIN)
        else:
            self.low_act_run = max(0, self.low_act_run - th.SLEEP_NOISE_PENALTY)

        if m.worn_frac < th.OFF_WORN_FRAC or (m.sqi or 0) < th.OFF_SQI:
            self.low_act_run = 0
            self.active_run = 0
            return Ctx.OFF

        if m.exercise or moving:
            # One busy minute is not exercise: the cooldown starts only after
            # sustained movement or an explicit exercise flag.
            if m.exercise or self.active_run >= th.ACTIVE_COOLDOWN_MIN_RUN:
                self.last_active_ts = m.ts
            return Ctx.ACTIVE
        if (
            self.last_active_ts is not None
            and m.ts - self.last_active_ts <= th.ACTIVE_COOLDOWN_S
        ):
            return Ctx.ACTIVE

        if self.low_act_run >= th.SLEEP_RUN_MIN:
            # Without a learned resting HR there is nothing to compare with,
            # so motion alone decides.
            if (
                m.hr is None
                or rest_hr_median is None
                or m.hr <= rest_hr_median + th.SLEEP_HR_MARGIN
            ):
                return Ctx.SLEEP
        return Ctx.REST
