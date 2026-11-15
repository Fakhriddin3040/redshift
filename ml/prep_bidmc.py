"""DP-6 / C4: AR(1) parameters for SpO2 and respiratory rate from BIDMC numerics
(docs/DATA_PLAN.md §6). Writes ml/out/ar1.json.

    python -m ml.prep_bidmc

Model per record: x_t - mu = phi * (x_{t-1} - mu) + eps,  eps ~ N(0, sigma_eps).
Fit on the train records, then check on the held-out records that a series
simulated with the median parameters has a similar std and lag-1 autocorrelation.
"""

import json
import sys

import numpy as np
import pandas as pd

from ml.paths import BIDMC, MANIFEST, OUT

MIN_RUN_S = 60
VALID = {"spo2": (50.0, 100.0), "rr": (0.0, 60.0)}  # rr: (0, 60], spo2: [50, 100]
PLAN_DEFAULT = {
    "spo2": {"phi": 0.98, "sigma_eps": 0.15},
    "rr": {"phi": 0.95, "sigma_eps": 0.4},
}
SIM_RECORDS, SIM_LEN, SIM_SEED = 2000, 481, 2026


def load(record: str) -> pd.DataFrame:
    df = pd.read_csv(BIDMC / f"bidmc_{record}_Numerics.csv")
    df.columns = [c.strip() for c in df.columns]
    out = pd.DataFrame(
        {"t": df["Time [s]"], "hr": df["HR"], "spo2": df["SpO2"], "rr": df["RESP"]}
    )
    out.loc[~out["spo2"].between(50, 100), "spo2"] = np.nan
    out.loc[~((out["rr"] > 0) & (out["rr"] <= 60)), "rr"] = np.nan
    out.loc[~(out["hr"] > 0), "hr"] = np.nan
    return out


def valid_runs(x: np.ndarray) -> list[np.ndarray]:
    ok = ~np.isnan(x)
    edges = np.flatnonzero(np.diff(np.r_[False, ok, False].astype(int)))
    return [
        x[a:b]
        for a, b in zip(edges[::2], edges[1::2], strict=True)
        if b - a >= MIN_RUN_S
    ]


def fit(x: np.ndarray) -> dict | None:
    runs = valid_runs(x)
    if not runs:
        return None
    mu = float(np.concatenate(runs).mean())
    cur = np.concatenate([r[1:] for r in runs]) - mu
    prev = np.concatenate([r[:-1] for r in runs]) - mu
    std = float(np.concatenate(runs).std())
    if std == 0 or prev.std() == 0 or cur.std() == 0:
        return {"mu": mu, "std": std, "phi": None, "sigma_eps": None, "n": len(cur)}
    phi = float(np.corrcoef(cur, prev)[0, 1])
    return {
        "mu": mu,
        "std": std,
        "phi": phi,
        "sigma_eps": float((cur - phi * prev).std()),
        "n": len(cur),
    }


def simulate(phi: float, sigma_eps: float, mu: float, quantize: bool) -> dict:
    """Median std and lag-1 autocorrelation of simulated 8-min records."""
    rng = np.random.default_rng(SIM_SEED)
    x = np.empty((SIM_RECORDS, SIM_LEN))
    x[:, 0] = rng.normal(0, sigma_eps / np.sqrt(1 - phi**2), SIM_RECORDS)
    eps = rng.normal(0, sigma_eps, (SIM_RECORDS, SIM_LEN))
    for t in range(1, SIM_LEN):
        x[:, t] = phi * x[:, t - 1] + eps[:, t]
    x += mu
    if quantize:
        x = np.round(x)
    stds, phis = [], []
    for row in x:
        f = fit(row)
        stds.append(f["std"])
        if f["phi"] is not None:
            phis.append(f["phi"])
    return {
        "std": float(np.median(stds)),
        "phi": float(np.median(phis)) if phis else None,
        "constant_frac": 1 - len(phis) / SIM_RECORDS,
    }


def med(fits: list[dict], key: str) -> float | None:
    vals = [f[key] for f in fits if f is not None and f[key] is not None]
    return float(np.median(vals)) if vals else None


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())["bidmc"]
    result: dict = {
        "dataset": "BIDMC numerics, 1 Hz",
        "min_run_s": MIN_RUN_S,
        "train_records": manifest["train"],
        "holdout_records": manifest["holdout"],
    }
    for metric in ("spo2", "rr"):
        train = [fit(load(r)[metric].to_numpy(float)) for r in manifest["train"]]
        hold = [fit(load(r)[metric].to_numpy(float)) for r in manifest["holdout"]]
        phi, sig, mu = med(train, "phi"), med(train, "sigma_eps"), med(train, "mu")
        n_const = sum(f is not None and f["phi"] is None for f in train)
        n_none = sum(f is None for f in train)
        result[metric] = {
            "phi": round(phi, 4),
            "sigma_eps": round(sig, 4),
            "mu_median": round(mu, 2),
            "train": {
                "n_fitted": sum(f is not None and f["phi"] is not None for f in train),
                "n_constant": n_const,
                "n_no_valid_run": n_none,
                "std_median": round(med(train, "std"), 3),
                "phi_iqr": [
                    round(float(q), 3)
                    for q in np.percentile(
                        [f["phi"] for f in train if f and f["phi"] is not None],
                        [25, 75],
                    )
                ],
                "sigma_eps_iqr": [
                    round(float(q), 3)
                    for q in np.percentile(
                        [f["sigma_eps"] for f in train if f and f["phi"] is not None],
                        [25, 75],
                    )
                ],
            },
            "holdout_real": {
                "std_median": round(med(hold, "std"), 3),
                "phi_median": round(med(hold, "phi"), 4),
                "n_constant": sum(f is not None and f["phi"] is None for f in hold),
            },
            "holdout_check_sim_fitted": simulate(phi, sig, mu, quantize=True),
            "holdout_check_sim_plan_default": simulate(
                **PLAN_DEFAULT[metric], mu=mu, quantize=True
            ),
            "plan_default": PLAN_DEFAULT[metric],
        }

    # Optional sanity check (ICU patients, not a calibration): RR vs HR across records.
    rows = [load(r)[["hr", "rr"]].mean() for r in manifest["train"]]
    hr, rr = np.array([r["hr"] for r in rows]), np.array([r["rr"] for r in rows])
    ok = ~np.isnan(hr) & ~np.isnan(rr)
    slope, intercept = np.polyfit(hr[ok], rr[ok], 1)
    result["rr_vs_hr_across_records"] = {
        "slope_br_per_bpm": round(float(slope), 4),
        "intercept": round(float(intercept), 2),
        "r": round(float(np.corrcoef(hr[ok], rr[ok])[0, 1]), 3),
        "n": int(ok.sum()),
        "our_param_slope": 0.08,
    }

    # Decision (docs/DATA_NOTES.md §4): the vdev generator uses the fitted values for
    # both metrics. They reproduce the real spread; the PLAN constants overshoot it.
    result["chosen_for_vdev"] = {
        m: {
            "phi": round(result[m]["phi"], 2),
            "sigma_eps": round(result[m]["sigma_eps"], 2),
            "stationary_std": round(
                round(result[m]["sigma_eps"], 2)
                / (1 - round(result[m]["phi"], 2) ** 2) ** 0.5,
                2,
            ),
        }
        for m in ("spo2", "rr")
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ar1.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if "records" not in k}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
