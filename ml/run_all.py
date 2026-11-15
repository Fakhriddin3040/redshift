"""The whole data and ML pipeline, in order. This is what deploy.sh runs.

    python -m ml.run_all            # skip the slow steps whose outputs exist
    python -m ml.run_all --force    # redo everything
    python -m ml.run_all --no-gate  # do not stop if the false-alarm check fails

Steps: get the datasets -> 1 Hz tracks -> split by person -> noise model ->
NASA profile and radiation seed -> context and sigma numbers -> windows ->
train XGBoost -> false-alarm check on the generator that will be deployed.

Outputs the application needs (all inside the repository tree, so the images
built afterwards contain them):
    ml/models/pattern.json                  pattern classifier
    vigil/vdev/assets/co2_iss_rr12.csv      ISS CO2 profile for the virtual device
    vigil/backend/seed/radiation_daily.csv  NASA radiation series
"""

import json
import subprocess
import sys
import time

from ml.paths import DATA, ML, SEED_DIR, TRACKS, VDEV_ASSETS

REQUIRED_OUTPUTS = [
    ML / "models" / "pattern.json",
    VDEV_ASSETS / "co2_iss_rr12.csv",
    SEED_DIR / "radiation_daily.csv",
]


def dalia_done() -> bool:
    d = TRACKS / "dalia"
    return all(
        (d / f"S{i}.parquet").exists() and (d / f"S{i}_ibi.parquet").exists()
        for i in range(1, 16)
    )


def sleep_done() -> bool:
    cov = TRACKS / "sleep" / "coverage.json"
    return cov.exists() and len(json.loads(cov.read_text())) == 31


def windows_done() -> bool:
    return all((DATA / "windows" / f"{n}.parquet").exists() for n in ("train", "test"))


# (module, extra args, "already done" check or None = always run)
STEPS = [
    ("ml.fetch_data", [], None),
    ("ml.prep_dalia", [], dalia_done),
    ("ml.prep_sleep", [], sleep_done),
    ("ml.split", [], None),
    ("ml.prep_bidmc", [], None),
    ("ml.prep_eda", [], None),
    ("ml.calc_context", [], None),
    ("ml.calc_sigma", [], None),
    ("ml.make_segments", [], None),
    ("ml.make_windows", [], windows_done),
    ("ml.train_xgb", [], None),
]
GATE = ("ml.eval_false_alarms", [])


def run(module: str, args: list[str]) -> int:
    started = time.monotonic()
    print(f"\n=== {module} {' '.join(args)}".rstrip(), flush=True)
    code = subprocess.run([sys.executable, "-m", module, *args]).returncode
    print(f"=== {module}: {'ok' if code == 0 else f'FAILED ({code})'}"
          f" in {time.monotonic() - started:.0f} s", flush=True)  # fmt: skip
    return code


def main(argv: list[str]) -> int:
    force, gate = "--force" in argv, "--no-gate" not in argv
    for module, args, done in STEPS:
        if done is not None and not force and done():
            print(
                f"\n=== {module}: outputs exist, skipped (use --force to redo)",
                flush=True,
            )
            continue
        if run(module, args) != 0:
            return 1

    missing = [str(p) for p in REQUIRED_OUTPUTS if not p.exists()]
    if missing:
        print("missing outputs:", ", ".join(missing))
        return 1

    if run(*GATE) != 0:
        print("\nFalse-alarm check failed: the generator raises alerts on normal data.")
        if gate:
            print(
                "Not deploying a stream that alarms by itself. Use --no-gate to override."
            )
            return 1
    print("\nPipeline finished: data prepared, model trained, checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
