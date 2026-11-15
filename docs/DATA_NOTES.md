# Vigil — data notes

Every number computed from the datasets, and how it was computed. Companion to `docs/DATA_PLAN.md` (task IDs C1–C9 refer to its §9).

- Computed on **2026-11-15**. Scripts live in `ml/` and were not yet committed when this was written (base commit `a6243a4`).
- Split: `ml/manifest.json`, seed 2026, by person. **Fitting uses train subjects only; accuracy is reported on held-out subjects only.**
- Machine-readable copies of the numbers: `ml/out/context.json`, `sigma.json`, `ar1.json`, `eda_stats.json`, `false_alarms.json`, `false_alarms_real_day.json`, `scenarios.json`, `xgb_report.json`.
- To rebuild everything from the raw data:

```
python -m ml.prep_dalia --plot     # 15 tracks + IBI files, ~2 min
python -m ml.prep_sleep            # 31 night tracks + coverage.json, ~3 min
python -m ml.split                 # ml/manifest.json
python -m ml.prep_bidmc            # C4
python -m ml.prep_eda              # CO2 profile + radiation seed
python -m ml.calc_context          # C1, C2, C3
python -m ml.calc_sigma            # C5
python -m ml.eval_false_alarms --seeds 3   # C7 (T2), ~3 min
python -m ml.eval_scenarios        # C8
python -m ml.make_windows          # windows for the classifier, ~5 min
python -m ml.train_xgb             # C9, writes ml/models/pattern.json
python -m ml.make_segments         # real daytime segments (§10)
```

---

## 0. What changed in `vigil/core`

Constants in `thresholds.py`:

| Constant | Was | Now | Why |
|---|---|---|---|
| `ACTIVE_ACT_MG` | 60 | **80** | C2: equal-error point of rest vs active minutes (DaLiA train) |
| `ACTIVE_COOLDOWN_S` | 300 | **180** | C3, §3.3 |
| `ACTIVE_COOLDOWN_MIN_RUN` | — | **2** (new) | C3: the cooldown starts only after 2 moving minutes in a row, or the exercise flag |
| `SLEEP_ACT_MG` | 8 | **12** | C3: chosen for the whole sleep rule, not for single minutes (their equal-error point is 8.1) |
| `SLEEP_NOISE_PENALTY` | — | **2** (new) | C3: a restless minute takes 2 off the quiet-minute count instead of resetting it |
| `SLEEP_HR_MARGIN` | 5 | **10** | C3 |
| `SLEEP_DEFAULT_REST_HR` | 60 | removed | without a learned resting HR the HR condition is skipped |
| `SIGMA_FLOOR["skin_t"]` | 0.3 | **0.5** | C5: 25th percentile of the resting σ across train subjects is 0.51 °C |
| `SIGMA_FLOOR["hr"]` | 3.0 | 3.0 | C5: 25th percentile in sleep, the quietest context, is 2.96 bpm |
| `SIGMA_FLOOR["hrv"]` | 8.0 | 8.0 (kept on purpose) | §5 |

Logic in `context.py` (`ContextTracker.classify`), described step by step in `docs/IMPLEMENTATION.md` §6.3:
- the cooldown after activity needs sustained movement (or the exercise flag);
- the sleep rule uses a count of quiet minutes that tolerates a restless minute;
- the HR condition for sleep applies only when the person's resting HR has been learned.

Result on held-out people (§3.2): DaLiA **88.0 %** (was 66.2 % before any change), sleep-accel **81–85 %** (was 33–46 %). Tests: 45 pass (5 new, 1 changed).

Generator constants for vdev (§4): SpO₂ φ 0.92, σ_ε 0.21; RR φ 0.96, σ_ε 0.32.

---

## 1. Splits and exclusions (`ml/split.py`)

| Dataset | Train | Held out | Excluded |
|---|---|---|---|
| PPG-DaLiA (15) | S2 S4 S5 S6 S7 S8 S9 S11 S13 S15 | S1 S3 S10 S12 S14 | — |
| sleep-accel (31) | 21 nights | 1066528 4018081 6220552 8000685 8258170 8530312 8692923 9106476 9961348 | 7749105 (`hr_coverage` 0.18) |
| BIDMC (53) | 37 records | 03 07 09 10 11 12 13 15 18 21 22 23 25 45 49 53 | — |

