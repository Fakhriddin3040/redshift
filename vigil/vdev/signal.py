"""Signal generator of the virtual device. No network, no clock of its own.

The backend learns a personal norm from minute values, so every signal is built as
    slow part (one value per minute)  +  per-second jitter with zero median.
History frames carry the slow part plus the noise a minute median would have;
live frames carry slow part + jitter. Both give the same minute statistics.

The same classes are driven by `vigil.vdev.app` (live stream) and by offline
scripts (`ml/eval_false_alarms.py`), so what is measured offline is what is shown.
"""

import csv
import math
import random
from dataclasses import dataclass, field
from importlib.resources import files

from vigil.core import thresholds as th
from vigil.core.frame import Flag, Frame, FrameType

DAY_MIN = 1440
SLEEP_MIN = 8 * 60
# The context rule calls a minute "sleep" from the 15th quiet minute on. Heart rate
# must step down in that same minute and step back up in the minute motion returns
# (docs/TASKS.md §2.5, traps A-D).
SLEEP_HR_DELAY_MIN = th.SLEEP_RUN_MIN - 1

EXERCISE_BLOCK_S = 30 * 60
EXERCISE_RISE_S = 60.0
EXERCISE_DECAY_S = 150.0
EXERCISE_FLAG_UNTIL = 3.0  # keep the flag until heart rate is back within rest + 3

# AR(1) per-second jitter fitted on BIDMC (C4, ml/out/ar1.json).
SPO2_PHI, SPO2_SIGMA = 0.92, 0.21
RR_PHI, RR_SIGMA = 0.96, 0.32
RR_PER_BPM = 0.08  # breathing follows heart rate [param]
# Std of the median of 60 such seconds: what a history minute must carry instead.
SPO2_MINUTE_STD, RR_MINUTE_STD, HR_MINUTE_STD = 0.30, 0.90, 0.15

# Normal output is clamped so a hard limit can never fire without a scenario.
HR_CLAMP = (44.0, 108.0)
RR_CLAMP = (9.5, 20.4)
SPO2_BELOW_MEAN = 1.8

PRESS_HPA, PRESS_NOISE = 1013.0, 0.3
AMB_T, AMB_NOISE = 22.5, 0.2

CABIN_SCENARIOS = ("hypercapnia", "depressurization")
SCENARIOS = (
    "hypoxia",
    "exercise",
    "sensor_off",
    "tachycardia_rest",
    "hypercapnia",
    "depressurization",
    "bradycardia",
    "fever_like",
    "motion_artifact",
)


@dataclass(frozen=True, slots=True)
class Profile:
    crew: int
    rest_hr: float
    sleep_hr: float
    spo2: float
    rr: float
    skin_t: float
    hrv: float
    exercise_peak_hr: float
    sleep_start: int  # minute of the UTC day
    exercise_starts: tuple[int, int]  # minutes of the UTC day
    history_days: int = 14


# [param] Seven people, chosen to stay clear of the hard limits (TASKS §2.5).
PROFILES = (
    Profile(1, 62, 53, 97.5, 14, 33.4, 46, 138, 21 * 60 + 30, (6 * 60 + 40, 18 * 60)),
    Profile(2, 58, 49, 97.0, 13, 33.0, 55, 134, 22 * 60, (7 * 60, 18 * 60 + 40)),
    Profile(3, 66, 57, 98.0, 15, 34.1, 38, 142, 21 * 60 + 45, (7 * 60 + 30, 19 * 60)),
    Profile(4, 56, 47, 96.8, 12, 32.7, 58, 132, 22 * 60 + 15, (8 * 60, 19 * 60 + 20)),
    Profile(5, 68, 58, 97.8, 16, 34.4, 33, 145, 21 * 60 + 15, (6 * 60 + 20, 17 * 60 + 40)),
    Profile(6, 60, 51, 96.5, 13, 33.7, 50, 136, 22 * 60 + 30, (8 * 60 + 20, 19 * 60 + 40)),
    Profile(7, 64, 55, 97.2, 15, 32.9, 42, 140, 21 * 60, (6 * 60, 17 * 60 + 20), 3),
)  # fmt: skip


@dataclass(slots=True)
class Scenario:
    name: str
    crew: int | None  # None = whole cabin
    t0: int
    severity: int
    duration_s: int
    params: dict[str, float] = field(default_factory=dict)

    @property
    def end(self) -> int:
        return self.t0 + self.duration_s


