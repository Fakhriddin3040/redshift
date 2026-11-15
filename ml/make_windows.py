"""ML-2: labelled 10-minute windows for the pattern classifier (PLAN §10).
Writes data/windows/train.parquet and data/windows/test.parquet.

    python -m ml.make_windows

The vdev generator runs offline through CrewState: 14 normal days to learn the
personal norm, then days with scenarios injected at random times, with random
severity and duration. A window is labelled with a scenario when the scenario
covers at least 5 of its 10 minutes; windows with 1-4 scenario minutes are dropped.

Train and test use different people (profiles) and different seeds. The abnormal
classes are simulated: this measures how well the model separates OUR models of
each deviation, not how it does on real patients.
"""

import random
import sys

import pandas as pd

from ml.eval_scenarios import to_minute
from ml.paths import DATA
from vigil.core.features import FEATURES, WINDOW_MIN, features
from vigil.core.pipeline import CrewState
from vigil.vdev.signal import PROFILES, Cabin, CrewSim, Profile, make_scenario

OUT_DIR = DATA / "windows"
START_MIN = 1_794_700_800 // 60
LEARN_DAYS = 14
SCENARIO_DAYS = 5
GAP_MIN = (100, 150)  # between scenario starts: long enough to recover in between
NORMAL_KEEP = 0.12  # share of normal windows kept

CLASS_OF = {
    "hypoxia": "hypoxia",
    "tachycardia_rest": "tachycardia_rest",
    "bradycardia": "bradycardia",
    "fever_like": "fever_like",
    "hypercapnia": "hypercapnia",
    "depressurization": "depressurization",
    "motion_artifact": "sensor_artifact",
}
CLASSES = ["normal", *CLASS_OF.values()]
DURATION_MIN = {
    "hypoxia": (8, 20), "tachycardia_rest": (6, 20), "bradycardia": (6, 20),
    "fever_like": (15, 35), "hypercapnia": (15, 45), "depressurization": (10, 25),
    "motion_artifact": (5, 15),
}  # fmt: skip

TRAIN_PROFILES = [p for p in PROFILES if p.crew <= 5]
# Test people are not in the training set: crew 6 and 7, and two more made up here.
TEST_PROFILES = [
    *(p for p in PROFILES if p.crew >= 6),
    Profile(8, 59, 50, 97.6, 14, 33.2, 52, 137, 21 * 60 + 50, (7 * 60 + 10, 18 * 60 + 20)),
    Profile(9, 67, 57, 96.9, 15, 34.0, 36, 143, 22 * 60 + 10, (6 * 60 + 50, 17 * 60 + 50)),
]  # fmt: skip
TRAIN_SEEDS, TEST_SEEDS = range(0, 10), range(100, 106)


def run(profile: Profile, seed: int) -> list[dict]:
    rng = random.Random(seed * 7919 + profile.crew)
    sim, cabin, state = CrewSim(profile, seed), Cabin(seed), CrewState()
    learn_end = START_MIN + LEARN_DAYS * 1440
    end = learn_end + SCENARIO_DAYS * 1440

    scenarios = []
    t = learn_end + rng.randint(20, 120)
    while t < end - 120:
        name = rng.choice(list(CLASS_OF))
        scenarios.append(
            make_scenario(
                name, profile.crew, t * 60, rng,
                severity=rng.randint(1, 3),
                duration_s=rng.randint(*DURATION_MIN[name]) * 60,
            )
        )  # fmt: skip
        t += rng.randint(*GAP_MIN)

    rows, window, active = [], [], []
    for minute in range(START_MIN, end):
        live = [s for s in scenarios if s.t0 <= minute * 60 + 30 < s.end + 3600]
        res = state.on_minute(
            to_minute(minute * 60, sim.minute_sample(minute, live),
                      cabin.sample(minute * 60 + 30, live))
        )  # fmt: skip
        if minute < learn_end:
            continue
        now = [s.name for s in scenarios if s.t0 <= minute * 60 < s.end]
        window = [*window, res][-WINDOW_MIN:]
        active = [*active, now[0] if now else None][-WINDOW_MIN:]
        if len(window) < WINDOW_MIN:
            continue
        names = [a for a in active if a is not None]
        if 0 < len(names) < 5:
            continue
        label = CLASS_OF[names[-1]] if names else "normal"
        if label == "normal" and rng.random() > NORMAL_KEEP:
            continue
        x = features(window)
        rows.append(
            dict(zip(FEATURES, x, strict=True))
            | {"label": label, "crew": profile.crew, "seed": seed, "ts": minute * 60,
               "level": res.level, "ctx": res.ctx.label}
        )  # fmt: skip
    return rows


def build(profiles: list[Profile], seeds: range) -> pd.DataFrame:
    rows = [r for p in profiles for seed in seeds for r in run(p, seed)]
    return pd.DataFrame(rows)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, profiles, seeds in (
        ("train", TRAIN_PROFILES, TRAIN_SEEDS),
        ("test", TEST_PROFILES, TEST_SEEDS),
    ):
        df = build(profiles, seeds)
        df.to_parquet(OUT_DIR / f"{name}.parquet", index=False)
        print(
            f"{name}: {len(df)} windows, {df['crew'].nunique()} people x {len(seeds)} seeds"
        )
        print("  ", df["label"].value_counts().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