The sleep coverage filter (heart rate present in at least 80 % of the night, with at most 15 s carry-forward) runs before the split. Only one night fails it. The next lowest are 1066528 (91 %) and 2598705 (96 %).

Amount of data: DaLiA 36.0 h in total, **12.6 h held out**. Sleep-accel 226.8 h in total, 66.7 h held out.

---

## 2. Tracks

### 2.1 PPG-DaLiA (`ml/prep_dalia.py`)

Source: `S#.pkl` only. Activity codes were checked against `PPG_FieldStudy_readme.pdf` §II and match the table in `DATA_PLAN.md` §4.2.

| Subject | Split | Length, s | Rest HR (C1), bpm | Resting RMSSD (C6), ms | Accepted IBI |
|---|---|---|---|---|---|
| S1 | held out | 9212 | 67.9 | 55.8 | 96.5 % |
| S2 | train | 8205 | 75.6 | 35.2 | 99.4 % |
| S3 | held out | 8741 | 84.7 | 25.1 | 99.3 % |
| S4 | train | 9150 | 82.8 | 31.7 | 99.3 % |
| S5 | train | 9305 | 114.1 | 8.8 | 100.0 % |
| S6 | train | 5250 | 99.0 | 17.2 | 99.3 % |
| S7 | train | 9343 | 78.9 | 54.3 | 93.5 % |
| S8 | train | 8080 | 68.3 | 28.6 | 88.6 % |
| S9 | train | 8560 | 75.3 | 22.9 | 100.0 % |
| S10 | held out | 10648 | 78.6 | 15.6 | 96.6 % |
| S11 | train | 9048 | 92.3 | 25.1 | 99.3 % |
| S12 | held out | 7914 | 64.0 | 32.3 | 99.7 % |
| S13 | train | 9136 | 76.9 | 45.3 | 99.0 % |
| S14 | held out | 8958 | 80.3 | 43.8 | 94.4 % |
| S15 | train | 7939 | 67.9 | 33.7 | 99.3 % |

- **C1** (rest HR) = median of 1 Hz `hr` where `ctx_label = rest`. It is the `rest_donor` value for vdev re-normalization. S5 (114) and S6 (99) are unusually high for "rest"; both are real values from the ECG reference.
- **C6** (RMSSD) = median of the 5-min trailing RMSSD over resting seconds. The range is 9–56 ms and the median across subjects is 32 ms, so the crew profile range of 30–60 ms sits at the upper half of what this dataset shows. `hrv_rmssd_ms` is NaN for 3–10 % of each recording (the first 4 minutes, plus windows where too many beats were rejected).
- `hr` is NaN only in the first 4 s and the last few seconds (no extrapolation past the first and last 8-s window).
- S6 is short because of a hardware fault during recording (stated in the readme).
- S1 was checked by eye (`data/tracks/dalia/plots/S1.png`): heart rate rises on stairs, cycling and walking; `act_mg` is near 0 while sitting.

Two details the plan left open, and what the script does:
- **IBI rejection.** An interval is dropped if it is outside 300–2000 ms or differs from the previous accepted interval by more than 20 %. The reference interval is forgotten when it is more than 5 s old. Without this, one real change in heart rate after a gap would reject every later beat.
- **"80 % of expected beats"** for RMSSD is implemented as: the accepted intervals must cover at least 80 % of the 300-s window.

### 2.2 sleep-accel (`ml/prep_sleep.py`)

31 nights, 3.5–8.3 h each. `skin_t` and `hrv_rmssd_ms` are NaN (not in the dataset). Per-night statistics are in `data/tracks/sleep/coverage.json`.

Motion coverage is below 100 % on some nights (for example 83 % for 1066528, 86 % for 2598705); seconds with no accelerometer sample stay NaN.

---

