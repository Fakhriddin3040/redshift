"""SIM-4: ISS cabin CO2 (NASA OSDR EDA) -> 1-min profile for vdev, plus the daily
radiation seed file (docs/DATA_PLAN.md §3.1, §7; docs/TASKS.md §4).

    python -m ml.prep_eda

Writes data/env/co2_profile.parquet (t_min, co2_ppm, mission),
       ml/out/eda_stats.json (numbers for DATA_NOTES.md and the deck),
       vigil/backend/seed/radiation_daily.csv (day,total,gcr,saa; mGy/day),
       vigil/vdev/assets/co2_iss_rr12.csv (t_min,co2_ppm; the profile vdev plays).
"""

import json
import sys

import numpy as np
import pandas as pd

from ml.paths import EDA, ENV, OUT, SEED_DIR, VDEV_ASSETS
from vigil.core import thresholds as th
from vigil.core.minute import ppco2

CO2_MIN_PPM, CO2_MAX_PPM = 1000.0, 20000.0  # outside -> NaN (sensor glitches)
MAX_INTERP_GAP_MIN = 15
RADIATION_MISSION = "RR-12"  # the mission vdev plays as the normal cabin profile


def co2_profile(mission: str) -> tuple[pd.DataFrame, dict]:
    raw = pd.DataFrame(json.loads((EDA / f"{mission}_co2_iss.json").read_text()))
    s = pd.Series(
        raw["co2_iss"].to_numpy(dtype=np.float64),
        index=pd.to_datetime(raw["time"], utc=True),
    ).sort_index()
    s = s[~s.index.duplicated()]
    n_low, n_high = int((s < CO2_MIN_PPM).sum()), int((s > CO2_MAX_PPM).sum())
    n_null = int(s.isna().sum())
    s = s.where((s >= CO2_MIN_PPM) & (s <= CO2_MAX_PPM)).dropna()

    # 1-min grid; linear interpolation only between points <= 15 min apart.
    grid = pd.date_range(s.index[0].floor("min"), s.index[-1].floor("min"), freq="1min")
    src_min = (s.index - grid[0]).total_seconds().to_numpy() / 60.0
    grid_min = np.arange(len(grid), dtype=np.float64)
    value = np.interp(grid_min, src_min, s.to_numpy())
    nxt = np.searchsorted(src_min, grid_min, side="left")
    prev = np.clip(nxt - 1, 0, None)
    nxt = np.clip(nxt, None, len(src_min) - 1)
    gap = src_min[nxt] - src_min[prev]
    exact = src_min[nxt] == grid_min
    value[(gap > MAX_INTERP_GAP_MIN) & ~exact] = np.nan

    profile = pd.DataFrame(
        {
            "t_min": grid_min.astype(np.int32),
            "co2_ppm": value.astype(np.float32),
            "mission": mission,
        }
    )

    pp = pd.Series(ppco2_array(value), index=grid)
    hourly = pp.rolling("60min", min_periods=th.PPCO2_MIN_VALUES).mean()
    days_above = hourly.groupby(hourly.index.date).max() > th.PPCO2_WATCH
    stats = {
        "start": s.index[0].strftime("%Y-%m-%dT%H:%MZ"),
        "end": s.index[-1].strftime("%Y-%m-%dT%H:%MZ"),
        "raw_points": len(raw),
        "removed_below_1000ppm": n_low,
        "removed_above_20000ppm": n_high,
        "removed_null": n_null,
        "minutes": len(grid),
        "minutes_nan": int(np.isnan(value).sum()),
        "ppm_median": round(float(np.nanmedian(value)), 0),
        "ppm_max": round(float(np.nanmax(value)), 0),
        "ppco2_mean_mmHg": round(float(pp.mean()), 2),
        "ppco2_max_mmHg": round(float(pp.max()), 2),
        "ppco2_max_1h_mean_mmHg": round(float(hourly.max()), 2),
        "hours_1h_mean_above_3mmHg": round(
            float((hourly > th.PPCO2_WATCH).sum()) / 60, 1
        ),
        "hours_1h_mean_above_5.3mmHg": round(
            float((hourly > th.PPCO2_ALERT).sum()) / 60, 1
        ),
        "days_total": int(len(days_above)),
        "days_with_1h_mean_above_3mmHg": int(days_above.sum()),
    }
    return profile, stats


def ppco2_array(co2_ppm: np.ndarray) -> np.ndarray:
    # Same formula as the backend, at standard pressure (EDA has no cabin pressure).
    return co2_ppm * (ppco2(1.0, None) or 0.0)


def radiation_seed(mission: str) -> tuple[pd.DataFrame, dict]:
    raw = pd.DataFrame(json.loads((EDA / f"{mission}_radiation.json").read_text()))
    seed = pd.DataFrame(
        {
            "day": pd.to_datetime(raw["time"], utc=True).dt.strftime("%Y-%m-%d"),
            "total": raw["total"].round(5),
            "gcr": raw["gcr"].round(5),
            "saa": raw["saa"].round(5),
        }
    ).sort_values("day")
    stats = {
        "mission": mission,
        "unit": "mGy/day",
        "days": len(seed),
        "first_day": seed["day"].iloc[0],
        "last_day": seed["day"].iloc[-1],
        "total_min": float(seed["total"].min()),
        "total_max": float(seed["total"].max()),
        "total_mean": round(float(seed["total"].mean()), 4),
    }
    return seed, stats


def main() -> int:
    missions = sorted(
        (p.name.removesuffix("_co2_iss.json") for p in EDA.glob("*_co2_iss.json")),
        key=lambda m: int(m.split("-")[1]),
    )
    profiles, stats = [], {"pressure_hPa": th.STD_PRESSURE_HPA, "co2": {}}
    for m in missions:
        profile, stats["co2"][m] = co2_profile(m)
        profiles.append(profile)
        s = stats["co2"][m]
        print(
            f"{m:>6}: {s['minutes']} min ({s['minutes_nan']} NaN), removed <1000 ppm:"
            f" {s['removed_below_1000ppm']}, ppCO2 mean/max {s['ppco2_mean_mmHg']}/"
            f"{s['ppco2_max_mmHg']}, max 1-h mean {s['ppco2_max_1h_mean_mmHg']},"
            f" hours >3.0: {s['hours_1h_mean_above_3mmHg']},"
            f" days >3.0: {s['days_with_1h_mean_above_3mmHg']}/{s['days_total']}"
        )
    ENV.mkdir(parents=True, exist_ok=True)
    out = pd.concat(profiles, ignore_index=True)
    out["mission"] = out["mission"].astype("category")
    out.to_parquet(ENV / "co2_profile.parquet", index=False)

    # The Docker image has no data/, so vdev ships the small cleaned profile it plays.
    VDEV_ASSETS.mkdir(parents=True, exist_ok=True)
    rr12 = out[out["mission"] == RADIATION_MISSION]
    rr12.assign(co2_ppm=rr12["co2_ppm"].round(0).astype("Int64"))[
        ["t_min", "co2_ppm"]
    ].to_csv(VDEV_ASSETS / "co2_iss_rr12.csv", index=False)

    seed, stats["radiation"] = radiation_seed(RADIATION_MISSION)
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    seed.to_csv(SEED_DIR / "radiation_daily.csv", index=False)
    print(f"radiation seed: {stats['radiation']}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eda_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
