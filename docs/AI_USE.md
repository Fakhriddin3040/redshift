# Vigil — use of AI

This file lists every place where an AI tool was used in this project, and where it was not.

## In building the project

| Tool | Used for | Checked by |
|---|---|---|
| Claude Code (Anthropic), an AI coding assistant | Parts of the code in `vigil/`, `ml/` and `client/`, the tests, and parts of the documentation in `docs/` and this README. It also ran the data preparation and the evaluations and wrote their results into `docs/DATA_NOTES.md` | The team reviewed the changes; the numbers in `docs/DATA_NOTES.md` are reproduced by the scripts named next to them |

Design tools used by the designers: **to be filled in by the team before submission.**

## In the product itself

| Part | AI or not | Detail |
|---|---|---|
| Detecting that something is wrong | **Not AI.** Rules and statistics | A personal norm per crew member (median and robust spread of their own readings), fixed medical limits (NEWS2-style), and the NASA-STD-3001 cabin CO₂ limit. See `docs/IMPLEMENTATION.md` |
| Naming the pattern ("low blood oxygen", …) | **Machine learning.** A gradient-boosted tree classifier (XGBoost) reads 40 features of the last 10 minutes and names the pattern of an alert that the rules have already raised. It never raises or lowers an alert. If it is unsure, a simple rule names the pattern | Trained by `ml/train_xgb.py` on windows from our own simulator; the abnormal classes are simulated. `vigil/core/pattern_model.py`, `vigil/core/pipeline.py` (`rule_pattern`) |
| Alert text and the suggested steps | **Not AI.** Templates | The numbers come from the alert itself; the steps come from `docs/actions.yaml`, which is written by people (`vigil/backend/narrate.py`) |
| Vital signs in the demo | Simulated by a generator, not by a model | `vigil/vdev/signal.py`. Noise parameters are fitted on open datasets (`docs/DATA_NOTES.md`) |

No language model runs in the product. The only trained model is the pattern classifier above. If that changes, this file must be updated before the claim is made anywhere else.

## What we do not claim

- Vigil is a prototype and not a medical device.
- It was not trained on astronaut data. The abnormal episodes in the demo are simulated.
- The cabin CO₂ and the radiation dose are real ISS measurements from NASA OSDR; the crew's vital signs are not.