## 3. Context: C2 thresholds and C3 accuracy (`ml/calc_context.py`)

Minutes are built with `vigil.core.minute.aggregate` (`ml/minutes.py`), with `sqi = 100` and `worn = 1` where `hr` is present. A minute gets a label only if at least 50 of its 60 seconds carry the same label; other minutes are skipped.

### 3.1 C2 — 1-min `act_mg` by class (train subjects)

| Class | n minutes | p5 | p25 | p50 | p75 | p95 |
|---|---|---|---|---|---|---|
| DaLiA rest | 704 | 7.2 | 17.1 | 27.0 | 52.2 | 91.2 |
| DaLiA active | 270 | 73.3 | 156.4 | 219.3 | 268.8 | 367.4 |
| sleep-accel asleep | 7422 | 1.2 | 2.1 | 3.2 | 5.4 | 8.8 |
| sleep-accel awake in bed | 549 | 1.8 | 3.0 | 6.8 | 12.6 | 48.9 |

By DaLiA activity (median `act_mg`): sitting 14, working 19, lunch 30, **driving 62**, table soccer 88, cycling 209, stairs 231, walking 236.

| Threshold | Equal-error point | Error at that point | Decision |
|---|---|---|---|
| `ACTIVE_ACT_MG` (rest vs active, DaLiA) | **80.2** | 7.4 % each way | 60 → 80 |
| `SLEEP_ACT_MG` (asleep vs DaLiA rest) | **8.1** | 7.1 % each way | 8 → 12, see §3.3 |

Caveats:
- The sleep threshold compares two different devices: Apple Watch (sleep-accel) and Empatica E4 (DaLiA).
- At the old threshold of 60, the median driving minute counted as "active".
- Cycling is not a problem in this dataset: wrist motion on the bike is high (median 209 mg), because the route was outdoors on gravel and paved roads.

### 3.2 C3 — accuracy of `ContextTracker.classify` on held-out subjects

With the rule and constants now in `vigil/core`. Minutes labelled `none` or mixed are ignored (695); 38 minutes the rule calls `off` are also ignored.

| Data | Minutes | Accuracy | Recall by class | Before any change |
|---|---|---|---|---|
| DaLiA (5 subjects) | 526 | **88.0 %** | rest 84.3 %, active 97.3 % | 66.2 % |
| sleep-accel (9 nights), cold start | 3498 | **84.9 %** | awake in bed 69.0 %, asleep 86.4 % | 32.5 % |
| sleep-accel, resting HR known | 3498 | **81.1 %** | awake in bed 69.3 %, asleep 82.3 % | 45.7 % |
| Combined, cold start | 4024 | **85.3 %** | rest 77.4 %, active 97.3 %, sleep 86.4 % | 38 % |
| Combined, resting HR known | 4024 | **82.0 %** | rest 77.6 %, active 97.3 %, sleep 82.3 % | 48.4 % |

**Target ≥ 85 %: met for daytime data (88 %) and for the combined set in a cold start (85.3 %); 82 % when the HR condition is active.** The weakest class is "awake in bed" (69 %): a person lying still is hard to tell from a sleeping one by wrist motion alone.

By DaLiA activity (held out): stairs 100 %, cycling 100 %, walking 100 %, sitting 98 %, lunch 86 %, table soccer 83 %, working 80 %, driving 76 %.

"Cold start" means no resting HR has been learned, so motion alone decides. "Resting HR known" means the rule is given the person's median heart rate while awake in bed, as a stand-in for the daytime resting HR that the backend would have learned; a night recording has no daytime data. This stand-in is rough, which is why the "known" row is lower.

For the Validity slide: "context rule, 88 % on 5 held-out people by day, 81–85 % on 9 held-out nights".

### 3.3 What was wrong with the first rule, and what was changed

The first rule (60 / 8, cooldown 300 s after any active minute, 15 quiet minutes strictly in a row, `hr ≤ rest + 5` with a default of 60) had three problems. All choices below were made on **train** subjects only.

