"""Pattern classifier at run time: gradient-boosted trees evaluated in plain Python.

ml/train_xgb.py trains with XGBoost and exports the trees to ml/models/pattern.json.
Reading that file here keeps xgboost out of the backend image, and the training
script checks that this evaluator gives the same probabilities as XGBoost.
"""

import json
import math
from pathlib import Path

import numpy as np

from vigil.core.features import FEATURES


class PatternModel:
    def __init__(self, data: dict) -> None:
        if data["features"] != list(FEATURES):
            raise ValueError("model was trained on a different feature list")
        self.classes: list[str] = data["classes"]
        self.bias: list[float] = data["bias"]
        # tree = flat node list; node = [feature, threshold, yes, no, missing] or [-1, leaf]
        # Thresholds are float32 in XGBoost; their decimal form in JSON is not exact.
        self.trees: list[tuple[int, list[list[float]]]] = [
            (
                t["class"],
                [
                    n if n[0] < 0 else [n[0], float(np.float32(n[1])), *n[2:]]
                    for n in t["nodes"]
                ],
            )
            for t in data["trees"]
        ]
        self.meta: dict = data.get("meta", {})

    @classmethod
    def load(cls, path: str) -> PatternModel | None:
        file = Path(path)
        if not file.is_file():
            return None
        return cls(json.loads(file.read_text()))

    def margins(self, x: list[float]) -> list[float]:
        # XGBoost compares float32 values; do the same so borderline splits agree.
        x = np.asarray(x, dtype=np.float32).tolist()
        out = list(self.bias)
        for cls, nodes in self.trees:
            node = nodes[0]
            while node[0] >= 0:
                value = x[int(node[0])]
                if value != value:  # NaN
                    nxt = node[4]
                else:
                    nxt = node[2] if value < node[1] else node[3]
                node = nodes[int(nxt)]
            out[cls] += node[1]
        return out

    def predict(self, x: list[float]) -> tuple[str, float]:
        """(class name, probability) of the most likely class."""
        m = self.margins(x)
        top = max(m)
        exp = [math.exp(v - top) for v in m]
        best = max(range(len(exp)), key=exp.__getitem__)
        return self.classes[best], exp[best] / sum(exp)
