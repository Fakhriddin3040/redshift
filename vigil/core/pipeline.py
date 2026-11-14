"""Everything after a minute closes (§5): one synchronous `on_minute` per crew member.

No network or database here: the backend, the startup restore and offline ML
all drive the same `CrewState`.
"""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from vigil.core import thresholds as th
from vigil.core.baseline import LEARN_BIT, METRICS, Baseline, Norm
from vigil.core.context import ContextTracker, Ctx
from vigil.core.levels import (
    EnvEval,
    EnvTracker,
    Hysteresis,
    ZRun,
    directional_z,
    hard_level,
)
from vigil.core.minute import Minute

Z_LEVEL_METRICS = ("hr", "spo2", "rr", "skin_t")
NOT_IN_ACTIVE = ("hr", "rr")
ENV_METRICS = ("ppco2", "press")
SLOPE_METRICS = METRICS + ENV_METRICS
SOURCE_PRIORITY = ("hard", "env", "baseline")


@dataclass(slots=True)
class MetricEval:
    value: float | None = None
    z: float | None = None
    norm: Norm | None = None
    learning: bool = False
    hard: int = 0
    z_level: int = 0
    flagged: bool = False

    @property
    def usual(self) -> tuple[float, float] | None:
        if self.norm is None or self.learning:
            return None
        return self.norm.lo, self.norm.hi


@dataclass(slots=True)
class IncidentMetric:
    m: str
    first_ts: int
    value: float | None = None
    usual: tuple[float, float] | None = None
    z: float | None = None
    slope_per_min: float | None = None
    since_min: int = 0
    trend: str = "stable"


@dataclass(slots=True)
class Incident:
    ts_start: int
    ts_update: int
    level: int
    peak_level: int
    source: str
    ctx: Ctx
    id: int | None = None
    key: str = "incident"
    ts_end: int | None = None
    pattern: str | None = None
    p: float | None = None
    metrics: dict[str, IncidentMetric] = field(default_factory=dict)
    text: dict | None = None
    text_src: str | None = None
    ack_ts: int | None = None

    @property
    def primary(self) -> str | None:
        return next(iter(self.metrics), None)


@dataclass(frozen=True, slots=True)
class BaselineStatus:
    state: str
    days: int
    ready_pct: int


@dataclass(slots=True)
class MinuteResult:
    minute: Minute
    ctx: Ctx
    evals: dict[str, MetricEval]
    env: EnvEval
    raw: int
    level: int
    prev_level: int
    learn_mask: int
    incident: Incident | None
    incident_event: str | None
    level_raised: bool
    became_learned: bool
    new_day: int | None


def slope_per_min(points: Iterable[tuple[int, float]]) -> float | None:
    pts = list(points)
    if len(pts) < 2:
        return None
    n = len(pts)
    mx = sum(t for t, _ in pts) / n
    my = sum(v for _, v in pts) / n
    sxx = sum((t - mx) ** 2 for t, _ in pts)
    if sxx == 0:
        return None
    sxy = sum((t - mx) * (v - my) for t, v in pts)
    return sxy / sxx * 60


def trend(metric: str, slope: float | None) -> str:
    if slope is None or abs(slope) * 10 < th.TREND_STABLE_10MIN[metric]:
        return "stable"
    return "rising" if slope > 0 else "falling"


def rule_pattern(metric: str | None, up: bool, ctx: Ctx) -> str | None:
    """§8.3: pattern from the primary metric while no model is loaded."""
    match metric:
        case "spo2" if not up:
            return "hypoxia"
        case "hr" if up and ctx in (Ctx.REST, Ctx.SLEEP):
            return "tachycardia_rest"
        case "hr" if not up:
            return "bradycardia"
        case "skin_t" if up:
            return "fever_like"
        case "ppco2":
            return "hypercapnia"
        case "press":
            return "depressurization"
    return None