1. **Cooldown.** One busy minute turned the next 5 rest minutes into `active`. Lunch, office work and driving contain single busy minutes. Now the cooldown is 3 minutes and starts only after 2 moving minutes in a row or the exercise flag. Train DaLiA accuracy: 76.3 % → 87.1 %; active recall 100 % → 98 %.
2. **The 15-minute run reset on one noisy minute.** 92 % of asleep minutes are at or below 8 mg, but 15 such minutes in a row are much rarer. Now a quiet minute adds 1 (up to 15), a restless minute takes 2 off, and only real movement resets the count. The quiet threshold is 12 mg.
3. **The HR condition rejected real sleep.** For 8 of 19 train nights the 90th percentile of heart rate while asleep is more than 5 bpm above the median while awake in bed, and many sleepers have a sleeping heart rate of 65–90 bpm, above the old default of 60 + 5. Now the margin is 10 bpm, and the condition is skipped until the resting HR is learned.

Train accuracy with the final rule: DaLiA 87.1 %, sleep 86.4 % (HR known) and 91.0 % (cold start).

Raising the quiet threshold to 12 mg did not turn any DaLiA rest minute into `sleep` on train, although sitting has a median of 14 mg. A looser rule (count allowed to run above 15, or a run of 10) gave up to 92 % on sleep but dropped "awake in bed" recall to about 55 %, so it was not taken.

Not measured: the effect on false alarms (C7). A shorter cooldown means a raised heart rate 4–5 minutes after unflagged movement is judged against the resting norm. In the simulator, exercise carries the `EXERCISE` flag until heart rate recovers, so the demo is not affected.

---

## 4. C4 — AR(1) for SpO₂ and respiratory rate (`ml/prep_bidmc.py`)

BIDMC numerics, 1 Hz, 8 min per record. Median over the 37 train records, using runs of at least 60 valid seconds.

| Metric | φ (median, IQR) | σ_ε (median, IQR) | Records fitted | PLAN §8.1 constants |
|---|---|---|---|---|
| SpO₂ | **0.916** (0.881–0.942) | **0.211** (0.172–0.265) | 31 of 37 (6 are constant) | φ 0.98, σ_ε 0.15 |
| RR | **0.959** (0.930–0.969) | **0.316** (0.243–0.384) | 37 of 37 | φ 0.95, σ_ε 0.40 |

Check on the 16 held-out records. Simulated series are 481 s long and rounded to integers, like the real data:

| Metric | Held-out real: std / lag-1 | Simulated, fitted params | Simulated, PLAN constants |
|---|---|---|---|
| SpO₂ | 0.47 / 0.913 | 0.59 / 0.748 | 0.71 / 0.881 |
| RR | 1.07 / 0.965 | 1.08 / 0.890 | 1.24 / 0.893 |

**Decision: the vdev generator uses the fitted values for both metrics** (`chosen_for_vdev` in `ml/out/ar1.json`; `PLAN.md` §8.1 is updated).

| Metric | φ | σ_ε | Long-run std of the generator | Real std (held out) |
|---|---|---|---|---|
| SpO₂ | 0.92 | 0.21 | 0.54 % | 0.47 % |
| RR | 0.96 | 0.32 | 1.14 breaths/min | 1.07 breaths/min |

- **RR:** the simulated std matches the held-out std (1.08 vs 1.07).
- **SpO₂:** the fitted parameters match the real spread; the PLAN constants (0.98 / 0.15) give a long-run std of 0.75 %, which is 60 % too wide and makes a false low-SpO₂ reading more likely. The PLAN constants match the lag-1 autocorrelation better (0.88 vs 0.75 against a real 0.91), but that number is distorted by integer quantization: 6 of 37 train records never change at all. For the demo, the spread matters more than the autocorrelation.
- The generator itself does not exist yet; it should read these two pairs.

RR vs HR across the 37 train records: slope 0.044 breaths/bpm, r = 0.15. That is weak, and half of our coupling parameter (0.08). These are ICU patients, so this is a sanity check only.

---

## 5. C5 — σ floors (`ml/calc_sigma.py`)

Per train subject, metric and context: σ = 1.4826 · MAD of the 1-min values. Cells with fewer than 10 minutes are skipped.

