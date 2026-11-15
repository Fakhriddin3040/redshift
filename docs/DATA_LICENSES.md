# Vigil — data licenses and attribution

All datasets were accessed on **2026-11-14** (NASA radiation series: 2026-11-15). None of the raw data is committed; `data/` is gitignored. The small derived files that are committed are listed below.

License source: **[file]** — read from the license file shipped with the dataset; **[check]** — taken from the plan, still to be compared with the dataset's landing page.

| ID | Dataset | Used for | License | URL |
|---|---|---|---|---|
| D1 | PPG-DaLiA | daytime heart rate, motion, skin temperature, HRV | CC BY 4.0 **[check]** | https://archive.ics.uci.edu/dataset/495/ppg+dalia |
| D2 | BIDMC PPG and Respiration Dataset 1.0.0 | AR(1) parameters for SpO₂ and respiratory rate | ODC-By 1.0 **[check]**; the dataset's `LICENSE` file says it contains modified PhysioNet (MIMIC-II) files, distributed under PhysioNet's terms for modified data **[file]** | https://physionet.org/content/bidmc/1.0.0/ |
| D3 | Motion and heart rate from a wrist-worn wearable and labeled sleep from polysomnography 1.0.0 (sleep-accel) | night heart rate and motion, sleep labels | ODC Attribution License (ODC-By) **[file]** | https://physionet.org/content/sleep-accel/1.0.0/ |
| D4 | NASA OSDR Environmental Data App (EDA): ISS cabin CO₂ and daily radiation dose, missions RR-1, RR-3, RR-9, RR-12, RR-19 | cabin CO₂ channel, Radiation page | NASA open data **[check]** | https://visualization.osdr.nasa.gov/eda/api_reference |
| D5 | NASA OSDR RadLab | not used, not downloaded | NASA open data **[check]** | https://visualization.osdr.nasa.gov/radlab/gui/data-api |

## Citations

**PPG-DaLiA.** Reiss A., Indlekofer I., Schmidt P., Van Laerhoven K. "Deep PPG: Large-scale heart rate estimation with convolutional neural networks." *Sensors* 19(14):3079, 2019.

**BIDMC.** Pimentel M.A.F., Johnson A.E.W., Charlton P.H., Birrenkott D., Watkinson P.J., Tarassenko L., Clifton D.A. "Toward a robust estimation of respiratory rate from pulse oximeters." *IEEE Transactions on Biomedical Engineering* 64(8):1914–1923, 2017.

**sleep-accel.** Walch O., Huang Y., Forger D., Goldstein C. "Sleep stage prediction with raw acceleration and photoplethysmography heart rate data derived from a consumer wearable device." *SLEEP* 42(12):zsz180, 2019.

**PhysioNet** (for BIDMC and sleep-accel). Goldberger A., Amaral L., Glass L., Hausdorff J., Ivanov P.C., Mark R., Mietus J.E., Moody G.B., Peng C.K., Stanley H.E. "PhysioBank, PhysioToolkit, and PhysioNet: Components of a new research resource for complex physiologic signals." *Circulation* 101(23):e215–e220, 2000.

**NASA.** "NASA Open Science Data Repository (OSDR), Environmental Data App", https://visualization.osdr.nasa.gov/eda/, accessed 2026-11-14. Wording for the deck: "ISS cabin CO₂ telemetry, NASA OSDR EDA (RR-1…RR-19)". No NASA logos.

**[check]** Compare each citation with the dataset's landing page before the submission; PhysioNet shows the exact required text.

## Derived files in the repository

| File | Made from | By |
|---|---|---|
| `vigil/backend/seed/radiation_daily.csv` | NASA OSDR EDA, RR-12 daily dose | `ml/prep_eda.py` |
| `vigil/vdev/assets/co2_iss_rr12.csv` | NASA OSDR EDA, RR-12 ISS cabin CO₂, cleaned, 1-min step | `ml/prep_eda.py` |
| `vigil/vdev/assets/dalia_rest_segments.csv` | PPG-DaLiA (CC BY 4.0), 5 held-out subjects: per-minute heart rate relative to the person's resting value, and wrist motion. Used only by `ml/eval_false_alarms.py --real-day`; the demo stream does not play it | `ml/make_segments.py` |
| `ml/models/pattern.json` | windows produced by our own simulator (no dataset rows) | `ml/train_xgb.py` |

## What is modified

- PPG-DaLiA and sleep-accel are converted to 1 Hz tracks (`ml/prep_dalia.py`, `ml/prep_sleep.py`). They are used to fit and test the context rule. The demo stream does not replay them (see `docs/DATA_NOTES.md` §10).
- BIDMC is used only to fit two model parameters per metric (`ml/prep_bidmc.py`).
- NASA CO₂ is cleaned (values below 1000 ppm removed) and interpolated from a 5-min to a 1-min step (`ml/prep_eda.py`). The radiation series is copied unchanged, rounded to 5 decimals.

## Rebuilding from scratch

1. Download the three archives from the URLs above into `data_archives/`, and extract them into `data/` with the folder names in `ml/paths.py`. From PPG-DaLiA only `S#.pkl` and the csv files are needed.
2. `python -m ml.fetch_eda` downloads the NASA files into `data/eda/`.
3. Run the scripts in the order listed at the top of `docs/DATA_NOTES.md`.

## Not used

MIMIC-III (optional), WESAD (license), OpenOximetry (restricted access).
