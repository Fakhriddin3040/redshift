# Vigil — data plan

What to download, how to prepare each dataset, what to compute from it, and where the results go.
Companion to `PLAN.md` §5–§6 and §8. Task IDs (DS-*, DP-*, SIM-*, C1–C10) refer to `PLAN.md`.

Markers: **[verified]** — checked against the files on disk on 2026-11-14; **[check]** — confirm before relying on it; **[param]** — our engineering assumption.

---

## 0. TL;DR

| # | Do | Who | Priority |
|---|---|---|---|
| 1 | ~~Export ISS cabin CO₂ from NASA OSDR EDA~~ **done 2026-11-14** via the EDA API → `data/eda/` (§3.1). Wrap it in `ml/fetch_eda.py` so it is reproducible | EMB | P5 |
| 2 | Radiation: use the EDA daily dose already in `data/eda/RR-12_radiation.json` (unit verified, §3.1). RadLab is optional; its unit is still unconfirmed (§3.2) | EMB | P6 |
| 3 | Fix `.gitignore` so `manifest.json` can be committed (§2.3) | BE | now |
| 4 | `ml/prep_dalia.py` → 15 × 1 Hz parquet tracks | ML | P20 |
| 5 | `ml/split.py` → `ml/manifest.json` (split by subject, fixed seed) | ML | P21 |
| 6 | C1, C2, C3 → `docs/DATA_NOTES.md` + update `vigil/core/thresholds.py` | ML | P22 |
| 7 | `ml/prep_bidmc.py` → AR(1) params for SpO₂/RR (C4) | ML | P88 (quick, do early) |
| 8 | `ml/prep_sleep.py` → real nights | ML | P80 |
| 9 | `ml/prep_eda.py` → CO₂ profile for the simulator | EMB | P35 |
| 10 | `docs/DATA_LICENSES.md` (§9) | D2 | P8 |

Nothing else needs downloading. Skip MIMIC-III (optional P111), WESAD (license), OpenOximetry (restricted).

---

## 1. Inventory

| ID | Dataset | On disk | Size | Status |
|---|---|---|---|---|
| D1 | PPG-DaLiA | `data/ppg+dalia/data/PPG_FieldStudy/S1…S15/` | 26 GB extracted | ✅ |
| D2 | BIDMC | `data/bidmc-ppg-and-respiration-dataset-1.0.0/bidmc-ppg-and-respiration-dataset-1.0.0/bidmc_csv/` | 209 MB | ✅ |
| D3 | sleep-accel | `data/sleep-accel-1.0.0/motion-and-heart-rate-from-a-wrist-worn-wearable-and-labeled-sleep-from-polysomnography-1.0.0/` | 2.2 GB | ✅ |
| D4 | NASA OSDR EDA — ISS cabin CO₂ | `data/eda/RR-{1,3,9,12,19}_co2_iss.json` | 2.8 MB | ✅ (§3.1) |
| D5 | NASA OSDR RadLab — ISS absorbed dose | — | small | ❌ **download (§3.2)** |

Raw folder names are long. Don't rename them. Put all paths in one place, `ml/paths.py`:

```python
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
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
TRACKS = DATA / "tracks"  # processed output
```

ML dependencies (dev group, not the backend image): `uv add --group ml numpy pandas pyarrow`. Add `xgboost` later, for ML-3.

---

## 2. Outputs and layout

### 2.1 Processed files

```
data/                         # gitignored
  eda/<mission>_telemetry.csv     raw export + eda/SOURCE.txt (URL, date, units)
  radlab/iss_<YYYY-MM-DD>.csv     raw API responses, one per day
  tracks/
    dalia/S1.parquet … S15.parquet      1 Hz track
    dalia/S1_ibi.parquet …              beat-to-beat intervals (for HRV)
    sleep/<subject_id>.parquet          1 Hz night track
  env/co2_profile.parquet               1-min ISS CO₂ profile for vdev
ml/
  manifest.json                   split + exclusions (committed)
  paths.py, prep_*.py, split.py, calc_*.py, fetch_radlab.py
docs/
  DATA_NOTES.md                   every computed number + how it was computed (committed)
  DATA_LICENSES.md
vigil/backend/seed/radiation_daily.csv   small derived NASA file, committed so the demo works offline
```

