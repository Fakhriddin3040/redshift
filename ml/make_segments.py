"""T4: real daytime segments for vdev, from the HELD-OUT PPG-DaLiA subjects
(docs/DATA_PLAN.md §8.1). Writes vigil/vdev/assets/dalia_rest_segments.csv.

    python -m ml.make_segments

A segment is a run of at least 3 whole minutes labelled `rest` (sitting, working,
lunch, driving). Per minute it keeps
    hr_rel  = minute heart rate - the donor's resting heart rate (C1)
    act_mg  = minute mean of wrist motion
vdev replays them for awake, non-exercise time and re-scales heart rate to each
crew member: hr = rest_crew + k * hr_rel. PPG-DaLiA is CC BY 4.0 (docs/DATA_LICENSES.md).
"""

import csv
import sys

from ml.minutes import load_track, manifest, to_minutes
from ml.paths import VDEV_ASSETS

MIN_SEGMENT_MIN = 3


def main() -> int:
    rows, n_seg = [], 0
    for subject in manifest()["dalia"]["holdout"]:
        track = load_track("dalia", subject)
        rest_hr = float(track.loc[track["ctx_label"] == "rest", "hr"].median())
        run: list[tuple[float, float]] = []
        for lm in [*to_minutes(track), None]:
            ok = (
                lm is not None
                and lm.label == "rest"
                and lm.minute.hr is not None
                and lm.minute.act_mg is not None
            )
            if ok:
                run.append((lm.minute.hr - rest_hr, lm.minute.act_mg))
                continue
            if len(run) >= MIN_SEGMENT_MIN:
                n_seg += 1
                rows += [(n_seg, subject, round(h, 1), round(a)) for h, a in run]
            run = []
    VDEV_ASSETS.mkdir(parents=True, exist_ok=True)
    with open(VDEV_ASSETS / "dalia_rest_segments.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["segment", "donor", "hr_rel", "act_mg"])
        w.writerows(rows)
    hr = sorted(r[2] for r in rows)
    act = sorted(r[3] for r in rows)
    q = lambda v, p: v[int(p * (len(v) - 1))]  # noqa: E731
    print(
        f"{n_seg} segments, {len(rows)} minutes ({len(rows) / 60:.1f} h) from held-out subjects"
    )
    print(
        f"hr_rel p5/p50/p95: {q(hr, 0.05)}/{q(hr, 0.5)}/{q(hr, 0.95)} bpm | act_mg p5/p50/p95: {q(act, 0.05)}/{q(act, 0.5)}/{q(act, 0.95)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
