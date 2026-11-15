"""C8: detection latency per scenario x severity (docs/DATA_PLAN.md §9).
Writes ml/out/scenarios.json.

    python -m ml.eval_scenarios

For every scenario: 10 normal days to learn the norm, then the scenario starts at
a resting moment. Reports the closed minute at which each level is first reached,
the pattern name and the primary metric. Minute values, no network.
"""

import json
import random
import sys

from ml.paths import OUT
from vigil.core.frame import Flag
from vigil.core.minute import Minute
from vigil.core.pipeline import CrewState
from vigil.vdev.signal import PROFILES, SCENARIOS, Cabin, CrewSim, make_scenario

START_MIN = 1_794_700_800 // 60  # 2026-11-15 00:00 UTC
LEARN_DAYS = 10
SCENARIO_AT_MIN = 12 * 60  # 12:00 UTC: everyone is awake and at rest
WATCH_MIN = 150


def to_minute(ts: int, s, cabin) -> Minute:
    worn = bool(s.flags & Flag.WORN)
    good = s.sqi >= 50
    co2, press, amb = cabin
    return Minute(
        ts=ts,
        hr=s.hr if good else None,
        spo2=s.spo2 if good else None,
        rr=s.rr if good else None,
        skin_t=s.skin_t if good else None,
        hrv=s.hrv if good else None,
        co2_ppm=co2,
        press_hpa=press,
        amb_t=amb,
        act_mg=s.act_mg,
        sqi=float(s.sqi),
        worn_frac=1.0 if worn else 0.0,
        valid_s=60 if good and worn else 0,
        exercise=bool(s.flags & Flag.EXERCISE),
    )


def run(name: str, severity: int, profile, seed: int) -> dict:
    sim, cabin, state = CrewSim(profile, seed), Cabin(seed), CrewState()
    t_scn = START_MIN + LEARN_DAYS * 1440 + SCENARIO_AT_MIN
    for minute in range(START_MIN, t_scn):
        state.on_minute(
            to_minute(minute * 60, sim.minute_sample(minute), cabin.sample(minute * 60))
        )
    assert state.level == 0, "not quiet before the scenario"

    scn = [make_scenario(name, profile.crew, t_scn * 60, random.Random(seed), severity)]
    first: dict[int, int] = {}
    pattern = primary = None
    peak = 0
    off_minutes = 0
    for k in range(WATCH_MIN):
        minute = t_scn + k
        res = state.on_minute(
            to_minute(
                minute * 60,
                sim.minute_sample(minute, scn),
                cabin.sample(minute * 60 + 30, scn),
            )
        )
        off_minutes += res.ctx.label == "off"
        if res.level > peak:
            peak = res.level
            first[res.level] = k + 1
            pattern, primary = res.incident.pattern, res.incident.primary
    back = None
    if peak:
        for k in range(WATCH_MIN, WATCH_MIN + 240):
            minute = t_scn + k
            res = state.on_minute(
                to_minute(
                    minute * 60,
                    sim.minute_sample(minute, scn),
                    cabin.sample(minute * 60, scn),
                )
            )
            if res.level == 0:
                back = k + 1
                break
    return {
        "scenario": name,
        "severity": severity,
        "crew": profile.crew,
        "peak_level": peak,
        "first_minute_at_level": first,
        "pattern": pattern,
        "primary": primary,
        "duration_min": scn[0].duration_s // 60,
        "back_to_usual_min": back,
        "off_minutes": off_minutes,
    }


def span(runs: list[dict], level: int) -> str:
    vals = [r["first_minute_at_level"].get(level) for r in runs]
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    return f"{min(vals)}" if min(vals) == max(vals) else f"{min(vals)}-{max(vals)}"


def main() -> int:
    rows = []
    print(
        f"{'scenario':<18}{'sev':>4}{'peak':>5}  {'Watch/Alert/Critical at closed minute (range over 7 crew)':<58} pattern"
    )
    for name in SCENARIOS:
        for severity in (1, 2, 3):
            runs = [run(name, severity, p, seed=1) for p in PROFILES]
            rows += runs

            peaks = sorted({r["peak_level"] for r in runs})
            patterns = sorted({str(r["pattern"]) for r in runs})
            print(
                f"{name:<18}{severity:>4}{'/'.join(map(str, peaks)):>5}  "
                f"{span(runs, 1) + ' / ' + span(runs, 2) + ' / ' + span(runs, 3):<58} {', '.join(patterns)}"
            )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scenarios.json").write_text(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
