"""All dataset locations in one place (docs/DATA_PLAN.md §1). Raw folders keep their names."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DALIA = DATA / "ppg+dalia/data/PPG_FieldStudy"
BIDMC = (
    DATA
    / "bidmc-ppg-and-respiration-dataset-1.0.0/bidmc-ppg-and-respiration-dataset-1.0.0/bidmc_csv"
)
SLEEP = (
    DATA
    / "sleep-accel-1.0.0/motion-and-heart-rate-from-a-wrist-worn-wearable-and-labeled-sleep-from-polysomnography-1.0.0"
)
EDA = DATA / "eda"
RADLAB = DATA / "radlab"
TRACKS = DATA / "tracks"  # processed 1 Hz tracks
ENV = DATA / "env"  # processed cabin profiles

ML = ROOT / "ml"
OUT = ML / "out"  # small derived JSON, committed
MANIFEST = ML / "manifest.json"
SEED_DIR = ROOT / "vigil/backend/seed"
VDEV_ASSETS = ROOT / "vigil/vdev/assets"