| Metric | Context | Subjects | p25 | p50 | p75 | Floor before |
|---|---|---|---|---|---|---|
| hr, bpm | sleep | 21 | 2.96 | 2.96 | 4.45 | 3.0 |
| hr, bpm | rest | 10 | 4.77 | 6.10 | 8.91 | 3.0 |
| hr, bpm | active | 10 | 10.17 | 15.19 | 16.74 | 3.0 |
| skin_t, °C | rest | 10 | 0.51 | 0.66 | 0.77 | 0.3 |
| skin_t, °C | active | 10 | 0.78 | 0.94 | 1.19 | 0.3 |
| hrv, ms | rest | 10 | 3.59 | 7.59 | 8.90 | 8.0 |
| hrv, ms | active | 10 | 4.39 | 4.92 | 6.00 | 8.0 |

`SIGMA_FLOOR` holds one value per metric, so the floor is taken from the quietest context.

- **hr: 3.0 confirmed** (sleep p25 = 2.96).
- **skin_t: 0.3 → 0.5.** Caveat: the DaLiA protocol moves between indoors and outdoors within 2.5 h, so wrist temperature drifts more than it would in a cabin. With the new floor, a Watch on skin temperature needs a shift of at least 1.0 °C instead of 0.6 °C. Re-check the fever scenario in the simulator.
- **hrv: stays at 8.0 (decided).** The 25th percentile suggests about 3.6 ms, but a check on the train subjects says not to lower it. Each person's resting minutes were scored against their own resting norm, counting runs of 5 minutes in a row with |z| ≥ 2 (a Watch):

  | Floor, ms | Watch-like runs in 11.2 resting hours | Minutes with \|z\| ≥ 2 |
  |---|---|---|
  | 8.0 | 6 | 8.1 % |
  | 6.0 | 6 | 9.3 % |
  | 5.0 | 7 | 9.7 % |
  | 3.6 | 7 | 10.3 % |

  HRV already produces the most Watch-like runs of any metric at the current floor, and a lower floor only adds more. The cause is that `hrv_rmssd_ms` is a 5-min trailing window, so neighbouring minutes share 80 % of their beats and a deviation easily lasts 5 minutes. This check is in-sample (the norm comes from the same 2.5 h), so the absolute count is pessimistic; the direction is what matters. If HRV alarms are too frequent in C7, the fix is a longer Watch run for HRV, not the floor.

---

## 6. NASA OSDR EDA (`ml/fetch_eda.py`, `ml/prep_eda.py`)

### 6.1 ISS cabin CO₂

ppCO₂ is computed at 1013.25 hPa with the backend's own formula. Values below 1000 ppm are removed. The 1-hour mean needs at least 30 valid minutes, like the backend.

| Mission | Period (UTC) | Points removed (< 1000 ppm) | ppCO₂ mean / max, mmHg | Highest 1-h mean | Hours with 1-h mean > 3.0 | Days with 1-h mean > 3.0 |
|---|---|---|---|---|---|---|
| RR-1 | 2014-09-20 … 2014-11-01 | 0 | 2.43 / 3.55 | 3.50 | 92.5 | 14 of 43 |
| RR-3 | 2016-04-06 … 2016-05-26 | 823 | 2.98 / 5.30 | 5.25 | 443.4 | 28 of 51 |
| RR-9 | 2018-08-14 … 2018-09-18 | 19 | 2.30 / 3.08 | 3.01 | 1.6 | 2 of 36 |
| **RR-12** | 2019-04-17 … 2019-05-28 | 1 | **2.04 / 2.79** | **2.77** | 0 | 0 of 42 |
| RR-19 | 2019-12-05 … 2020-01-09 | 1 | 1.95 / 2.72 | 2.68 | 0 | 0 of 36 |

These match the table in `DATA_PLAN.md` §3.1. No value is above 20 000 ppm and no 1-hour mean is above the 5.3 mmHg Alert limit.

