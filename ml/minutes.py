"""1 Hz track -> backend minutes, using the backend's own aggregation
(docs/DATA_PLAN.md §9: import vigil.core.minute, don't re-implement it).

Offline data has no signal quality or wear sensor, so sqi = 100 and worn = 1
wherever hr is not NaN, and sqi = 0 / worn = 0 elsewhere.
"""

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.paths import MANIFEST, TRACKS
from vigil.core.frame import Flag, Frame, FrameType
from vigil.core.minute import Minute, aggregate

MIN_LABEL_SECONDS = 50  # a minute gets a label only if >= 50 of its 60 s agree


@dataclass(slots=True)
class LabeledMinute:
    minute: Minute
    label: str  # rest / active / sleep / none / mixed
    act_code: int  # raw activity or sleep-stage code, -1 if mixed


def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def load_track(src: str, subject: str) -> pd.DataFrame:
    return pd.read_parquet(TRACKS / src / f"{subject}.parquet")


def _opt(x: float) -> float | None:
    return None if np.isnan(x) else float(x)


def to_minutes(track: pd.DataFrame) -> list[LabeledMinute]:
    hr = track["hr"].to_numpy(dtype=np.float64)
    act = track["act_mg"].to_numpy(dtype=np.float64)
    skin = track["skin_t"].to_numpy(dtype=np.float64)
    hrv = track["hrv_rmssd_ms"].to_numpy(dtype=np.float64)
    label = track["ctx_label"].astype(str).to_numpy()
    code = track["act_code"].to_numpy()

    out = []
    for start in range(0, len(track) - 59, 60):  # whole minutes only
        frames = []
        for i in range(start, start + 60):
            worn = not np.isnan(hr[i])
            frames.append(
                Frame(
                    type=FrameType.SECOND,
                    dev_id=0,
                    ts=i,
                    hr=_opt(hr[i]),
                    skin_t=_opt(skin[i]),
                    act_mg=_opt(act[i]),
                    hrv=_opt(hrv[i]),
                    sqi=100 if worn else 0,
                    flags=Flag.WORN if worn else 0,
                )
            )
        values, counts = np.unique(code[start : start + 60], return_counts=True)
        top = counts.argmax()
        if counts[top] >= MIN_LABEL_SECONDS:
            minute_label, minute_code = (
                label[start + int(np.argmax(code[start : start + 60] == values[top]))],
                int(values[top]),
            )
        else:
            minute_label, minute_code = "mixed", -1
        out.append(LabeledMinute(aggregate(start, frames), minute_label, minute_code))
    return out
