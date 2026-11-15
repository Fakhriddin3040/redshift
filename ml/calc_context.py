"""C1, C2, C3 (docs/DATA_PLAN.md §9). Writes ml/out/context.json.

    python -m ml.calc_context

C1  resting HR per DaLiA subject = median 1 Hz hr where ctx_label = rest.
C2  context thresholds on 1-min act_mg, fitted on TRAIN subjects only:
      active = equal-error point of DaLiA rest vs DaLiA active minutes;
      sleep  = equal-error point of sleep-accel asleep vs DaLiA rest (awake) minutes.
C3  accuracy of vigil.core.context.ContextTracker, as it is in vigil/core,
    on HELD-OUT subjects (train is printed for reference only).
"""

import json
import sys
from collections import Counter, defaultdict
from statistics import median

import numpy as np

from ml.minutes import LabeledMinute, load_track, manifest, to_minutes
from ml.paths import OUT
from ml.prep_dalia import ACTIVITY
from vigil.core import thresholds as th
from vigil.core.context import ContextTracker, Ctx

CLASSES = ("rest", "active", "sleep")


def equal_error(low: np.ndarray, high: np.ndarray) -> dict:
    """Threshold T where P(low >= T) = P(high < T). `low` is the quieter class."""
    cand = np.unique(np.concatenate([low, high]))
    miss_low = np.array([(low >= t).mean() for t in cand])
    miss_high = np.array([(high < t).mean() for t in cand])
    i = int(np.argmin(np.abs(miss_low - miss_high)))
    return {
        "threshold": round(float(cand[i]), 1),
        "error_low_class": round(float(miss_low[i]), 4),
        "error_high_class": round(float(miss_high[i]), 4),
    }


def pct(x: np.ndarray) -> dict:
    return {
        f"p{q}": round(float(np.percentile(x, q)), 1) for q in (5, 25, 50, 75, 95)
    } | {"n": len(x)}


def running_rest_hr(values: list[float]) -> float | None:
    return median(values) if len(values) >= th.REST_HR_MIN_VALUES else None


def evaluate(
    minutes: list[LabeledMinute], rest_hr: float | None, learn_rest: bool
) -> list[tuple[str, int, str]]:
    """Run the backend classifier over one recording -> (label, act_code, predicted)."""
    tracker = ContextTracker()
    rest_values: list[float] = []
    out = []
    for lm in minutes:
        ref = running_rest_hr(rest_values) if learn_rest else rest_hr
        ctx = tracker.classify(lm.minute, ref)
        if ctx is Ctx.REST and lm.minute.hr is not None:
            rest_values.append(lm.minute.hr)
        out.append((lm.label, lm.act_code, ctx.label))
    return out


def score(rows: list[tuple[str, int, str]]) -> dict:
    scored = [
        (lab, code, pred)
        for lab, code, pred in rows
        if lab in CLASSES and pred != "off"
    ]
    confusion: dict = defaultdict(Counter)
    for lab, _, pred in scored:
        confusion[lab][pred] += 1
    recall = {lab: round(c[lab] / sum(c.values()), 4) for lab, c in confusion.items()}
    return {
        "n_minutes": len(scored),
        "n_skipped_none_or_mixed": sum(lab not in CLASSES for lab, _, _ in rows),
        "n_skipped_predicted_off": sum(
            lab in CLASSES and pred == "off" for lab, _, pred in rows
        ),
        "accuracy": round(sum(lab == pred for lab, _, pred in scored) / len(scored), 4),
        "balanced_accuracy": round(float(np.mean(list(recall.values()))), 4),
        "recall": recall,
        "confusion": {lab: dict(c) for lab, c in confusion.items()},
    }


def by_activity(rows: list[tuple[str, int, str]]) -> dict:
    out = {}
    for code, (name, ctx) in ACTIVITY.items():
        hits = [
            pred == ctx
            for lab, c, pred in rows
            if c == code and lab in CLASSES and pred != "off"
        ]
        if hits:
            out[name] = {
                "expected": ctx,
                "n": len(hits),
                "recall": round(float(np.mean(hits)), 4),
            }
    return out


def c3(
    dalia: dict,
    sleep: dict,
    wake_hr: dict,
    subjects_d: list[str],
    subjects_s: list[str],
) -> dict:
    d_rows = [r for s in subjects_d for r in evaluate(dalia[s], None, learn_rest=True)]
    # A night alone has no daytime rest HR. Two cases: cold start (backend default 60 bpm)
    # and "known" rest HR, approximated by the person's median HR while awake in bed.
    s_cold = [r for s in subjects_s for r in evaluate(sleep[s], None, learn_rest=False)]
    s_known = [
        r for s in subjects_s for r in evaluate(sleep[s], wake_hr[s], learn_rest=False)
    ]
    return {
        "dalia": score(d_rows) | {"by_activity": by_activity(d_rows)},
        "sleep_cold_start": score(s_cold),
        "sleep_known_rest_hr": score(s_known),
        "combined_known_rest_hr": score(d_rows + s_known),
        "combined_cold_start": score(d_rows + s_cold),
    }


