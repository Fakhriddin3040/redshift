"""DP-1: PPG-DaLiA S#.pkl -> 1 Hz track + beat-to-beat intervals (docs/DATA_PLAN.md §4).

    python -m ml.prep_dalia            # all subjects, one child process each
    python -m ml.prep_dalia S1 S7      # selected subjects
    python -m ml.prep_dalia --plot S1  # also write data/tracks/dalia/plots/S1.png

Each pkl is ~1.4 GB and unpickles to several GB, so every subject runs in its own
process and the memory is returned to the OS between subjects.
"""

import pickle
import subprocess
import sys

import numpy as np
import pandas as pd

from ml.paths import DALIA, TRACKS

OUT_DIR = TRACKS / "dalia"
SUBJECTS = [f"S{i}" for i in range(1, 16)]

ACC_HZ, SLOW_HZ, CHEST_HZ = 32, 4, 700
LABEL_SHIFT_S, LABEL_CENTER_S = 2, 4  # label[i] covers [2i, 2i+8) s

# Activity IDs from PPG_FieldStudy_readme.pdf §II (checked 2026-11-15).
ACTIVITY = {
    0: ("transient", "none"),
    1: ("sitting", "rest"),
    2: ("stairs", "active"),
    3: ("table_soccer", "active"),
    4: ("cycling", "active"),
    5: ("driving", "rest"),
    6: ("lunch", "rest"),
    7: ("walking", "active"),
    8: ("working", "rest"),
}
CTX_CATEGORIES = ["rest", "active", "sleep", "none"]

IBI_MIN_MS, IBI_MAX_MS = 300.0, 2000.0
IBI_MAX_JUMP = 0.20
# The plan compares each IBI with "the previous accepted" one. If that one is old,
# the comparison is meaningless and would lock out everything after a real HR change,
# so the reference is dropped when it is older than this.
IBI_REF_MAX_AGE_S = 5.0
HRV_WINDOW_S = 300
HRV_MIN_COVERAGE = 0.8


def act_mg_per_second(acc_g: np.ndarray, n_sec: int) -> np.ndarray:
    mag = np.linalg.norm(acc_g[: n_sec * ACC_HZ].astype(np.float64), axis=1)
    return (np.abs(mag - 1.0).reshape(n_sec, ACC_HZ).mean(axis=1) * 1000.0).astype(
        np.float32
    )


def mode_per_second(codes: np.ndarray, n_sec: int) -> np.ndarray:
    block = codes[: n_sec * SLOW_HZ].astype(np.int64).reshape(n_sec, SLOW_HZ)
    counts = (block[:, :, None] == np.arange(len(ACTIVITY))).sum(axis=1)
    return counts.argmax(axis=1).astype(np.int8)


def hr_on_grid(label: np.ndarray, n_sec: int) -> np.ndarray:
    t_label = np.arange(len(label)) * LABEL_SHIFT_S + LABEL_CENTER_S
    grid = np.arange(n_sec)
    # No extrapolation: seconds before the first / after the last window stay NaN.
    return np.interp(grid, t_label, label, left=np.nan, right=np.nan).astype(np.float32)


def beat_intervals(rpeaks: np.ndarray) -> pd.DataFrame:
    t_beat = np.asarray(rpeaks, dtype=np.float64) / CHEST_HZ
    ibi = np.diff(t_beat) * 1000.0
    t = t_beat[1:]  # stamped at the second beat
    ok = np.zeros(len(ibi), dtype=bool)
    ref, ref_t = None, -np.inf
    for i, (ti, x) in enumerate(zip(t, ibi, strict=True)):
        if not IBI_MIN_MS <= x <= IBI_MAX_MS:
            continue
        if ref is not None and ti - ref_t > IBI_REF_MAX_AGE_S:
            ref = None
        if ref is not None and abs(x - ref) > IBI_MAX_JUMP * ref:
            continue
        ok[i] = True
        ref, ref_t = x, ti
    return pd.DataFrame(
        {"t": t.astype(np.float64), "ibi_ms": ibi.astype(np.float32), "ok": ok}
    )


def rmssd_trailing(ibi: pd.DataFrame, n_sec: int) -> np.ndarray:
    """RMSSD of accepted successive-IBI pairs in (t - 300, t], per integer second."""
    t = ibi["t"].to_numpy()
    x = ibi["ibi_ms"].to_numpy(dtype=np.float64)
    ok = ibi["ok"].to_numpy()

    pair = ok[1:] & ok[:-1]  # both neighbours accepted
    pair_t = t[1:][pair]
    sq = np.diff(x)[pair] ** 2
    cum_sq = np.concatenate([[0.0], np.cumsum(sq)])

    ok_t = t[ok]
    cum_cov = np.concatenate([[0.0], np.cumsum(x[ok]) / 1000.0])

    grid = np.arange(n_sec, dtype=np.float64)
    hi = np.searchsorted(pair_t, grid, side="right")
    lo = np.searchsorted(pair_t, grid - HRV_WINDOW_S, side="right")
    n = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        rmssd = np.sqrt((cum_sq[hi] - cum_sq[lo]) / n)

    # "80 % of the expected beats": accepted intervals must cover 80 % of the window.
    chi = np.searchsorted(ok_t, grid, side="right")
    clo = np.searchsorted(ok_t, grid - HRV_WINDOW_S, side="right")
    coverage = (cum_cov[chi] - cum_cov[clo]) / HRV_WINDOW_S
    rmssd[(coverage < HRV_MIN_COVERAGE) | (n < 2)] = np.nan
    return rmssd.astype(np.float32)