def make_scenario(
    name: str,
    crew: int,
    t0: int,
    rng: random.Random,
    severity: int | None = None,
    duration_s: int | None = None,
) -> Scenario:
    """Parameters are drawn at random on each run, except the hypoxia stages,
    which have to hit their thresholds (TASKS §2.7)."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}")
    severity = min(3, max(1, severity or (3 if name == "hypoxia" else 2)))
    u = rng.uniform
    defaults: dict[str, tuple[int, dict[str, float]]] = {
        # stage 1 (7 min) -> stage 2 (4 min) -> stage 3; severity cuts the later stages
        "hypoxia": ({1: 7, 2: 11, 3: 17}[severity] * 60, {"rr": u(2.0, 4.0)}),
        "exercise": (5 * 60, {"act": u(130, 180)}),
        "sensor_off": (3 * 60, {}),
        "tachycardia_rest": (
            8 * 60,
            {"dhr": {1: u(22, 28), 2: u(38, 44), 3: u(75, 85)}[severity]},
        ),
        "hypercapnia": (70 * 60, {"ppco2": {1: 4.2, 2: u(5.8, 6.4), 3: 11.5}[severity]}),
        "depressurization": (20 * 60, {"drop": {1: 0.05, 2: 0.08, 3: u(0.115, 0.125)}[severity]}),
        "bradycardia": (10 * 60, {"hr": {1: 47.0, 2: u(42.5, 44.5), 3: u(37.0, 39.0)}[severity]}),
        "fever_like": (25 * 60, {"dt": {1: 1.2, 2: u(1.7, 2.1), 3: u(2.4, 2.8)}[severity]}),
        "motion_artifact": (3 * 60, {}),
    }  # fmt: skip
    default_duration, params = defaults[name]
    crew_or_cabin = None if name in CABIN_SCENARIOS else crew
    return Scenario(
        name, crew_or_cabin, t0, severity, duration_s or default_duration, params
    )


def _ar(prev: float, phi: float, sigma: float, rng: random.Random) -> float:
    return phi * prev + rng.gauss(0.0, sigma)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def exercise_elevation(elapsed_s: float, block_s: float, peak: float) -> float:
    """Heart-rate rise above rest: up during the block, exponential recovery after."""
    if elapsed_s < 0:
        return 0.0
    if elapsed_s < block_s:
        return peak * (1.0 - math.exp(-elapsed_s / EXERCISE_RISE_S))
    top = peak * (1.0 - math.exp(-block_s / EXERCISE_RISE_S))
    return top * math.exp(-(elapsed_s - block_s) / EXERCISE_DECAY_S)


@dataclass(slots=True)
class Sample:
    hr: float | None
    spo2: float | None
    rr: float | None
    skin_t: float | None
    hrv: float | None
    act_mg: float
    sqi: int
    flags: int


# Real daytime recordings (held-out PPG-DaLiA subjects, ml/make_segments.py).
REAL_HR_SCALE = 0.6  # hr = rest_crew + scale * (donor hr - donor rest) [param]
REAL_ACT_MIN = 13.0  # keeps a very still desk hour from being read as sleep


def load_real_segments() -> list[list[tuple[float, float]]]:
    """Segments of (hr_rel, act_mg) minutes; empty if the asset is not shipped."""
    asset = files("vigil.vdev").joinpath("assets/dalia_rest_segments.csv")
    if not asset.is_file():
        return []
    segments: dict[str, list[tuple[float, float]]] = {}
    for row in csv.DictReader(asset.read_text().splitlines()):
        segments.setdefault(row["segment"], []).append(
            (float(row["hr_rel"]), float(row["act_mg"]))
        )
    return list(segments.values())


class CrewSim:
    """One crew member. Call `minute_sample` / `second_sample` with increasing time.

    With `real_segments`, awake time outside exercise replays real recordings
    (heart rate and wrist motion); everything else stays generated.
    """

    def __init__(
        self,
        profile: Profile,
        seed: int = 0,
        real_segments: list[list[tuple[float, float]]] | None = None,
    ) -> None:
        self.p = profile
        self.real = real_segments or []
        self._seg: list[tuple[float, float]] = []
        self._seg_i = 0
        self._real_hr, self._real_act = 0.0, 26.0
        self.rng = random.Random(seed * 1000 + profile.crew)
        self._seed = seed * 1000 + profile.crew
        self._minute: int | None = None
        # slow parts (minute level)
        self._hr = self._spo2 = self._rr = self._skin = self._hrv = 0.0
        self._act = 26.0
        # per-second jitter state
        self._j_spo2 = self._j_rr = 0.0

    # ---- schedule (pure functions of time) ----

    def _sleep_minute(self, minute: int) -> int | None:
        """Minutes since lights-out, or None when awake. Bedtime and length differ
        from night to night, the same way for history and live (a pure function)."""
        night = (minute - self.p.sleep_start + 60) // DAY_MIN
        g = random.Random(self._seed * 100_003 + night)
        start = night * DAY_MIN + self.p.sleep_start + g.randint(-25, 25)
        length = SLEEP_MIN + g.randint(-50, 20)
        since = minute - start
        return since if 0 <= since < length else None

    def _scheduled_exercise(self, vt: float) -> tuple[float, bool]:
        """(heart-rate elevation, moving) from the two daily exercise blocks."""
        peak = self.p.exercise_peak_hr - self.p.rest_hr
        sec_of_day = vt % 86400
        best, moving = 0.0, False
        for start_min in self.p.exercise_starts:
            elapsed = (sec_of_day - start_min * 60) % 86400
            if elapsed < EXERCISE_BLOCK_S + 3600:
                best = max(best, exercise_elevation(elapsed, EXERCISE_BLOCK_S, peak))
                moving = moving or elapsed < EXERCISE_BLOCK_S
        return best, moving

    # ---- slow part ----

    def _advance(self, minute: int) -> None:
        if self._minute == minute:
            return
        steps = 1 if self._minute is None else min(max(minute - self._minute, 1), 30)
        self._minute = minute
        g = self.rng
        for _ in range(steps):
            self._hr = _ar(self._hr, 0.9, 0.55, g)
            self._spo2 = _ar(self._spo2, 0.9, 0.05, g)
            self._rr = _ar(self._rr, 0.9, 0.15, g)
            self._skin = _ar(self._skin, 0.98, 0.02, g)
            self._hrv = _ar(self._hrv, 0.9, 1.3, g)
            self._act = _clamp(26.0 + 0.7 * (self._act - 26.0) + g.gauss(0, 5), 15, 45)
            if self.real:
                if self._seg_i >= len(self._seg):
                    self._seg, self._seg_i = g.choice(self.real), 0
                self._real_hr, self._real_act = self._seg[self._seg_i]
                self._seg_i += 1

    def _values(
        self, vt: float, scenarios: list[Scenario]
    ) -> tuple[dict[str, float | None], float, int, int, bool]:
        """Slow values at time vt -> (vitals, act_mg, sqi, flags, asleep)."""
        p, g = self.p, self.rng
        minute = int(vt // 60)
        self._advance(minute)

        sleep_min = self._sleep_minute(minute)
        in_bed = sleep_min is not None
        asleep = in_bed and sleep_min >= SLEEP_HR_DELAY_MIN
        circadian = 1.0 * math.sin(2 * math.pi * (minute % DAY_MIN) / DAY_MIN)

        elev, moving = (0.0, False) if in_bed else self._scheduled_exercise(vt)
        act = float(g.randint(1, 5)) if in_bed else self._act
        flags = int(Flag.WORN)
        sqi = g.randint(85, 100)

        hr_base = p.sleep_hr if asleep else p.rest_hr + circadian
        hr = hr_base + self._hr
        if self.real and not in_bed:
            hr = hr_base + REAL_HR_SCALE * self._real_hr
            act = max(REAL_ACT_MIN, self._real_act)
        spo2 = p.spo2 + self._spo2
        rr = p.rr - (1.0 if asleep else 0.0) + self._rr
        skin = p.skin_t + self._skin
        hrv = p.hrv + (8.0 if asleep else 0.0) + self._hrv
        clamp_hr = True

        mine = [
            s
            for s in scenarios
            if s.crew in (None, p.crew) and s.t0 <= vt < s.end + 3600
        ]
        for s in mine:  # fmt: skip
            t = vt - s.t0
            on = t < s.duration_s
            if s.name == "exercise":
                e = exercise_elevation(t, s.duration_s, p.exercise_peak_hr - p.rest_hr)
                elev = max(elev, e)
                moving = moving or on
                if on:
                    act = s.params["act"]
            elif not on:
                continue
            elif s.name == "hypoxia":
                # Staged relative to the person's own mean, so each level is shown.
                target = p.spo2 - 2.5 if t < 420 else 93.0 if t < 660 else 88.0
                spo2 = target
                hr += p.spo2 - target
                rr = min(rr + s.params["rr"], 20.0)
            elif s.name == "tachycardia_rest":
                hr += s.params["dhr"] * min(1.0, t / 20.0)
                clamp_hr = False
            elif s.name == "bradycardia":
                hr = s.params["hr"] + 0.3 * self._hr
                clamp_hr = False
            elif s.name == "fever_like":
                rise = s.params["dt"] * min(1.0, t / 300.0)
                skin += rise
                hr += 2.5 * rise
            elif s.name == "motion_artifact":
                flags |= Flag.MOTION_ARTIFACT
                sqi = g.randint(22, 40)
                act = float(g.randint(45, 75))
            elif s.name == "sensor_off":
                flags &= ~Flag.WORN
                sqi = 0

        if elev > EXERCISE_FLAG_UNTIL or moving:
            flags |= Flag.EXERCISE
            hr += elev
            hrv = max(8.0, hrv - 0.45 * elev)
            if moving and act < 100:
                act = float(g.randint(120, 200))
        elif clamp_hr:
            hr = _clamp(hr, *HR_CLAMP)
        rr += RR_PER_BPM * max(0.0, hr - hr_base - self._hr)

        vitals: dict[str, float | None] = {
            "hr": hr, "spo2": spo2, "rr": rr, "skin_t": skin, "hrv": max(5.0, hrv),
        }  # fmt: skip
        if not flags & Flag.WORN:
            vitals = dict.fromkeys(vitals)
        return vitals, act, sqi, flags, bool(flags & Flag.EXERCISE)

    def _finish(self, v: dict[str, float | None], exercising: bool) -> None:
        if v["spo2"] is not None:
            v["spo2"] = min(100.0, v["spo2"])
        if v["rr"] is not None and not exercising:
            v["rr"] = _clamp(v["rr"], *RR_CLAMP)

    # ---- outputs ----

    def minute_sample(self, minute: int, scenarios: list[Scenario] = ()) -> Sample:
        """One history minute: slow part + the noise a 60-second median would have."""
        g = self.rng
        v, act, sqi, flags, exercising = self._values(minute * 60 + 30, list(scenarios))
        if v["hr"] is not None:
            v["hr"] += g.gauss(0, HR_MINUTE_STD)
            if v["spo2"] >= self.p.spo2 - 2.0:  # not a staged scenario value
                v["spo2"] = max(
                    v["spo2"] + g.gauss(0, SPO2_MINUTE_STD),
                    self.p.spo2 - SPO2_BELOW_MEAN,
                )
            v["rr"] += g.gauss(0, RR_MINUTE_STD)
        self._finish(v, exercising)
        return Sample(act_mg=act, sqi=sqi, flags=flags, **v)

    def second_sample(self, vt: int, scenarios: list[Scenario] = ()) -> Sample:
        """One live second: slow part + jitter."""
        g = self.rng
        v, act, sqi, flags, exercising = self._values(vt, list(scenarios))
        self._j_spo2 = _ar(self._j_spo2, SPO2_PHI, SPO2_SIGMA, g)
        self._j_rr = _ar(self._j_rr, RR_PHI, RR_SIGMA, g)
        if v["hr"] is not None:
            in_scenario = v["spo2"] < self.p.spo2 - 2.0
            v["hr"] += g.gauss(0, 1.0)
            # A staged SpO2 value must keep its rounded minute median: small jitter only.
            v["spo2"] += 0.25 * self._j_spo2 if in_scenario else self._j_spo2
            if not in_scenario:
                v["spo2"] = max(v["spo2"], self.p.spo2 - SPO2_BELOW_MEAN)
            v["rr"] += self._j_rr
            v["skin_t"] += g.gauss(0, 0.02)
        self._finish(v, exercising)
        act = max(0.0, act + g.gauss(0, 1.0 if act < 10 else 4.0))
        return Sample(act_mg=act, sqi=sqi, flags=flags, **v)


class Cabin:
    """One cabin for everyone: real ISS CO2 (NASA OSDR EDA, RR-12), looped."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed * 1000 + 999)
        text = files("vigil.vdev").joinpath("assets/co2_iss_rr12.csv").read_text()
        self.co2: list[float | None] = [
            float(row["co2_ppm"]) if row["co2_ppm"] else None
            for row in csv.DictReader(text.splitlines())
        ]

    def sample(
        self, vt: float, scenarios: list[Scenario] = ()
    ) -> tuple[float | None, float, float]:
        """(co2_ppm, press_hpa, amb_t) at time vt."""
        g = self.rng
        co2 = self.co2[int(vt // 60) % len(self.co2)]
        press = PRESS_HPA + _clamp(g.gauss(0, 0.1), -PRESS_NOISE, PRESS_NOISE)
        amb = AMB_T + _clamp(g.gauss(0, 0.07), -AMB_NOISE, AMB_NOISE)
        for s in scenarios:
            t = vt - s.t0
            if not 0 <= t < s.duration_s:
                continue
            if s.name == "hypercapnia" and co2 is not None:
                target_ppm = s.params["ppco2"] / (
                    1e-6 * th.STD_PRESSURE_HPA * th.MMHG_PER_HPA
                )
                co2 = max(co2, target_ppm) + g.gauss(0, 30)
            elif s.name == "depressurization":
                press *= 1.0 - s.params["drop"] * min(1.0, t / 600.0)
        return co2, press, amb


class Fleet:
    """All crew members plus the cabin; builds wire frames."""

    def __init__(self, seed: int = 0, real_day: bool = False) -> None:
        self.seed = seed
        self.real_day = real_day
        segments = load_real_segments() if real_day else []
        self.crew = {p.crew: CrewSim(p, seed, segments) for p in PROFILES}
        self.cabin = Cabin(seed)
        self.scenarios: list[Scenario] = []
        self._seq = dict.fromkeys(self.crew, 0)
        self._scn_rng = random.Random(seed * 1000 + 998)

    def add_scenario(
        self,
        name: str,
        crew: int,
        vt: int,
        severity: int | None = None,
        duration_s: int | None = None,
    ) -> Scenario:
        if crew not in self.crew:
            raise ValueError(f"unknown crew {crew}")
        s = make_scenario(name, crew, vt, self._scn_rng, severity, duration_s)
        self.scenarios = [
            x for x in self.scenarios if (x.name, x.crew) != (s.name, s.crew)
        ]
        self.scenarios.append(s)
        return s

    def prune(self, vt: int) -> None:
        self.scenarios = [s for s in self.scenarios if vt < s.end + 3600]

    def active(self, vt: int) -> list[Scenario]:
        return [s for s in self.scenarios if s.t0 <= vt < s.end]

    def _frame(
        self, ftype: int, crew: int, ts: int, s: Sample, cabin: tuple, history: bool
    ) -> Frame:
        self._seq[crew] = (self._seq[crew] + 1) & 0xFF
        co2, press, amb = cabin
        minute_of_day = ts // 60 % DAY_MIN
        return Frame(
            type=ftype,
            dev_id=crew,
            ts=ts,
            hr=s.hr,
            spo2=s.spo2,
            rr=s.rr,
            skin_t=s.skin_t,
            co2_ppm=co2,
            press_hpa=press,
            act_mg=s.act_mg,
            sqi=s.sqi,
            flags=s.flags | (Flag.HISTORY if history else 0),
            batt=95 - minute_of_day * 40 // DAY_MIN,
            seq=self._seq[crew],
            hrv=s.hrv,
            amb_t=amb,
        )

    def history_frames(self, minute: int, first_minute: dict[int, int]) -> list[Frame]:
        """Type-2 frames of one history minute, for the crew whose history covers it."""
        cabin = self.cabin.sample(minute * 60 + 30)
        return [
            self._frame(
                FrameType.MINUTE, c, minute * 60, sim.minute_sample(minute), cabin, True
            )
            for c, sim in self.crew.items()
            if minute >= first_minute[c]
        ]

    def live_frames(self, vt: int) -> list[Frame]:
        """Type-1 frames of one live second, one per crew member."""
        cabin = self.cabin.sample(vt, self.scenarios)
        return [
            self._frame(
                FrameType.SECOND,
                c,
                vt,
                sim.second_sample(vt, self.scenarios),
                cabin,
                False,
            )
            for c, sim in self.crew.items()
        ]