def main() -> int:
    man = manifest()
    dalia = {
        s: to_minutes(load_track("dalia", s))
        for s in man["dalia"]["train"] + man["dalia"]["holdout"]
    }
    sleep_ids = man["sleep"]["train"] + man["sleep"]["holdout"]
    # C2 also uses the night excluded from vdev (its motion is still valid).
    sleep_c2_ids = man["sleep"]["train"] + [e["id"] for e in man["sleep"]["excluded"]]
    sleep = {
        s: to_minutes(load_track("sleep", s))
        for s in set(sleep_ids) | set(sleep_c2_ids)
    }

    # ---- C1
    c1 = {}
    for s in dalia:
        t = load_track("dalia", s)
        c1[s] = {
            "rest_hr": round(float(t.loc[t["ctx_label"] == "rest", "hr"].median()), 1),
            "split": "train" if s in man["dalia"]["train"] else "holdout",
        }
    wake_hr = {}
    for s in sleep_ids:
        vals = [
            lm.minute.hr
            for lm in sleep[s]
            if lm.label == "rest" and lm.minute.hr is not None
        ]
        wake_hr[s] = median(vals) if len(vals) >= 5 else None

    # ---- C2 (train only)
    def acts(pool: dict, ids: list[str], label: str) -> np.ndarray:
        return np.array(
            [
                lm.minute.act_mg
                for s in ids
                for lm in pool[s]
                if lm.label == label and lm.minute.act_mg is not None
            ]
        )

    rest = acts(dalia, man["dalia"]["train"], "rest")
    active = acts(dalia, man["dalia"]["train"], "active")
    asleep = acts(sleep, sleep_c2_ids, "sleep")
    awake_in_bed = acts(sleep, sleep_c2_ids, "rest")
    eer_active, eer_sleep = equal_error(rest, active), equal_error(asleep, rest)
    per_activity = {}
    for code, (name, _) in ACTIVITY.items():
        vals = np.array(
            [
                lm.minute.act_mg
                for s in man["dalia"]["train"]
                for lm in dalia[s]
                if lm.act_code == code and lm.minute.act_mg is not None
            ]
        )
        if len(vals):
            per_activity[name] = pct(vals)
    c2 = {
        "act_mg_1min": {
            "dalia_rest": pct(rest),
            "dalia_active": pct(active),
            "sleep_asleep": pct(asleep),
            "sleep_awake_in_bed": pct(awake_in_bed),
            "dalia_by_activity": per_activity,
        },
        "active_equal_error": eer_active,
        "sleep_equal_error": eer_sleep,
        "current": {"ACTIVE_ACT_MG": th.ACTIVE_ACT_MG, "SLEEP_ACT_MG": th.SLEEP_ACT_MG},
        "frac_asleep_minutes_at_or_below_sleep_threshold": round(
            float((asleep <= th.SLEEP_ACT_MG).mean()), 4
        ),
        "frac_dalia_rest_minutes_at_or_below_sleep_threshold": round(
            float((rest <= th.SLEEP_ACT_MG).mean()), 4
        ),
    }

    # ---- C3: the rule as it is in vigil/core, on train (for reference) and holdout (reported)
    c3_out = {
        "constants": {
            k: getattr(th, k)
            for k in (
                "ACTIVE_ACT_MG",
                "ACTIVE_COOLDOWN_S",
                "ACTIVE_COOLDOWN_MIN_RUN",
                "SLEEP_ACT_MG",
                "SLEEP_RUN_MIN",
                "SLEEP_NOISE_PENALTY",
                "SLEEP_HR_MARGIN",
            )
        },
        "train": c3(
            dalia, sleep, wake_hr, man["dalia"]["train"], man["sleep"]["train"]
        ),
        "holdout": c3(
            dalia, sleep, wake_hr, man["dalia"]["holdout"], man["sleep"]["holdout"]
        ),
    }

    result = {
        "C1_rest_hr": c1,
        "C2": c2,
        "C3": c3_out,
        "subjects": {
            "dalia_train": man["dalia"]["train"],
            "dalia_holdout": man["dalia"]["holdout"],
            "sleep_train": man["sleep"]["train"],
            "sleep_holdout": man["sleep"]["holdout"],
            "sleep_c2_extra": [e["id"] for e in man["sleep"]["excluded"]],
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "context.json").write_text(json.dumps(result, indent=2) + "\n")

    print("C1 rest HR:", {s: v["rest_hr"] for s, v in c1.items()})
    print(
        "C2 act_mg:",
        {k: v for k, v in c2["act_mg_1min"].items() if k != "dalia_by_activity"},
    )
    print("C2 by activity p50:", {k: v["p50"] for k, v in per_activity.items()})
    print("C2 EER active:", eer_active, "| sleep:", eer_sleep)
    for part in ("train", "holdout"):
        r = c3_out[part]
        print(
            f"C3 {part:>7}: dalia {r['dalia']['accuracy']:.3f} {r['dalia']['recall']}"
            f" | sleep cold {r['sleep_cold_start']['accuracy']:.3f} {r['sleep_cold_start']['recall']}"
            f" | sleep known {r['sleep_known_rest_hr']['accuracy']:.3f} {r['sleep_known_rest_hr']['recall']}"
            f" | combined cold {r['combined_cold_start']['accuracy']:.3f} known {r['combined_known_rest_hr']['accuracy']:.3f}"
        )
    print(
        "holdout by activity:",
        {k: v["recall"] for k, v in c3_out["holdout"]["dalia"]["by_activity"].items()},
    )
    print(
        "holdout confusion:",
        c3_out["holdout"]["dalia"]["confusion"],
        c3_out["holdout"]["sleep_known_rest_hr"]["confusion"],
        c3_out["holdout"]["sleep_cold_start"]["confusion"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