def build(subject: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    with open(DALIA / subject / f"{subject}.pkl", "rb") as f:
        raw = pickle.load(f, encoding="latin1")
    wrist = raw["signal"]["wrist"]
    acc, temp = np.asarray(wrist["ACC"]), np.asarray(wrist["TEMP"]).ravel()
    activity = np.asarray(raw["activity"]).ravel()
    label = np.asarray(raw["label"], dtype=np.float64).ravel()
    rpeaks = np.asarray(raw["rpeaks"]).ravel()
    del raw, wrist

    n_sec = min(len(acc) // ACC_HZ, len(temp) // SLOW_HZ, len(activity) // SLOW_HZ)
    act_code = mode_per_second(activity, n_sec)
    ibi = beat_intervals(rpeaks)
    ibi = ibi[ibi["t"] < n_sec].reset_index(drop=True)

    track = pd.DataFrame(
        {
            "subj": f"dalia:{subject}",
            "t": np.arange(n_sec, dtype=np.int32),
            "hr": hr_on_grid(label, n_sec),
            "act_mg": act_mg_per_second(acc, n_sec),
            "skin_t": temp[: n_sec * SLOW_HZ]
            .astype(np.float64)
            .reshape(n_sec, SLOW_HZ)
            .mean(axis=1)
            .astype(np.float32),
            "ctx_label": pd.Categorical(
                [ACTIVITY[c][1] for c in act_code], categories=CTX_CATEGORIES
            ),
            "act_code": act_code,
            "hrv_rmssd_ms": rmssd_trailing(ibi, n_sec),
            "src": pd.Categorical(["dalia"] * n_sec, categories=["dalia", "sleep"]),
        }
    )
    return track, ibi


def plot(subject: str, track: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"rest": "#4c9be8", "active": "#e8834c", "none": "#bbbbbb"}
    t_min = track["t"].to_numpy() / 60.0
    fig, axes = plt.subplots(4, 1, figsize=(14, 9), sharex=True)
    for ax, col, name in zip(
        axes,
        ["hr", "act_mg", "skin_t", "hrv_rmssd_ms"],
        ["HR, bpm (ECG)", "act_mg", "skin T, °C", "RMSSD 5 min, ms"],
        strict=True,
    ):
        ax.plot(t_min, track[col], lw=0.7, color="black")
        ax.set_ylabel(name)
    code = track["act_code"].to_numpy()
    edges = np.flatnonzero(np.diff(code)) + 1
    for a, b in zip(np.r_[0, edges], np.r_[edges, len(code)], strict=True):
        name, ctx = ACTIVITY[int(code[a])]
        for ax in axes:
            ax.axvspan(a / 60, b / 60, color=colors[ctx], alpha=0.25, lw=0)
        if ctx != "none":
            axes[0].text(
                (a + b) / 120,
                1.02,
                name,
                ha="center",
                fontsize=8,
                transform=axes[0].get_xaxis_transform(),
            )
    axes[-1].set_xlabel(
        "minutes from start (blue = rest, orange = active, grey = none)"
    )
    fig.suptitle(f"PPG-DaLiA {subject}: 1 Hz track", y=0.995)
    fig.tight_layout()
    (OUT_DIR / "plots").mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / "plots" / f"{subject}.png", dpi=110)
    plt.close(fig)


def run_one(subject: str, with_plot: bool) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    track, ibi = build(subject)
    track.to_parquet(OUT_DIR / f"{subject}.parquet", index=False)
    ibi.to_parquet(OUT_DIR / f"{subject}_ibi.parquet", index=False)
    if with_plot:
        plot(subject, track)
    by_ctx = track.groupby("ctx_label", observed=True)
    hr, act = by_ctx["hr"].median(), by_ctx["act_mg"].median()
    print(
        f"{subject}: {len(track)} s ({len(track) / 3600:.2f} h)"
        f" | hr NaN {track['hr'].isna().mean():.1%}"
        f" | hr rest/active {hr.get('rest', np.nan):.0f}/{hr.get('active', np.nan):.0f}"
        f" | act_mg rest/active {act.get('rest', np.nan):.0f}/{act.get('active', np.nan):.0f}"
        f" | skin_t {track['skin_t'].median():.1f}"
        f" | ibi ok {ibi['ok'].mean():.1%} of {len(ibi)}"
        f" | rmssd rest {by_ctx['hrv_rmssd_ms'].median().get('rest', np.nan):.0f} ms"
        f" (NaN {track['hrv_rmssd_ms'].isna().mean():.0%})",
        flush=True,
    )


def main(argv: list[str]) -> int:
    with_plot = "--plot" in argv
    subjects = [a for a in argv if not a.startswith("--")] or SUBJECTS
    if len(subjects) == 1:
        run_one(subjects[0], with_plot)
        return 0
    failed = []
    for s in subjects:
        cmd = [
            sys.executable,
            "-m",
            "ml.prep_dalia",
            s,
            *(["--plot"] if with_plot else []),
        ]
        if subprocess.run(cmd).returncode != 0:
            failed.append(s)
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
