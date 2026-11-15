"""C5: sigma floors (docs/DATA_PLAN.md §9). Writes ml/out/sigma.json.

    python -m ml.calc_sigma

Per train subject x metric x context: sigma = 1.4826 * MAD of the 1-min values
(the same robust sigma as vigil.core.baseline). The floor candidate is the 25th
percentile of that sigma across subjects. Context comes from the dataset labels.
spo2 / rr are not covered: there is no real wearable source for them.
"""

import json
import sys

import numpy as np

from ml.minutes import load_track, manifest, to_minutes
from ml.paths import OUT
from vigil.core import thresholds as th

METRICS = ("hr", "skin_t", "hrv")
MIN_MINUTES = 10  # per subject x ctx, otherwise the MAD is not meaningful


def robust_sigma(values: list[float]) -> float:
    x = np.asarray(values)
    return float(th.MAD_TO_SIGMA * np.median(np.abs(x - np.median(x))))


def main() -> int:
    man = manifest()
    pools = [("dalia", s) for s in man["dalia"]["train"]] + [
        ("sleep", s) for s in man["sleep"]["train"]
    ]
    sigmas: dict[tuple[str, str], dict[str, float]] = {}
    for src, subject in pools:
        minutes = to_minutes(load_track(src, subject))
        for ctx in ("rest", "active", "sleep"):
            # Awake-in-bed minutes of a sleep night are too few and too mixed to be a "rest" norm.
            if src == "sleep" and ctx != "sleep":
                continue
            for metric in METRICS:
                vals = [
                    v
                    for lm in minutes
                    if lm.label == ctx and (v := lm.minute.get(metric)) is not None
                ]
                if len(vals) >= MIN_MINUTES:
                    sigmas.setdefault((metric, ctx), {})[f"{src}:{subject}"] = round(
                        robust_sigma(vals), 3
                    )

    result: dict = {
        "current_floor": {m: th.SIGMA_FLOOR[m] for m in METRICS},
        "min_minutes_per_cell": MIN_MINUTES,
        "cells": {},
    }
    print(
        f"{'metric':>7} {'ctx':>6} {'n':>3} {'p25':>6} {'p50':>6} {'p75':>6}   current floor"
    )
    for (metric, ctx), per_subj in sorted(sigmas.items()):
        v = np.array(list(per_subj.values()))
        p25, p50, p75 = (round(float(q), 2) for q in np.percentile(v, [25, 50, 75]))
        result["cells"][f"{metric}/{ctx}"] = {
            "n_subjects": len(v),
            "p25": p25,
            "p50": p50,
            "p75": p75,
            "per_subject": per_subj,
        }
        print(
            f"{metric:>7} {ctx:>6} {len(v):>3} {p25:>6} {p50:>6} {p75:>6}   {th.SIGMA_FLOOR[metric]}"
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sigma.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