### 2.2 Unified 1 Hz track schema (PLAN §6.1)

| Column | Type | Meaning | Missing |
|---|---|---|---|
| `subj` | str | `dalia:S3`, `sleep:1066528` | — |
| `t` | int32 | seconds from start of recording | — |
| `hr` | float32 | bpm | NaN |
| `act_mg` | float32 | mean over the second of `abs(‖a‖ − 1 g) · 1000` | NaN |
| `skin_t` | float32 | °C, wrist | NaN (sleep-accel has none) |
| `ctx_label` | category | `rest` / `active` / `sleep` / `none` | `none` |
| `act_code` | int8 | raw activity / sleep-stage code | -1 |
| `hrv_rmssd_ms` | float32 | 5-min trailing RMSSD (DaLiA only) | NaN |
| `src` | category | `dalia` / `sleep` | — |

Missing data stays NaN. Never fill a gap with 0 or with an old value beyond the limits below. This is the "a gap stays a gap" principle.

### 2.3 Fix: the manifest must be committed

`.gitignore` currently ignores the whole `data/` directory. That means `data/manifest.json` (PLAN §6.2) can never be committed, but DP-2 requires it in the repo. **Put it at `ml/manifest.json`.** That is simpler than adding exceptions to `.gitignore`.

---

## 3. Downloads still needed

### 3.1 D4 — ISS cabin CO₂ from the OSDR EDA API — done

EDA has a public JSON API with no key **[verified 2026-11-14]**. Docs: https://visualization.osdr.nasa.gov/eda/api_reference

| Endpoint | Returns |
|---|---|
| `GET /eda/api/missions/` | list of missions |
| `GET /eda/api/missions/{m}/co2/iss/` | **what we use**: `[{"time": "2014-09-20T03:59:00Z", "co2_iss": 2641.0}, …]` |
| `GET /eda/api/missions/{m}/co2/` | ISS + ground control |
| `GET /eda/api/missions/{m}/telemetry_data/` | temperature, RH, CO₂ (ISS + ground) |
| `GET /eda/api/missions/{m}/{gcr\|saa\|total}/` | radiation per mission (an alternative to RadLab) |
| `?start=YYYY-MM-DDTHH:MM:SSZ&end=…` | date filter on any time-series endpoint |

Base URL: `https://visualization.osdr.nasa.gov`. Missions: RR-1, RR-3…RR-9, RR-12, RR-17, RR-18, RR-19, RR-23, APEX-03-1/2, APEX-04, VEG-01A/B/C.

What was downloaded, and what it contains (unit **ppm**, UTC, **5-min step**):

| Mission | Days | Points | ppm median / max | ppCO₂ median / max (mmHg @ 1013 hPa) | Points > 3 mmHg |
|---|---|---|---|---|---|
| RR-1 (2014) | 41 | 12 087 | 3192 / 4667 | 2.43 / 3.55 | 1 096 |
| RR-3 (2016) | 49 | 14 385 | 3638 / 6977 | 2.76 / 5.30 | 5 310 |
| RR-9 (2018) | 34 | 10 079 | 3203 / 4051 | 2.43 / 3.08 | 27 |
| RR-12 (2019) | 40 | 11 785 | 2675 / 3668 | 2.03 / 2.79 | 0 |
| RR-19 (2019) | 35 | 10 193 | 2516 / 3581 | 1.91 / 2.72 | 0 |

Notes:
- **RR-6 and RR-23 responses come back truncated** (invalid JSON). Fetch them in chunks with `start`/`end` (one week per request), or skip them.
- **RR-3 really goes above NASA's 3 mmHg / 1-hour limit.** Its highest single reading is 5.30 mmHg and its highest 1-hour mean is 5.25, so it reaches Watch but not the 5.3 Alert limit. This is a good real-data episode for a slide.
- The minimums (128–500 ppm) are implausible for ISS air and are most likely sensor glitches or calibration events. Set values below **1000 ppm** to NaN and record how many in `DATA_NOTES.md`.
- EDA describes these values as ISS cabin measurements taken alongside the Rodent Research hardware. Wording for the deck: "ISS cabin CO₂ telemetry, NASA OSDR EDA (RR-1…RR-19)".

