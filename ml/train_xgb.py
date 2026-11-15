"""ML-3 / C9: train the pattern classifier and export it for the backend (PLAN §10).
Writes ml/models/pattern.json and ml/out/xgb_report.json.

    python -m ml.train_xgb

Train: windows from ml/make_windows.py (train people and seeds), with one seed held
back for early stopping. Report: windows from other people and other seeds.
The exported trees are checked against XGBoost's own probabilities.
"""

import json
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

from ml.make_windows import CLASSES, OUT_DIR
from ml.paths import ML, OUT
from vigil.core.features import FEATURES
from vigil.core.pattern_model import PatternModel

MODEL_PATH = ML / "models" / "pattern.json"
PARAMS = dict(
    objective="multi:softprob", num_class=len(CLASSES), max_depth=5, eta=0.1,
    subsample=0.8, colsample_bytree=0.8, eval_metric="mlogloss", seed=2026,
)  # fmt: skip
MAX_ROUNDS, EARLY_STOP = 300, 20
VALID_SEED = 9  # generator seed kept out of training, used for early stopping


def flatten(tree: dict) -> list[list[float]]:
    """One tree of XGBoost's saved model -> node list [feature, threshold, yes, no, missing]
    or [-1, leaf value]. The saved model keeps thresholds at full float32 precision."""
    nodes = []
    for i, left in enumerate(tree["left_children"]):
        if left == -1:
            nodes.append([-1, tree["split_conditions"][i]])
        else:
            right = tree["right_children"][i]
            nodes.append([tree["split_indices"][i], tree["split_conditions"][i], left,
                          right, left if tree["default_left"][i] else right])  # fmt: skip
    return nodes


def export(booster: xgb.Booster, sample: np.ndarray, meta: dict) -> PatternModel:
    saved = json.loads(booster.save_raw("json"))["learner"]["gradient_booster"]["model"]
    trees = [
        {"class": cls, "nodes": flatten(t)}
        for t, cls in zip(saved["trees"], saved["tree_info"], strict=True)
    ]
    data = {"classes": CLASSES, "features": list(FEATURES),
            "bias": [0.0] * len(CLASSES), "trees": trees, "meta": meta}  # fmt: skip
    # The constant XGBoost adds to every margin: measured, not read from its config.
    ref = booster.predict(xgb.DMatrix(sample[:50]), output_margin=True)
    mine = np.array([PatternModel(data).margins(list(row)) for row in sample[:50]])
    data["bias"] = [round(float(b), 6) for b in (ref - mine).mean(axis=0)]
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(data, separators=(",", ":")))
    return PatternModel(data)


def main() -> int:
    train = pd.read_parquet(OUT_DIR / "train.parquet")
    test = pd.read_parquet(OUT_DIR / "test.parquet")
    cols = list(FEATURES)
    y = lambda df: df["label"].map(CLASSES.index).to_numpy()  # noqa: E731
    fit, valid = train[train["seed"] != VALID_SEED], train[train["seed"] == VALID_SEED]

    dfit = xgb.DMatrix(fit[cols].to_numpy(), label=y(fit))
    dvalid = xgb.DMatrix(valid[cols].to_numpy(), label=y(valid))
    booster = xgb.train(
        PARAMS, dfit, MAX_ROUNDS, evals=[(dvalid, "valid")],
        early_stopping_rounds=EARLY_STOP, verbose_eval=False,
    )  # fmt: skip
    best = booster.best_iteration + 1
    booster = booster[:best]

    x_test = test[cols].to_numpy()
    proba = booster.predict(xgb.DMatrix(x_test))
    pred, true = proba.argmax(axis=1), y(test)

    n = len(CLASSES)
    confusion = np.zeros((n, n), dtype=int)
    for t, p in zip(true, pred, strict=True):
        confusion[t, p] += 1
    recall = confusion.diagonal() / confusion.sum(axis=1)
    precision = confusion.diagonal() / np.maximum(confusion.sum(axis=0), 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)

    # The backend names a pattern only for an open incident (level > 0).
    alarmed = (test["level"] > 0).to_numpy()
    acc_alarmed = float((pred[alarmed] == true[alarmed]).mean())

    meta = {"rounds": best, "params": PARAMS, "trained_on": len(fit),
            "macro_f1_test": round(float(f1.mean()), 4)}  # fmt: skip
    model = export(booster, x_test, meta)
    check = np.array([model.margins(list(row)) for row in x_test[:2000]])
    ref = booster.predict(xgb.DMatrix(x_test[:2000]), output_margin=True)
    parity = float(np.abs(check - ref).max())
    assert parity < 1e-3, f"exported trees disagree with XGBoost by {parity}"

    gain = booster.get_score(importance_type="gain")
    top = sorted(((FEATURES[int(k[1:])], round(v, 1)) for k, v in gain.items()),
                 key=lambda kv: -kv[1])[:10]  # fmt: skip
    report = {
        "train_windows": len(fit),
        "valid_windows": len(valid),
        "test_windows": len(test),
        "train_people": sorted(int(c) for c in train["crew"].unique()),
        "test_people": sorted(int(c) for c in test["crew"].unique()),
        "rounds": best,
        "params": PARAMS,
        "accuracy": round(float((pred == true).mean()), 4),
        "macro_f1": round(float(f1.mean()), 4),
        "accuracy_when_level_above_0": round(acc_alarmed, 4),
        "windows_with_level_above_0": int(alarmed.sum()),
        "per_class": {
            c: {
                "recall": round(float(recall[i]), 4),
                "precision": round(float(precision[i]), 4),
                "f1": round(float(f1[i]), 4),
                "n": int(confusion[i].sum()),
            }
            for i, c in enumerate(CLASSES)
        },
        "confusion_rows_true_cols_pred": {
            "classes": CLASSES,
            "matrix": confusion.tolist(),
        },
        "top_features_by_gain": top,
        "export_max_margin_diff": parity,
        "model_bytes": MODEL_PATH.stat().st_size,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "xgb_report.json").write_text(json.dumps(report, indent=2) + "\n")

    print(
        f"rounds {best} | accuracy {report['accuracy']} | macro-F1 {report['macro_f1']}"
        f" | accuracy on windows with level > 0: {report['accuracy_when_level_above_0']}"
        f" ({report['windows_with_level_above_0']} windows)"
    )
    for c, v in report["per_class"].items():
        print(
            f"  {c:<18} recall {v['recall']:.3f}  precision {v['precision']:.3f}  n {v['n']}"
        )
    print("confusion (rows = true, cols = predicted):", CLASSES)
    print(confusion)
    print("top features:", top)
    print(f"export parity {parity:.2e}, model {report['model_bytes'] / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