`data/env/co2_profile.parquet` holds all five missions at a 1-min step (`t_min`, `co2_ppm`, `mission`); vdev should filter `mission == "RR-12"`. Gaps longer than 15 minutes stay NaN: 51 minutes for RR-12, 4163 minutes for RR-3.

`ml/fetch_eda.py` reproduces the files on disk exactly (checked for RR-12, both as one request and in one-week chunks). On 2026-11-15 the RR-6 response was complete in one request; the chunked path is kept for when it is truncated.

### 6.2 Radiation

`vigil/backend/seed/radiation_daily.csv` (`day,total,gcr,saa`, mGy/day) is built from `data/eda/RR-12_radiation.json`: 37 days, 2019-04-17 … 2019-05-23, total 0.333–0.417 mGy/day, mean 0.361. It is listed in `package-data`. The `/radiation` endpoint and the database import are not built yet (TASKS §4).

RadLab (D5) was not downloaded: the EDA series has a confirmed unit and is enough for the Radiation page.

---

## 7. C7 — false alarms on normal data (`ml/eval_false_alarms.py`)

The vdev generator (`vigil/vdev/signal.py`) is driven straight into `CrewState`: 21 days as history minutes, then 2 days as live seconds through the minute aggregator. Frames pass through `pack`/`unpack`, so values are quantized as on the wire. Incidents are counted from day 8, when the baseline is learned.

| Run | Person-days counted | Incidents | Watch / Alert / Critical | Per person-day |
|---|---|---|---|---|
| seed 0 | 105 | 0 | 0 / 0 / 0 | 0.00 |
| seed 1 | 105 | 0 | 0 / 0 / 0 | 0.00 |
| seed 2 | 105 | 0 | 0 / 0 / 0 | 0.00 |

**Target (zero Alert and Critical, at most one Watch per person-day): met.** This is with the final context rule and thresholds from §0. Share of minutes by context: sleep 32 %, rest 62 %, active 6 %.

For the Validity slide: "0 false alarms in 315 simulated person-days of normal data". The normal data is simulated; see §10 for what happens with real recordings.

Run it again after every change to the generator, the profiles or `thresholds.py`. The first version of the generator gave 4 Watch in 105 person-days (heart-rate noise too wide); the heart-rate noise was reduced.

How the generator keeps the baseline quiet (`docs/TASKS.md` §2.5):
- every signal is a slow part per minute plus per-second jitter with zero median; history minutes carry the slow part plus the noise that a 60-second median would have;
- heart rate steps to the sleep value in the 15th quiet minute, the same minute the context rule says `sleep`, and back in the minute motion returns;
- the `EXERCISE` flag stays set until heart rate is back within rest + 3 bpm;
- skin temperature is the same day and night;
- normal output is clamped away from the hard limits.

SpO₂ and breathing jitter use the AR(1) parameters from §4.

---

## 8. C8 — detection per scenario and severity (`ml/eval_scenarios.py`)

Ten normal days, then the scenario starts at 12:00 UTC (awake, at rest). The table gives the closed minute at which each level is first reached, over all 7 crew profiles. Minute values, no network; in the live stream add about one minute, because a minute closes when the next one starts.

| Scenario | Severity | Peak level | Watch at | Alert at | Critical at | Pattern named by the rule |
|---|---|---|---|---|---|---|
| hypoxia | 1 | Watch | 5 | — | — | hypoxia |
| hypoxia | 2 | Alert | 5 | 8 | — | hypoxia |
| hypoxia | 3 (default) | Critical | 5 | 8 | 12 | hypoxia |
| tachycardia_rest | 1, 2 | Alert | — | 3 | — | tachycardia_rest |
| tachycardia_rest | 3 | Critical | — | — | 1 | tachycardia_rest |
| bradycardia | 1, 2 | Alert | — | 3–4 | — | bradycardia |
| bradycardia | 3 | Critical | — | — | 1 | bradycardia |
| fever_like | 1 | Watch | 9–11 | — | — | fever_like |
| fever_like | 2 | Alert | — | 7–8 | — | fever_like |
| fever_like | 3 | Alert | — | 6 | — | fever_like |
| hypercapnia | 1 | Watch | 28 | — | — | hypercapnia |
| hypercapnia | 2 | Alert | 15 | 49 | — | hypercapnia |
| hypercapnia | 3 | Critical | 7 | 21 | 51 | hypercapnia |
| depressurization | 1 | Alert | — | 5 | — | depressurization |
| depressurization | 2 | Alert | — | 3 | — | depressurization |
| depressurization | 3 | Critical | — | 3 | 9 | depressurization |
| exercise, sensor_off, motion_artifact | any | none | — | — | — | — |

