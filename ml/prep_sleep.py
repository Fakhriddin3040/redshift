"""DP-4: sleep-accel -> 1 Hz night tracks + HR coverage (docs/DATA_PLAN.md §5).

    python -m ml.prep_sleep            # all 31 subjects
    python -m ml.prep_sleep 1066528

Writes data/tracks/sleep/<id>.parquet and data/tracks/sleep/coverage.json.
ml/split.py reads coverage.json to exclude nights with too little heart rate.
"""

import json
import sys

import numpy as np
import pandas as pd

from ml.paths import SLEEP, TRACKS

OUT_DIR = TRACKS / "sleep"
EPOCH_S = 30
HR_CARRY_S = 15  # carry the last HR value forward at most this long
CTX_CATEGORIES = ["rest", "active", "sleep", "none"]


def subjects() -> list[str]:
    return sorted(
        (p.name.split("_")[0] for p in (SLEEP / "labels").glob("*_labeled_sleep.txt")),
        key=int,
    )


def stage_to_ctx(stage: int) -> str:
    if stage == 0:
        return "rest"  # awake in bed
    if 1 <= stage <= 5:
        return "sleep"  # N1-N3, legacy N4, REM
    return "none"  # -1 = unscored, or no epoch at all


def build(subject: str) -> pd.DataFrame:
    labels = pd.read_csv(
        SLEEP / "labels" / f"{subject}_labeled_sleep.txt",
        sep=" ",
        names=["t", "stage"],
    )
    t0 = int(labels["t"].iloc[0])
    t1 = int(labels["t"].iloc[-1]) + EPOCH_S
    n_sec = t1 - t0
    grid = np.arange(n_sec)

    # Stage per second; seconds not covered by any epoch stay -1.
    act_code = np.full(n_sec, -1, dtype=np.int8)
    for t, stage in zip(
        labels["t"].to_numpy(), labels["stage"].to_numpy(), strict=True
    ):
        a = int(t) - t0
        act_code[a : a + EPOCH_S] = stage

    # Motion: bin by timestamp, because the sample rate varies (7.7-66 Hz).
    motion = pd.read_csv(
        SLEEP / "motion" / f"{subject}_acceleration.txt",
        sep=" ",
        names=["t", "x", "y", "z"],
        dtype=np.float64,
    )
    motion = motion[(motion["t"] >= t0) & (motion["t"] < t1)]
    sec = np.floor(motion["t"].to_numpy() - t0).astype(np.int64)
    dev = np.abs(np.linalg.norm(motion[["x", "y", "z"]].to_numpy(), axis=1) - 1.0)
    count = np.bincount(sec, minlength=n_sec)[:n_sec]
    total = np.bincount(sec, weights=dev, minlength=n_sec)[:n_sec]
    with np.errstate(invalid="ignore", divide="ignore"):
        act_mg = np.where(count > 0, total / count * 1000.0, np.nan)

    # Heart rate: last sample at or before the grid second, if it is fresh enough.
    hr_raw = pd.read_csv(
        SLEEP / "heart_rate" / f"{subject}_heartrate.txt", names=["t", "bpm"]
    ).sort_values("t")
    hr_t = hr_raw["t"].to_numpy() - t0
    hr_v = hr_raw["bpm"].to_numpy(dtype=np.float64)
    idx = np.searchsorted(hr_t, grid, side="right") - 1
    safe = np.clip(idx, 0, None)
    age = grid - hr_t[safe]
    hr = np.where((idx >= 0) & (age <= HR_CARRY_S), hr_v[safe], np.nan)

    return pd.DataFrame(
        {
            "subj": f"sleep:{subject}",
            "t": grid.astype(np.int32),
            "hr": hr.astype(np.float32),
            "act_mg": act_mg.astype(np.float32),
            "skin_t": np.full(n_sec, np.nan, dtype=np.float32),  # not in this dataset
            "ctx_label": pd.Categorical(
                [stage_to_ctx(int(c)) for c in act_code], categories=CTX_CATEGORIES
            ),
            "act_code": act_code,
            "hrv_rmssd_ms": np.full(n_sec, np.nan, dtype=np.float32),
            "src": pd.Categorical(["sleep"] * n_sec, categories=["dalia", "sleep"]),
        }
    )


def main(argv: list[str]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cov_path = OUT_DIR / "coverage.json"
    coverage = json.loads(cov_path.read_text()) if cov_path.exists() else {}
    for s in argv or subjects():
        track = build(s)
        track.to_parquet(OUT_DIR / f"{s}.parquet", index=False)
        stats = {
            "hours": round(len(track) / 3600, 2),
            "hr_coverage": round(float(track["hr"].notna().mean()), 4),
            "act_coverage": round(float(track["act_mg"].notna().mean()), 4),
            "sleep_frac": round(float((track["ctx_label"] == "sleep").mean()), 4),
            "unscored_frac": round(float((track["ctx_label"] == "none").mean()), 4),
        }
        coverage[s] = stats
        asleep = track[track["ctx_label"] == "sleep"]
        print(
            f"{s:>8}: {stats['hours']:5.2f} h | hr cov {stats['hr_coverage']:.0%}"
            f" | act cov {stats['act_coverage']:.0%} | sleep {stats['sleep_frac']:.0%}"
            f" | unscored {stats['unscored_frac']:.0%}"
            f" | asleep hr {asleep['hr'].median():.0f}, act_mg {asleep['act_mg'].median():.1f}",
            flush=True,
        )
    cov_path.write_text(
        json.dumps(dict(sorted(coverage.items(), key=lambda kv: int(kv[0]))), indent=2)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
