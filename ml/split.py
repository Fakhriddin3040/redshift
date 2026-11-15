"""DP-2: split by person, never by row (docs/DATA_PLAN.md §8). Writes ml/manifest.json.

    python -m ml.split

Sleep nights with too little heart rate are excluded *before* splitting, so the
held-out pool that vdev plays is usable. Run ml.prep_sleep first.
"""

import json
import random
import sys
from datetime import date

from ml.paths import BIDMC, DALIA, MANIFEST, TRACKS

SEED = 2026
MIN_HR_COVERAGE = 0.80
DALIA_HOLDOUT = 5
BIDMC_HOLDOUT = 16
SLEEP_HOLDOUT_FRAC = 0.30


def split(ids: list[str], n_holdout: int, rng: random.Random) -> dict[str, list[str]]:
    shuffled = ids[:]
    rng.shuffle(shuffled)
    key = lambda s: int(s.lstrip("S"))  # noqa: E731
    return {
        "train": sorted(shuffled[n_holdout:], key=key),
        "holdout": sorted(shuffled[:n_holdout], key=key),
    }


def main() -> int:
    rng = random.Random(SEED)  # one stream; dataset order below is part of the split

    dalia = sorted(
        (p.name for p in DALIA.glob("S*") if p.is_dir()), key=lambda s: int(s[1:])
    )
    bidmc = sorted(p.name.split("_")[1] for p in BIDMC.glob("bidmc_*_Numerics.csv"))
    coverage = json.loads((TRACKS / "sleep" / "coverage.json").read_text())
    sleep_ok = [s for s, c in coverage.items() if c["hr_coverage"] >= MIN_HR_COVERAGE]
    excluded = [
        {"id": s, "reason": f"hr_coverage {c['hr_coverage']:.2f}"}
        for s, c in coverage.items()
        if c["hr_coverage"] < MIN_HR_COVERAGE
    ]
    assert len(dalia) == 15 and len(bidmc) == 53 and len(coverage) == 31

    manifest = {
        "seed": SEED,
        "created": date.today().isoformat(),
        "dalia": split(dalia, DALIA_HOLDOUT, rng),
        "sleep": {
            **split(
                sorted(sleep_ok, key=int),
                round(len(sleep_ok) * SLEEP_HOLDOUT_FRAC),
                rng,
            ),
            "excluded": excluded,
        },
        "bidmc": split(bidmc, BIDMC_HOLDOUT, rng),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    for name in ("dalia", "sleep", "bidmc"):
        m = manifest[name]
        print(
            f"{name}: train {len(m['train'])}, holdout {len(m['holdout'])}"
            f"{', excluded ' + str(len(m['excluded'])) if 'excluded' in m else ''}"
        )
        print("  holdout:", " ".join(m["holdout"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
