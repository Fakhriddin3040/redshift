import math

import pytest

from vigil.core.features import FEATURES, features
from vigil.core.minute import Minute
from vigil.core.pattern_model import PatternModel
from vigil.core.pipeline import CrewState

MODEL_PATH = "ml/models/pattern.json"


def tiny_model() -> PatternModel:
    # One stump per class on spo2_z_min: below -3 -> class 1, else class 0; NaN -> class 0.
    i = FEATURES.index("spo2_z_min")
    return PatternModel(
        {
            "classes": ["normal", "hypoxia"],
            "features": list(FEATURES),
            "bias": [0.0, 0.0],
            "trees": [
                {"class": 0, "nodes": [[i, -3.0, 1, 2, 2], [-1, -2.0], [-1, 2.0]]},
                {"class": 1, "nodes": [[i, -3.0, 1, 2, 2], [-1, 2.0], [-1, -2.0]]},
            ],
        }
    )


def test_tree_walk_and_missing_values():
    model = tiny_model()
    x = [0.0] * len(FEATURES)
    assert model.predict(x)[0] == "normal"
    x[FEATURES.index("spo2_z_min")] = -5.0
    name, p = model.predict(x)
    assert name == "hypoxia" and p == pytest.approx(1 / (1 + math.exp(-4)))
    x[FEATURES.index("spo2_z_min")] = float("nan")
    assert model.predict(x)[0] == "normal"


def test_feature_list_must_match():
    with pytest.raises(ValueError):
        PatternModel({"classes": [], "features": ["x"], "bias": [], "trees": []})


def window(spo2: float) -> list:
    st = CrewState()
    return [
        st.on_minute(
            Minute(ts=600 + i * 60, hr=60.0, spo2=spo2, rr=14.0, skin_t=33.5,
                   co2_ppm=2700.0, press_hpa=1013.0, act_mg=20.0, sqi=90.0,
                   worn_frac=1.0, valid_s=60)
        )
        for i in range(10)
    ]  # fmt: skip


def test_features_have_the_declared_length_and_need_five_minutes():
    win = window(97.0)
    assert len(features(win)) == len(FEATURES) == 40
    assert features(win[:4]) is None


def test_trained_model_names_hypoxia():
    model = PatternModel.load(MODEL_PATH)
    if model is None:
        pytest.skip("no trained model in this checkout")
    assert model.predict(features(window(97.0)))[0] == "normal"
    name, p = model.predict(features(window(88.0)))
    assert name == "hypoxia" and p > 0.9