- Hypoxia is staged relative to each person's own SpO₂ mean, so all three levels appear for every profile. Checked live at ×60: levels 1, 2, 3 after about 5, 8 and 12 seconds.
- Hypercapnia is slow by design: the limit is a 1-hour mean.
- Exercise, a sensor that is taken off and a noisy sensor raise nothing. That is the intended result.
- With the skin-temperature floor of 0.5 °C (§5) the fever scenario is still detected.

---

## 9. C9 — pattern classifier (`ml/make_windows.py`, `ml/train_xgb.py`)

The detector decides that there is an alert; the classifier only names it. It reads 40 features of the last 10 minutes (`vigil/core/features.py`); vital signs enter as z-scores against the personal norm.

| | |
|---|---|
| Classes (8) | normal, hypoxia, tachycardia_rest, bradycardia, fever_like, hypercapnia, depressurization, sensor_artifact |
| Train | 77 479 windows: simulated crew 1–5, generator seeds 0–8 |
| Early stopping | 8 545 windows: crew 1–5, seed 9 |
| Test | 41 645 windows: crew 6, 7 and two more profiles (8, 9), seeds 100–105. No person and no seed is shared with training |
| Model | XGBoost, `multi:softprob`, depth 5, learning rate 0.1, subsample 0.8, colsample 0.8; stopped at 101 rounds |
| Label | a scenario covers at least 5 of the window's 10 minutes; windows with 1–4 scenario minutes are dropped |

Results on the test windows:

| Class | Recall | Precision | Windows |
|---|---|---|---|
| normal | 0.997 | 0.986 | 16 411 |
| hypoxia | 1.000 | 1.000 | 2 748 |
| tachycardia_rest | 0.997 | 1.000 | 2 967 |
| bradycardia | 0.923 | 0.986 | 2 692 |
| fever_like | 1.000 | 1.000 | 4 912 |
| hypercapnia | 1.000 | 1.000 | 6 011 |
| depressurization | 0.996 | 0.997 | 3 978 |
| sensor_artifact | 1.000 | 1.000 | 1 926 |

**Accuracy 0.993, macro-F1 0.993.** On the windows where the detector has an alert open (22 661), accuracy is 0.997. The weakest class is bradycardia at severity 1: 207 of 2 692 windows are called normal, because a heart rate of 47 bpm is close to a normal sleeping value.

**What this number means.** The abnormal classes are produced by our own simulator, and the model is tested on the same kind of simulated deviation, on other simulated people. So 0.99 says that the classes are easy to tell apart **as we modelled them**. It says nothing about real patients. Say this on the slide.

In the backend (`hub._name_pattern`): the model is asked only when an incident is open; if it answers a class other than `normal` with probability at least 0.5, the incident gets that `pattern` and `p`; otherwise the rule's name stays. The model never raises a level. The backend does not need the xgboost package: `ml/train_xgb.py` exports the trees to `ml/models/pattern.json` (322 KB) and `vigil/core/pattern_model.py` walks them; the largest difference from XGBoost's own margins on 2 000 test windows is 3·10⁻⁶.

---

## 10. T4 — real PPG-DaLiA segments in the daytime stream: tried, not enabled

`ml/make_segments.py` cuts the 5 held-out DaLiA subjects into 20 segments labelled `rest` (376 minutes, 6.3 h). The generator can replay them for awake time outside exercise (`Fleet(seed, real_day=True)`): heart rate is re-scaled to the crew member, `hr = rest_crew + k · (hr_donor − rest_donor)`, and wrist motion is taken as recorded.