class CrewState:
    def __init__(self) -> None:
        self.baseline = Baseline()
        self.context = ContextTracker()
        self.zruns = {m: ZRun() for m in Z_LEVEL_METRICS}
        self.env = EnvTracker()
        self.hysteresis = Hysteresis()
        self.incident: Incident | None = None
        self._closed: Incident | None = None
        self.recent: dict[str, deque[tuple[int, float]]] = {
            m: deque() for m in SLOPE_METRICS
        }
        self.days: set[int] = set()
        self.learned = False
        self.last_ts: int | None = None
        self.last: MinuteResult | None = None

    @property
    def level(self) -> int:
        return self.hysteresis.level

    def baseline_status(self) -> BaselineStatus:
        ready, nonempty = self.baseline.progress()
        pct = round(100 * ready / nonempty) if nonempty else 0
        days = len(self.days)
        learned = days >= th.LEARNED_DAYS and pct >= th.LEARNED_READY_PCT
        return BaselineStatus(
            "learned" if learned else "learning", min(days, th.LEARNED_DAYS), pct
        )

    def restore(
        self,
        minutes: Iterable[tuple[Minute, Ctx, int]],
        incident: Incident | None = None,
    ) -> None:
        """Refill norms from stored minutes (by learn_mask) and pick up an open incident."""
        for m, ctx, mask in minutes:
            for metric in METRICS:
                value = m.get(metric)
                if mask & LEARN_BIT[metric] and value is not None:
                    self.baseline.add(metric, ctx, m.ts, value)
            self.env.push(m.ts, m.ppco2, m.press_hpa)
            self.days.add(m.ts // 86400)
            self.last_ts = m.ts
        if self.last_ts is not None:
            self.baseline.recompute(self.last_ts)
            self._prune_days(self.last_ts)
        self.learned = self.baseline_status().state == "learned"
        if incident is not None:
            self.incident = incident
            self.hysteresis = Hysteresis(incident.level)

    def on_minute(self, m: Minute) -> MinuteResult:
        prev_day = None if self.last_ts is None else self.last_ts // 86400
        self.last_ts = m.ts
        self.baseline.maybe_recompute(m.ts)
        ctx = self.context.classify(m, self.baseline.rest_hr_median())
        self._push_recent(m)

        hard_ok = m.summary or (m.valid_s or 0) >= th.HARD_MIN_VALID_SECONDS
        evals = {metric: self._evaluate(metric, m, ctx, hard_ok) for metric in METRICS}
        env = self.env.update(m)

        contributions = {
            "hard": max(e.hard for e in evals.values()),
            "env": max(env.ppco2_level, env.press_level),
            "baseline": max(e.z_level for e in evals.values()),
        }
        raw = max(contributions.values())
        source = next(s for s in SOURCE_PRIORITY if contributions[s] == raw)

        prev_level = self.level
        level = self.hysteresis.update(raw)
        event, raised = self._track_incident(
            m, ctx, evals, env, level, prev_level, source
        )
        incident = self.incident if event != "closed" else self._closed
        mask = self._learn(m, ctx, evals)

        self.days.add(m.ts // 86400)
        self._prune_days(m.ts)
        learned = self.baseline_status().state == "learned"
        became_learned = learned and not self.learned
        self.learned = learned

        day = m.ts // 86400
        self.last = MinuteResult(
            minute=m,
            ctx=ctx,
            evals=evals,
            env=env,
            raw=raw,
            level=level,
            prev_level=prev_level,
            learn_mask=mask,
            incident=incident,
            incident_event=event,
            level_raised=raised,
            became_learned=became_learned,
            new_day=day if prev_day is not None and day != prev_day else None,
        )
        return self.last

    def _evaluate(self, metric: str, m: Minute, ctx: Ctx, hard_ok: bool) -> MetricEval:
        ev = MetricEval(value=m.get(metric))
        if ctx == Ctx.OFF:
            return ev
        lookup = self.baseline.lookup(metric, ctx, m.ts)
        ev.norm, ev.learning = lookup.norm, lookup.learning
        if ev.value is not None and ev.norm is not None:
            ev.z = ev.norm.z(ev.value)
        if hard_ok:
            ev.hard = hard_level(metric, ev.value, ctx)

        scored = (
            metric in self.zruns
            and ev.z is not None
            and not ev.learning
            and not (ctx == Ctx.ACTIVE and metric in NOT_IN_ACTIVE)
        )
        dz = directional_z(metric, ev.z) if scored else None
        if metric in self.zruns:
            ev.z_level = self.zruns[metric].update(m.ts, dz)
        ev.flagged = ev.hard > 0 or (dz is not None and dz >= th.WATCH_Z)
        return ev

    def _track_incident(
        self,
        m: Minute,
        ctx: Ctx,
        evals: dict[str, MetricEval],
        env: EnvEval,
        level: int,
        prev_level: int,
        source: str,
    ) -> tuple[str | None, bool]:
        inc = self.incident
        raised = False
        if level > 0:
            if inc is None:
                inc = self.incident = Incident(
                    ts_start=m.ts,
                    ts_update=m.ts,
                    level=level,
                    peak_level=level,
                    source=source,
                    ctx=ctx,
                )
                event = "created"
                raised = True
            else:
                event = "updated"
                if level > inc.level:
                    inc.ack_ts = None
                    inc.source = source
                    raised = True
                inc.level = level
                inc.peak_level = max(inc.peak_level, level)
                inc.ts_update = m.ts
                inc.ctx = ctx
            self._refresh_incident(inc, m, ctx, evals, env)
            return event, raised
        if inc is not None:
            inc.level = 0
            inc.ts_end = inc.ts_update = m.ts
            self._closed = inc
            self.incident = None
            return "closed", False
        return None, False

    def _refresh_incident(
        self,
        inc: Incident,
        m: Minute,
        ctx: Ctx,
        evals: dict[str, MetricEval],
        env: EnvEval,
    ) -> None:
        flagged = {k: e for k, e in evals.items() if e.flagged}
        env_flagged = {"ppco2": env.ppco2_level, "press": env.press_level}
        env_flagged = {k: lv for k, lv in env_flagged.items() if lv > 0}
        for metric in [*flagged, *env_flagged]:
            if metric not in inc.metrics:
                inc.metrics[metric] = IncidentMetric(m=metric, first_ts=m.ts)

        for metric, im in inc.metrics.items():
            if metric in evals:
                ev = evals[metric]
                im.value, im.z, im.usual = ev.value, ev.z, ev.usual
            elif metric == "ppco2":
                im.value = env.ppco2_mean
            else:
                im.value = env.press
            im.slope_per_min = slope_per_min(self.recent[metric])
            im.trend = trend(metric, im.slope_per_min)
            im.since_min = (m.ts - im.first_ts) // 60

        primary = self._pick_primary(flagged, env_flagged) or inc.primary
        if primary is not None:
            inc.metrics = {primary: inc.metrics[primary]} | {
                k: v for k, v in inc.metrics.items() if k != primary
            }
            z = evals[primary].z if primary in evals else None
            inc.pattern = rule_pattern(primary, z is None or z > 0, ctx)

    @staticmethod
    def _pick_primary(
        flagged: dict[str, MetricEval], env_flagged: dict[str, int]
    ) -> str | None:
        def dz(item: tuple[str, MetricEval]) -> float:
            metric, ev = item
            return 0.0 if ev.z is None else directional_z(metric, ev.z)

        hard = [(k, e) for k, e in flagged.items() if e.hard > 0]
        if hard:
            return max(hard, key=lambda it: (it[1].hard, dz(it)))[0]
        if env_flagged:
            return max(env_flagged.items(), key=lambda it: it[1])[0]
        if flagged:
            return max(flagged.items(), key=dz)[0]
        return None

    def _learn(self, m: Minute, ctx: Ctx, evals: dict[str, MetricEval]) -> int:
        if ctx == Ctx.OFF:
            return 0
        mask = 0
        for metric, ev in evals.items():
            if ev.value is None:
                continue
            if ev.learning or (
                ev.z is not None
                and abs(ev.z) < th.LEARN_MAX_Z
                and self.incident is None
            ):
                self.baseline.add(metric, ctx, m.ts, ev.value)
                mask |= LEARN_BIT[metric]
        return mask

    def _push_recent(self, m: Minute) -> None:
        for metric, dq in self.recent.items():
            value = m.get(metric)
            if value is not None:
                dq.append((m.ts, value))
            while dq and dq[0][0] <= m.ts - th.SLOPE_WINDOW_S:
                dq.popleft()

    def _prune_days(self, now_ts: int) -> None:
        oldest = (now_ts - th.BASELINE_WINDOW_S) // 86400
        self.days = {d for d in self.days if d > oldest}
