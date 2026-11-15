"""T2 / C7: false alarms on normal data (docs/TASKS.md §3). Writes ml/out/false_alarms.json.

    python -m ml.eval_false_alarms            # 21 days as history + 2 days as live seconds
    python -m ml.eval_false_alarms --seeds 5  # repeat with several generator seeds
    python -m ml.eval_false_alarms --real-day # awake time replays real PPG-DaLiA segments

Drives the vdev generator straight into vigil.core.pipeline.CrewState: no backend,
no network. Frames go through pack/unpack, so the values are quantized as on the wire.
Run it again after every change to the generator, the profiles or thresholds.py.
Target: zero Alert and zero Critical; at most one Watch per person-day.
"""

import json
import sys
from collections import Counter

from ml.paths import OUT
from vigil.core.frame import pack, unpack
from vigil.core.minute import MinuteAggregator, from_minute_frame
from vigil.core.pipeline import CrewState
from vigil.vdev.signal import PROFILES, Fleet

HISTORY_DAYS = 21
LIVE_DAYS = 2
COUNT_AFTER_DAY = 8  # the baseline needs a week; incidents are counted after this
START_MIN = 1_794_700_800 // 60  # 2026-11-15 00:00 UTC, any fixed day boundary


def run(seed: int, real_day: bool = False) -> dict:
    fleet = Fleet(seed, real_day)
    states = {p.crew: CrewState() for p in PROFILES}
    first = {p.crew: START_MIN for p in PROFILES}
    incidents: dict[int, list[dict]] = {p.crew: [] for p in PROFILES}
    ctx_minutes: dict[int, Counter] = {p.crew: Counter() for p in PROFILES}

    def feed(crew: int, minute, day: int) -> None:
        res = states[crew].on_minute(minute)
        ctx_minutes[crew][res.ctx.label] += 1
        if res.incident_event == "created" and day >= COUNT_AFTER_DAY:
            incidents[crew].append({"day": day, "inc": res.incident})

    end_history = START_MIN + HISTORY_DAYS * 1440
    for minute in range(START_MIN, end_history):
        day = (minute - START_MIN) // 1440
        for f in fleet.history_frames(minute, first):
            feed(f.dev_id, from_minute_frame(unpack(pack(f))), day)

    aggs = {p.crew: MinuteAggregator() for p in PROFILES}
    for vt in range(end_history * 60, (end_history + LIVE_DAYS * 1440) * 60):
        day = (vt // 60 - START_MIN) // 1440
        for f in fleet.live_frames(vt):
            closed = aggs[f.dev_id].add(f if vt % 60 else unpack(pack(f)))
            if closed is not None:
                feed(f.dev_id, closed, day)

    days = HISTORY_DAYS + LIVE_DAYS - COUNT_AFTER_DAY
    per_crew = {}
    for crew, items in incidents.items():
        status = states[crew].baseline_status()
        per_crew[crew] = {
            "incidents": len(items),
            "per_person_day": round(len(items) / days, 3),
            "by_peak_level": dict(Counter(i["inc"].peak_level for i in items)),
            "by_pattern": dict(Counter(str(i["inc"].pattern) for i in items)),
            "live_part": sum(i["day"] >= HISTORY_DAYS for i in items),
            "baseline": status.state,
            "ctx_share": {
                k: round(v / sum(ctx_minutes[crew].values()), 3)
                for k, v in sorted(ctx_minutes[crew].items())
            },
            "examples": [
                {
                    "day": i["day"],
                    "level": i["inc"].peak_level,
                    "pattern": i["inc"].pattern,
                    "ctx": i["inc"].ctx.label,
                    "source": i["inc"].source,
                    "metrics": {
                        k: round(m.value, 1) if m.value is not None else None
                        for k, m in i["inc"].metrics.items()
                    },
                }
                for i in items[:5]
            ],
        }
    total = sum(v["incidents"] for v in per_crew.values())
    levels = Counter()
    for v in per_crew.values():
        levels.update(v["by_peak_level"])
    return {
        "seed": seed,
        "counted_days_per_person": days,
        "incidents": total,
        "per_person_day": round(total / (days * len(PROFILES)), 3),
        "watch": levels.get(1, 0),
        "alert": levels.get(2, 0),
        "critical": levels.get(3, 0),
        "per_crew": per_crew,
    }


def main(argv: list[str]) -> int:
    n_seeds = int(argv[argv.index("--seeds") + 1]) if "--seeds" in argv else 1
    real_day = "--real-day" in argv
    runs = [run(seed, real_day) for seed in range(n_seeds)]
    for r in runs:
        print(
            f"seed {r['seed']}: {r['incidents']} incidents in {r['counted_days_per_person']} days x 7 people"
            f" = {r['per_person_day']} per person-day | watch {r['watch']}, alert {r['alert']}, critical {r['critical']}"
        )
        for crew, v in r["per_crew"].items():
            print(
                f"   crew {crew}: {v['incidents']} ({v['by_pattern']}) live {v['live_part']}"
                f" | baseline {v['baseline']} | ctx {v['ctx_share']}"
            )
            for e in v["examples"][:3]:
                print("      ", e)
    ok = all(
        r["alert"] == 0 and r["critical"] == 0 and r["per_person_day"] <= 1
        for r in runs
    )
    result = {
        "history_days": HISTORY_DAYS,
        "live_days": LIVE_DAYS,
        "count_after_day": COUNT_AFTER_DAY,
        "target_met": ok,
        "runs": runs,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (
        OUT / ("false_alarms_real_day.json" if real_day else "false_alarms.json")
    ).write_text(json.dumps(result, indent=2) + "\n")
    print("TARGET MET" if ok else "TARGET NOT MET")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
