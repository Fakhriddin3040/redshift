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
| Alert title and the suggested steps | **Not AI.** Templates | The numbers come from the alert itself; the steps come from `docs/actions.yaml`, which is written by people (`vigil/backend/narrate.py`) |
| The "why" sentence of an alert | **Language model** (see below which one). Without `LLM_BASE_URL` and `LLM_MODEL` it is a template | When configured, any OpenAI-compatible model writes one or two sentences from a summary of the alert (no names, no ids). The answer is used only if every number in it is in the summary; otherwise the template stays. The model never decides that there is an alert and never chooses the steps (`vigil/llm/`) |
| Ask Vigil: answers to a crew member's questions about their own record | **Language model**, the same one. Hidden when no model is configured | The model is sent that one person's record: current readings and usual ranges, the last hour, alerts of the last 24 hours with their text, sleep, whether the check-in is filed. No name and no id; the question itself is sent as typed. The answer is shown only if every number in it is in the record or in the question and it names no alert pattern that the record does not contain; otherwise a fixed sentence is shown. The model is told not to diagnose or advise, but this is not checked automatically (`vigil/llm/ask.py`) |
| Vital signs in the demo | Simulated by a generator, not by a model | `vigil/vdev/signal.py`. Noise parameters are fitted on open datasets (`docs/DATA_NOTES.md`) |

**Language model in the deployed demo (from 2026-11-15):** `deepseek-flash` through the DeepSeek API, with its reasoning mode switched off. It is used as the provider ships it; nothing was fine-tuned. It receives a summary of the alert (readings, ranges, level, context — no names or ids) and writes one or two sentences. On 141 validation alerts all 141 answers passed the automatic check (`docs/DATA_NOTES.md` §11). Ask Vigil uses the same model; how often its answers pass their check has not been measured yet.

The integration itself names no provider: the model is chosen by the `LLM_*` variables of the deployment. If they change, update this paragraph. The fine-tuning scripts (`ml/llm_dataset.py`, `ml/finetune_llm.py`) exist but training has not been run; a dataset made with `--teacher provider` would be AI-generated data and must be listed here.

## What we do not claim

- Vigil is a prototype and not a medical device.
- It was not trained on astronaut data. The abnormal episodes in the demo are simulated.
- The cabin CO₂ and the radiation dose are real ISS measurements from NASA OSDR; the crew's vital signs are not.