`ml/fetch_eda.py` (to make this reproducible): loop over missions, fetch `co2/iss/` in one-week chunks, merge, drop duplicate timestamps, and write `data/eda/<m>_co2_iss.json` + `SOURCE.txt`.

**Which mission to play in the simulator** (checked 2026-11-15, values below 1000 ppm removed, 1-hour rolling mean at 1013.25 hPa):

| Mission | Highest 1-h mean ppCO₂ | Days with a 1-h mean above 3.0 mmHg | Use |
|---|---|---|---|
| RR-12 | 2.77 | 0 of 42 | **normal cabin profile** |
| RR-19 | 2.68 | 0 of 36 | spare normal profile |
| RR-9 | 3.01 | 2 of 36 | avoid: its CO₂ is dated 2018 but its radiation 2017 |
| RR-1 | 3.50 | 14 of 43 | not as the normal profile: the whole crew would sit on Watch |
| RR-3 | 5.25 | 28 of 51 | real high-CO₂ episode for a slide; never above the 5.3 Alert limit |

**EDA also has daily radiation dose**, and it is the better source for the Radiation page: `GET /eda/api/missions/{m}/radiation_data/` returns one row per day with `gcr`, `saa`, `total`. NASA's own chart code labels the unit "Dose [mGy/day]". Downloaded to `data/eda/<m>_radiation.json`. RR-12: 37 days, total 0.333–0.417 mGy/day. See `docs/TASKS.md` §4.

### 3.2 D5 — RadLab (scripted) — `ml/fetch_radlab.py`

The API works **[verified 2026-11-14]**:

```
GET https://visualization.osdr.nasa.gov/radlab/api/
    ?spacecraft=ISS
    &timestamp%3E=2022-04-01&timestamp%3C2022-04-02
    &absorbed_dose_rate&dose_equivalent_rate
    &format=csv
```

The response has the columns `timestamp, instrument_id, absorbed_dose_rate, dose_equivalent_rate, spacecraft`. Instruments seen: `DosTel1`, `DosTel2`, `Lidal`, `REM-Lid`. DosTel1 reports every 10 s. `dose_equivalent_rate` was empty in our sample, so we use **absorbed dose (Gy-based)**, which matches PLAN FE-13.