| Stream | Incidents per person-day | Watch / Alert / Critical in 105 person-days |
|---|---|---|
| Simulated (default) | 0.00 | 0 / 0 / 0 |
| Real segments, k = 0.6 | 8.65 | 67 / 841 / 0 |
| Real segments, k = 0.3 | 4.09 | 215 / 214 / 0 |

**The gate in `docs/TASKS.md` (T2 must still pass) is not met, so the demo stream stays simulated.** `python -m ml.eval_false_alarms --real-day` reproduces the table.

Why: in the real recordings, "rest" covers sitting, office work, lunch and driving, and heart rate differs between them by 10–20 bpm for many minutes at a time (5th–95th percentile of `hr_rel`: −21 to +12 bpm). The personal norm has one cell per context and time of day, learns only values within 2.5 σ, and so stays narrow; every long stretch of a different activity is then outside it. Almost all incidents are named bradycardia or tachycardia_rest.

This is a finding about the detector, not about the data: on real daily life, one "rest" norm for heart rate is too coarse. Making it work needs a wider or multi-level heart-rate norm, or a longer Watch run for heart rate; neither was done.

What can be claimed (`docs/TASKS.md` §5): "simulated vital signs with parameters taken from open datasets". Real recordings are used to fit and test the context rule (§3) and the noise model (§4), and the cabin CO₂ and the radiation dose are real NASA data.

---

## 11. C10 — language model for the alert explanation (`ml/llm_dataset.py`, `ml/llm_eval.py`)

The model writes only the "why" sentence of an alert that the rules have already raised. The title and the steps stay with the template and `docs/actions.yaml`. Its answer is shown only if it passes an automatic check (`vigil/llm/explain.py`): every number must appear in the summary it was given, no other pattern may be named, and the length must be within limits. Anything else leaves the template text in place.

Validation set: 141 alert summaries from the simulator (10 % of 1 412; six incident scenarios × random severity × 7 crew profiles × 8 seeds, one summary each time an alert reaches a new level). The model is asked exactly as the backend asks it.

| Model (2026-11-15) | Answers accepted | Median response | 95th percentile |
|---|---|---|---|
| `deepseek-flash` through the DeepSeek API, reasoning mode off, answer limited to 120 tokens | **141 of 141 (100 %)** | 1.2 s | 3.5 s |
| same model, reasoning mode on, 200-token limit | 21 of 36 (58 %) | 2.0 s | 3.6 s |

**Rule from the plan (at least 98 % accepted): met**, so the model may be used.

Why the second row failed: with reasoning on, the hidden reasoning used up the token limit and 15 of 36 answers came back empty or cut off. Two changes followed, neither specific to a provider: a reply cut off by the token limit is now treated as an error (a half sentence is never shown), and extra request fields can be set with `LLM_EXTRA_BODY`. For this provider it is `{"thinking": {"type": "disabled"}}`.

Cost per request with these settings, measured over the 141 requests: 187 prompt tokens and 39 answer tokens on average, about 226 in total. Three limits keep spending bounded:

| Limit | Value in the deployment | Effect |
|---|---|---|
| `LLM_MAX_TOKENS` | 120 | an answer that does not fit is dropped and the template is shown |
| `LLM_MAX_CALLS_PER_HOUR` | 30 (default) | further alerts in that hour keep the template text |
| one request per alert level | built in | an alert asks at most three times (Watch, Alert, Critical), never every minute |

So the live application cannot spend more than about 30 × 226 ≈ 6 800 tokens per hour. `GET /api/v1/health` shows the running totals in `llm_usage`. `ml/llm_eval.py` and `ml/llm_dataset.py --teacher provider` are batch runs started by a person and are not capped.

What "accepted" does and does not mean: it means no number was invented and no other pattern was named. It does not measure how well the sentence reads; a person should read a sample before the demo. No fine-tuning was run; the provider's model is used as it is. `ml/finetune_llm.py` exists for a self-hosted model and has not been run.

The provider receives the alert summary only: readings, ranges, level, context. No names, ids or timestamps.