Script:
1. Download one day per request for one month (30 requests), saving raw files to `data/radlab/iss_<date>.csv`. Sleep 1 s between requests and skip days that already exist, so it can be re-run safely.
2. Aggregate per day and instrument: mean `absorbed_dose_rate`, number of samples, and the daily dose (`mean_rate × 24 h`, if the rate is per hour).
3. Write `vigil/backend/seed/radiation_daily.csv` with the columns `date, instrument, mean_rate, daily_dose, n, unit`.
4. **[check] The unit of `absorbed_dose_rate`** in the API docs (https://visualization.osdr.nasa.gov/radlab/gui/data-api). Don't put a unit on the page before this is confirmed.
5. Pick one instrument as the headline number (DosTel1 has the densest data). Show the others in a small table.

---

## 4. D1 — PPG-DaLiA → `ml/prep_dalia.py` (DP-1, P20)

### 4.1 What is actually in `S#.pkl` [verified on S1]

Load it with `pickle.load(f, encoding="latin1")`.

| Key | Shape (S1) | Rate | Notes |
|---|---|---|---|
| `label` | (4603,) | 8 s windows, 2 s shift | **reference HR from ECG**, in bpm |
| `rpeaks` | (11431,) int | — | sample indices into the **chest** signals at **700 Hz** |
| `signal.wrist.ACC` | (294784, 3) | 32 Hz | **already in g** (median ‖a‖ = 1.013). No 1/64 conversion is needed |
| `signal.wrist.TEMP` | (36848, 1) | 4 Hz | °C, starts around 32 °C |
| `signal.wrist.BVP` | | 64 Hz | not needed |
| `activity` | (36848, 1) | 4 Hz | codes 0–8 |
| `signal.chest.*` | | 700 Hz | not needed (R-peaks are already extracted) |
| `questionnaire` | | — | age, gender, height, weight, skin type, sport level |

S1 lasts 9212 s, about 2.6 h. All 15 subjects together give about 36 h.

Do **not** use `S#_E4.zip`. Its HR is Empatica's own PPG estimate, not the ECG reference. `S#_RespiBAN.h5` is not needed either.

### 4.2 Activity codes → context

From the order in `S#_activity.csv` and the readme **[check exact mapping in `PPG_FieldStudy_readme.pdf`]**:

| Code | Activity | `ctx_label` |
|---|---|---|
| 0 | transient / no activity (between protocol steps) | `none` (excluded from threshold fitting) |
| 1 | sitting (BASELINE, CLEAN_BASELINE) | `rest` |
| 2 | stairs | `active` |
| 3 | table soccer | `active` |
| 4 | cycling | `active` |
| 5 | driving | `rest` |
| 6 | lunch break | `rest` |
| 7 | walking | `active` |
| 8 | working (office) | `rest` |

### 4.3 Conversion to 1 Hz

The 1 Hz grid is `t = 0 … floor(len(ACC)/32) − 1`.

- **hr**: `label[i]` describes the window `[2i, 2i+8)` s, so its timestamp is `2i + 4`. Interpolate linearly onto the integer grid. **Don't extrapolate** past the first or last window; leave those seconds NaN.
- **act_mg**: reshape ACC into `(n_sec, 32, 3)`, compute `‖a‖` per sample, then `act_mg = mean(abs(‖a‖ − 1)) · 1000` per second.
- **skin_t**: reshape TEMP into `(n_sec, 4)` and take the mean.
- **act_code**: the most frequent code among the 4 samples in each second; then `ctx_label` comes from the table above.
- **IBI and HRV** (for C6 / DP-5):
  - `t_beat = rpeaks / 700`; `ibi_ms = diff(t_beat) · 1000`, stamped at the second beat.
  - Reject an IBI outside 300–2000 ms, or one that differs from the previous accepted IBI by more than 20 %. Drop the IBI (don't interpolate it).
  - Save `S#_ibi.parquet (t, ibi_ms, ok)`.
  - `hrv_rmssd_ms[t]` = RMSSD of the accepted IBI pairs in `(t − 300, t]`. It is NaN if fewer than 80 % of the expected beats in that window were accepted.
- Write `data/tracks/dalia/S#.parquet`.

**Memory:** each pkl is about 1.4 GB and loads entirely into RAM. Process one subject per loop iteration, `del` the dict, and call `gc.collect()`. Or run one process per subject.

**Done when** there are 15 parquet files and one subject has been plotted (hr, act_mg, skin_t, with ctx shaded) and checked by eye. Expect heart rate to rise during stairs, cycling and walking, and act_mg to be near 0 while seated.

---

## 5. D3 — sleep-accel → `ml/prep_sleep.py` (DP-4, P80)

### 5.1 File formats [verified]

| Folder | Format | Notes |
|---|---|---|
| `heart_rate/<id>_heartrate.txt` | `t,bpm` (comma) | irregular, median interval 5 s |
| `motion/<id>_acceleration.txt` | `t x y z` (space), in g, **gravity included** | about 50 Hz during the night (range 7.7–66 Hz across subjects) |
| `labels/<id>_labeled_sleep.txt` | `t stage` (space), 30 s epochs | |
| `steps/` | | not needed |

`t` is in seconds **relative to the start of PSG**. Negative values belong to the days before the lab night.

Stage codes, counted over all 31 files:
- `0` = wake;
- `1`, `2`, `3` = N1–N3;
- `4` = N4 (legacy, 356 epochs; treat it as N3);
- `5` = REM;
- **`-1` = unscored** (438 epochs) → `ctx_label = none`.

### 5.2 Conversion

1. **Crop** heart rate and motion to `[first_label_t, last_label_t + 30)`. The motion files contain days of data outside the lab night (1066528's file has 1.28 M rows).
2. **act_mg**: bin samples by `floor(t)` and use the same formula as DaLiA. A second with no samples is NaN. Bin by timestamp, not by a fixed sample count, because the sample rate varies.
3. **hr**: put it on the 1 Hz grid by carrying the last value forward for **at most 15 s**; after that it is NaN.
4. **ctx_label**: stage 1–5 → `sleep`; 0 → `rest` (awake in bed); -1 → `none`.
5. **skin_t**: none in this dataset. In vdev, night skin temperature is synthetic and **equal to the person's day value, with no night offset**. An offset of +0.8 °C was tested on 2026-11-15 with the core pipeline and produced one false "fever_like" Watch per person per day, because the first 15 quiet minutes of the night are still judged against the daytime norm (`docs/TASKS.md` §2.5, trap E).
6. **Coverage filter.** Some subjects have long HR gaps. In the worst case, only 18 % of the night is covered with ≤ 15 s carry-forward [verified]. Compute `hr_coverage` per subject. Subjects below **80 %** are excluded from the vdev pool. They are still used for the motion threshold (C2). Record the exclusions in the manifest.

Write `data/tracks/sleep/<id>.parquet`. Until this is done, vdev nights stay synthetic (PLAN §8.1).

---

## 6. D2 — BIDMC → `ml/prep_bidmc.py` (DP-6, C4)

Use **only** `bidmc_csv/bidmc_##_Numerics.csv`. Header: `Time [s], HR, PULSE, RESP, SpO2`. 1 Hz, about 481 rows (8 min) per record [verified]. Ignore `*_Signals.csv`, `*_Breaths.csv`, `.dat`, `.hea` and `.mat`.

Steps:
1. Clean each record:
   - SpO₂ outside 50–100 → NaN;
   - RESP ≤ 0 or > 60 → NaN;
   - HR ≤ 0 → NaN.
   Use only runs of at least 60 consecutive valid seconds.
2. Per record and metric (SpO₂, RESP), with μ = the record mean:
   - `φ = corr(x_t − μ, x_{t−1} − μ)`;
   - `σ_ε = std((x_t − μ) − φ·(x_{t−1} − μ))`.
3. Report the **median φ and median σ_ε over the 37 training records**. Then check on the 16 held-out records that a simulated series with those parameters has a similar std and lag-1 autocorrelation.
4. **Caveat:** BIDMC SpO₂ and RESP are **integers**. Quantization in 1 % / 1 breath steps distorts both φ and σ_ε. Note this in `DATA_NOTES.md`. If the result looks unreasonable (for example σ_ε ≈ 0 with φ ≈ 1), keep the PLAN §8.1 constants: SpO₂ φ=0.98, σ_ε=0.15; RR φ=0.95, σ_ε=0.4.
5. Optional check: regress RESP on HR across records, to compare with our coupling `μ_rr = rr_rest + 0.08·(hr − hr_rest)` [param]. These are ICU patients, so treat the result as a sanity check, not a calibration.

The output is a small JSON (`ml/out/ar1.json`). Its values go into the vdev generator constants. **Decided 2026-11-15:** use the fitted values, SpO₂ φ=0.92, σ_ε=0.21; RR φ=0.96, σ_ε=0.32 (`chosen_for_vdev` in the JSON; reasons in `DATA_NOTES.md` §4).

---

## 7. D4 → `ml/prep_eda.py` (SIM-4, P35)

1. Read `data/eda/*_co2_iss.json` (a list of `{time, co2_iss}`, already in ppm) and parse `time` as UTC.
2. Clean: values below 1000 ppm or above 20 000 ppm → NaN.
3. Resample to 1 min. EDA's step is 5 min, so interpolate linearly between points no more than 15 min apart; across longer gaps, leave NaN.
4. Write `data/env/co2_profile.parquet` with the columns `t_min, co2_ppm, mission`.
5. vdev plays it in a loop as the cabin channel. The `hypercapnia` scenario adds on top of it.
6. Log in `DATA_NOTES.md`: mean and max ppCO₂ (mmHg), and hours above 3.0 mmHg. That gives the deck a real NASA number.

---

## 8. Split and manifest → `ml/split.py` (DP-2, P21)

Split **by person, never by row**, with seed `2026`.

| Dataset | Train (offline: thresholds, XGBoost windows, LLM summaries) | Held out (played by vdev, used for all reported metrics) |
|---|---|---|
| DaLiA, 15 | 10 | 5 |
| sleep-accel, 31 minus excluded | ≈ 70 % | ≈ 30 % |
| BIDMC, 53 | 37 | 16 |

`ml/manifest.json`:

```json
{
  "seed": 2026,
  "created": "2026-11-14",
  "dalia":  {"train": ["S1", "..."], "holdout": ["S4", "..."]},
  "sleep":  {"train": ["..."], "holdout": ["..."],
             "excluded": [{"id": "....", "reason": "hr_coverage 0.18"}]},
  "bidmc":  {"train": ["01", "..."], "holdout": ["..."]}
}
```

Do the sleep coverage filter **before** splitting, so the held-out pool is usable.

### 8.1 Consequence for the simulator (SIM-2)

The 5 held-out DaLiA subjects give only about **12 h of daytime data** in total. A 14-day backfill for 7 crew needs about 1,500 awake hours. So the vdev playlist must **reuse segments**:
- Cut the held-out tracks into segments by `ctx_label`: rest blocks and active blocks, each at least 3 min.
- Assemble each virtual day by drawing segments at random.
- Re-normalize heart rate to the crew member: `hr' = (hr − rest_donor)·k + rest_crew` (PLAN §8.1).

This is fine for baseline learning. Say it openly in the Validity slide: "normal signals are real recordings, re-sampled into longer days".

---

## 9. Calculations (PLAN §6.3) — data, script, destination

All numbers go into `docs/DATA_NOTES.md`, each with: value, dataset, which subjects (train or held out), script name and commit. Fitting uses **train subjects only**. Accuracy is reported on **held-out subjects only**.

| # | What | Data | Script | Goes into |
|---|---|---|---|---|
| C1 | Resting HR per person = median `hr` where `ctx_label = rest` | DaLiA tracks | `calc_context.py` | donor `rest_donor` for vdev re-normalization |
| C2 | Context thresholds: 1-min median `act_mg` per class; active threshold = equal-error point of rest vs active; sleep threshold from sleep vs rest-awake | DaLiA (rest/active), sleep-accel (sleep) | `calc_context.py` | `ACTIVE_ACT_MG` (now 60), `SLEEP_ACT_MG` (now 8) in `vigil/core/thresholds.py` |
| C3 | Context-rule accuracy: run `vigil.core.context.classify` on held-out 1-min data and compare with `ctx_label` (ignore `none`). Target ≥ 85 % | held-out DaLiA + sleep | `calc_context.py` | Validity slide. Report cycling separately, because the wrist sees little motion on a bike |
| C4 | AR(1) φ, σ_ε for SpO₂ and RR | BIDMC train | `prep_bidmc.py` | vdev generator constants |
| C5 | σ floors: per subject × metric × ctx, `1.4826·MAD` of 1-min values; floor ≈ 25th percentile across subjects | DaLiA + sleep train | `calc_sigma.py` | `SIGMA_FLOOR` in `thresholds.py` (now hr 3.0, skin_t 0.3, hrv 8.0; spo2/rr stay as they are, because there is no real wearable source for them) |
| C6 | RMSSD at rest, 5-min windows | DaLiA IBI | `prep_dalia.py` | `hrv_rmssd_ms` channel; sanity check against crew profile range 30–60 ms |
| C7 | False alarms on normal data. Target ≤ 1 Watch per person-day, 0 Critical | vdev on held-out, no scenarios | later (DET-4) | main quality metric |
| C8 | Detection latency per scenario × severity | vdev on held-out + scenarios | later (DET-4) | slide, threshold tuning |
| C9 | XGBoost macro-F1, per-class recall, confusion matrix | windows from held-out people | `train_xgb.py` | slide |
| C10 | LLM number fidelity, pattern match, latency | 10 % LLM validation split | `llm_eval.py` | LLM vs template decision |

C2 and C5 must use the same 1-minute aggregation as the backend. Import `vigil.core.minute` / `vigil.core.context`; don't re-implement them (PLAN §4, rule 3). For offline data, set `sqi = 100` and `worn = 1` wherever `hr` is not NaN.

---

## 10. Licenses and attribution → `docs/DATA_LICENSES.md` (DS-6)

| Dataset | License | Cite |
|---|---|---|
| PPG-DaLiA | CC BY 4.0 | Reiss A., Indlekofer I., Schmidt P., Van Laerhoven K. "Deep PPG: Large-scale heart rate estimation with convolutional neural networks." *Sensors* 19(14):3079, 2019. |
| BIDMC | ODC-By 1.0 | Pimentel M.A.F. et al. "Toward a robust estimation of respiratory rate from pulse oximeters." *IEEE TBME* 64(8):1914–1923, 2017. + PhysioNet citation |
| sleep-accel | ODC-By 1.0 | Walch O., Huang Y., Forger D., Goldstein C. "Sleep stage prediction with raw acceleration and photoplethysmography heart rate data derived from a consumer wearable device." *SLEEP* 42(12):zsz180, 2019. + PhysioNet citation |
| PhysioNet | — | Goldberger A. et al. "PhysioBank, PhysioToolkit, and PhysioNet." *Circulation* 101(23):e215–e220, 2000. |
| OSDR EDA, RadLab | NASA open data | "NASA Open Science Data Repository (OSDR)", URL + access date. No NASA logos. |

Each row also records the URL and the access date. **[check]** Compare each citation with the dataset's landing page; PhysioNet shows the exact required text.

---

## 11. Disk cleanup (after the tracks are built)

| Delete | Frees | Safe when |
|---|---|---|
| `data/*.zip`, `data/ppg+dalia/data.zip` | about 6 GB | now (they can be downloaded again) |
| `S#_RespiBAN.h5`, `S#_E4.zip` | about 3.8 GB | now (not used) |
| `S#.pkl` | about 21 GB | after `S#.parquet` **and** `S#_ibi.parquet` exist and have been checked |
| sleep-accel `steps/`, BIDMC waveforms | small | any time |

Keep the download URLs in `docs/DATA_LICENSES.md` so anyone can rebuild everything from scratch.

---

## 12. Order of work

| When | ML | EMB | BE / D2 |
|---|---|---|---|
| Now | `paths.py`, `prep_dalia.py` (DP-1) | `fetch_eda.py` (DS-4, data already on disk), `fetch_radlab.py` (DS-5) | `.gitignore` / manifest location; D2: `DATA_LICENSES.md` |
| Next | `split.py` (DP-2), `prep_bidmc.py` (C4, about 30 min) | SIM-2 playlist from held-out DaLiA tracks | radiation seed file → `/radiation` (BE-7) |
| Then | C1–C3, C5 → `DATA_NOTES.md`, update `thresholds.py` | `prep_eda.py` → SIM-4 | — |
| Later | `prep_sleep.py` (DP-4), C6 (DP-5), then windows / XGBoost | real nights in the playlist | — |

### Done-checklist

- [x] `data/eda/` has CO₂ JSON for 5 missions + `SOURCE.txt` (ppm, 5-min step, ISS)
- [x] `vigil/backend/seed/radiation_daily.csv` exists, and its unit is confirmed (EDA, mGy/day)
- [x] 15 DaLiA tracks + IBI files; one subject checked by eye
- [ ] `ml/manifest.json` committed
- [x] `docs/DATA_NOTES.md` has C1–C5 with scripts and subject lists
- [x] `thresholds.py` updated from C2/C5, with the change noted in `DATA_NOTES.md`
- [x] sleep tracks + coverage exclusions
- [ ] `docs/DATA_LICENSES.md` complete for D1–D5 (written; citations still to be checked against the landing pages)
