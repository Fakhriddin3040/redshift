# Vigil — what is left to finish the project

Written 2026-11-15 12:30 (+05) from an audit of the repository, the running stack and the data on disk.
Task IDs in brackets (SIM-2, BE-7, …) refer to `PLAN.md`. Section numbers like "IMPL §9.2" refer to `docs/IMPLEMENTATION.md`.

Markers used in this file:

- **[verified]** — I checked it today against the code, the running stack, or by running the core pipeline offline.
- **[check]** — I could not verify it; a person must confirm before relying on it.
- **[param]** — an engineering choice, not a fact.

---

## 0. Read this first

1. **The project has no data source.** The virtual device (`vdev`) does not exist anywhere in the repository. Every screen is empty and the demo cannot run. This is the one task that blocks everything else (T1).
2. **The repository is not public.** `https://github.com/Fakhriddin3040/redshift` returns 404 to an anonymous request, and there is no `LICENSE` file. Both are submission requirements (T10).
3. **Deadline [check].** `PLAN.md` says 23:59 local time on 15 November, "to be confirmed with the local organizer". Confirm it now. Everything below assumes 23:59 (+05) and a submission no later than 21:30–22:00.
4. **Rules [check].** I could not open spaceappschallenge.org from this machine. The rule summary in `PLAN.md` §3 (demo is a video of at most 30 s or at most 7 slides, English only, public links, AI use declared, no NASA logos) is the plan author's reading from 12 November. D2 must re-read the Project Submission Guide today (PRE-1).
5. **Only claim what is built.** Section 5 lists which sentence in the submission depends on which task. A claim about a feature that is not in the repository is the most damaging mistake available to us.

### Order of work and the cut line

| Clock (+05) | Block | Must be true at the end |
|---|---|---|
| 12:30–15:30 | **A. Stream** | T1 steps 1–6: seven crew stream at 1 Hz, six have a learned baseline, the hypoxia button reaches the Critical screen. This is milestone M2. |
| 15:30–17:30 | **B. Demo-proof** | T2 passes (no false alarms on normal data). T3 Radiation on NASA data. Demo rehearsed twice, backup video recorded (T11). `LICENSE` and public repository done. |
| 17:30–20:00 | **C. Depth** (cut from the bottom) | T4 real DaLiA segments → T5 sleep endpoint → T6 server text → T7 XGBoost → T8 LLM. |
| 20:00 | **Feature freeze** | Only fixes after this. |
| 20:00–21:30 | **D. Submission** | T10 complete, T11 final recording. |
| 21:30–22:00 | Submit | Two hours of reserve remain. |

If block A is not finished by 16:00, drop everything in block C and move its time to A and B.

---

## 1. Current state [verified 2026-11-15, 16:30 +05]

| Area | State | Evidence |
|---|---|---|
| Core pipeline (`vigil/core`) | Done. Context rule refitted on real data; pattern name kept during recovery | 55 tests pass |
| Backend (`vigil/backend`) | Done: ingest, live, crew, today, metric, alerts, ack, sim forwarding, restore; **new:** `/radiation`, `/crew/{id}/sleep`, `/crew/{id}/checkin`, alert text from templates, pattern from the model | `GET /api/v1/health` → all counters 0 |
| Virtual device (`vigil/vdev`) | **Done (T1).** 7 streams, 14 days of history in about 8 s, live at ×1/×10/×60, 9 scenarios, real ISS CO₂, reset, reconnect | acceptance checks 1–8 in §2.9 pass against a local stack |
| False alarms (T2) | **Pass.** 0 incidents on normal data | `python -m ml.eval_false_alarms --seeds 3`, `docs/DATA_NOTES.md` §7 |
| Radiation (T3) | **Done.** Endpoint + page, NASA OSDR EDA RR-12 | `/radiation` |
| Real DaLiA day stream (T4) | **Tried, not enabled.** With real segments the detector gives 4–9 incidents per person-day; the stream stays simulated | `docs/DATA_NOTES.md` §10. Use the "simulated vital signs" wording in §5 |
| Sleep (T5) | **Done.** Endpoint + page + Crew column | `/crew/1/sleep` |
| Alert text (T6a) | **Done.** `docs/actions.yaml` + templates | `text_src = "template"` |
| Check-in on the server (T6b) | **Done** for check-in. The Report page is still assembled in the browser | `POST /crew/{id}/checkin` |
| Pattern classifier (T7) | **Done.** XGBoost, macro-F1 0.99 on simulated windows of people not in training; loaded by the backend without the xgboost package | `ml/models/pattern.json`, `docs/DATA_NOTES.md` §9 |
| LLM (T8) | **Not done, cut.** Text is from templates | say "template explanations" |
| Client | Radiation and Sleep pages show data; Today record rows filled | `client/src/app` |
| Compose | `postgres`, `backend`, `vdev`, `client` | `compose.yml` |
| Repository (T10) | `LICENSE`, English `README.md`, `docs/AI_USE.md`, `docs/DATA_LICENSES.md`, `docs/DATA_NOTES.md` written; `.idea/` no longer tracked. **Still to do by a person:** make the repository public, decide on the Russian documents, fill in the designers' tools in `AI_USE.md` | `git status` |

Still open, all for people: confirm the deadline and the rules (section 0), rehearse and record the demo (T11), the project page.

---

## 2. T1 — Virtual device `vdev` (blocker) [SIM-1, SIM-2, SIM-3, SIM-4]

Owner: EMB, with BE. Rough size: 3 hours for steps 1–6.

### 2.1 What it is

One Python process in `vigil/vdev/`, started with `uvicorn vigil.vdev.app:app --host 0.0.0.0 --port 8100`. It does two things:

- keeps **one** WebSocket open to the backend and sends 32-byte frames for device ids 1…7;
- serves four small HTTP routes that the backend forwards from `/api/v1/sim/*`.

Use `vigil.core.frame.Frame`, `pack`, `Flag`, `FrameType` to build frames. Do not re-implement the frame layout.

`websockets` 17.4 is installed (it comes with `uvicorn[standard]`) [verified]. If vdev imports it directly, add `websockets` to `pyproject.toml` dependencies so the dependency is explicit.

### 2.2 Wire contract with the backend [verified in code]

| Item | Value | Where it is defined |
|---|---|---|
| Ingest URL | `ws://<backend>:8000/api/v1/ingest` | `routes.py`, `app.py` |
| Message | one binary message = one 32-byte frame | `routes.ingest` |
| Device ids | `dev_id` 1…7 map to crew 1…7 | `schema.sql` |
| Unknown `dev_id` | frame dropped, `unknown_frames += 1` | `hub.handle_frame` |
| Time order | per device, `ts` must be **strictly greater** than the previous frame's `ts`, otherwise the frame is dropped as stale | `hub.handle_frame` |
| Type 1 | one second of data | `frame.py` |
| Type 2 | one minute of data (a summary). Processed at once, no one-minute wait | `hub.handle_frame` |
| `Flag.WORN` (bit 0) | must be set, otherwise the minute becomes context `off` | `context.py` |
| `Flag.EXERCISE` (bit 4) | forces context `active` | `context.py` |
| `Flag.HISTORY` (bit 7) | the frame is processed and stored, but nothing is pushed to `/live` and no check-in notice is opened | IMPL §4.6 |
| `sqi` | a second counts for vital signs only if `sqi ≥ 50`; a minute with mean `sqi < 20` is `off` | `minute.py`, `context.py` |
| "No data" | pass `None` in the `Frame` field; never 0 | `frame.py` |

Rules that are easy to break:

1. **Use one connection and send in order.** History first, then live, on the same socket. If live frames travel on a second connection they can be processed first, and then all history is dropped as stale.
2. **Start live on a minute boundary after history.** If the last history frame is for minute `M`, the first live second must be `(M + 1) · 60`. Sending type-1 seconds inside a minute that already had a type-2 frame makes the backend process that minute twice, which resets the alert counters.
3. **Never skip seconds to go faster.** A minute needs at least 20 valid seconds to have a value at all, and at least 40 valid heart-rate seconds before the hard limits are checked (`HARD_MIN_VALID_SECONDS`). With fewer than 40, low SpO₂ would never become Critical. Always send all 60 seconds of every virtual minute.
4. **All logic runs on frame time.** The backend never looks at its own clock except to show "connected / no link" (last frame within 10 s of wall time).

Throughput, measured today with the real `Hub` and no database: 18,000 minute frames per second and 50,000 second frames per second. A 14-day history for 7 crew is 141,120 minute frames, about 8 s of backend CPU. Speed ×60 needs 420 frames per second. The backend is not the bottleneck.

### 2.3 HTTP contract [verified in `routes.py` and `client/src/components/DemoPanel.tsx`]

The backend forwards these with a **5-second timeout**. Every handler must answer at once and do its work in the background.

| Route on vdev | Body the client sends | Must do | Response |
|---|---|---|---|
| `GET /state` | — | report state | JSON. The client reads the scenario list from `scenarios` (array of strings). Suggested: `{"scenarios": [...], "speed": 1, "mode": "backfill"\|"live", "virtual_ts": 1794…, "active": [{"crew": 1, "name": "hypoxia", "elapsed_s": 40}]}` |
| `POST /scenario` | `{"crew": 1, "name": "hypoxia", "scenario": "hypoxia"}` | start the scenario for that crew member. Also accept optional `severity` (1–3) and `duration` (s); the client does not send them today, so defaults must work | any JSON; on an unknown name return 400 with `{"detail": "..."}` |
| `POST /speed` | `{"speed": 1}`, `10` or `60` | change the clock rate | any JSON |
| `POST /reset` | `{}` | stop sending **before** answering; then restart from scratch (2.4) | any JSON |

### 2.4 Clock, history and reset

Virtual clock `vt` (unix seconds). At start: `vt0 = floor(wall_now / 60) · 60`.

**History (backfill).** For each crew member send type-2 frames with `WORN | HISTORY`, one per minute, from `vt0 − N · 86400` to `vt0 − 60`:

- crew 1–6: `N = 14` → baseline "learned";
- crew 7: `N = 3` → baseline "learning, day 3–4 of 7" [verified in IMPL §7.7: learned needs 7 distinct days and 75 % of cells ready].

**Live.** From `vt0`: every virtual second, one type-1 frame per crew member. At speed `K`, send `K` virtual seconds per real second.

**Reset.** The backend's order is: pause ingest → call vdev `/reset` → wipe the database → resume (IMPL §16.9). Frames that arrive while it is paused are thrown away silently. So after answering `/reset`, vdev must not start the new history until the wipe is finished. A reliable way to know: poll `GET /api/v1/crew` every 0.5 s until every `now_ts` is `null`, wait one more second, then start. (The extra second covers a reset pressed when the database was already empty, where `now_ts` is `null` before the wipe as well.) A blind 3 s sleep is the fallback.

**Start-up.** Postgres keeps data between runs, and the backend restores `last_ts` from it. If an earlier run used fast mode, the stored time is ahead of the wall clock and every new frame would be dropped as stale. So on start vdev should call `POST <backend>/api/v1/sim/reset` itself and begin only when that call returns. (The backend calls vdev's `/reset` inside that request, so the HTTP server must be listening first.)

Health check after any start or reset: `GET /api/v1/health` must show `stale_frames: 0`.

### 2.5 Normal signal: rules that keep the baseline quiet

Design each signal as a **slow part** (one value per minute) plus **per-second jitter** with zero median. History frames carry the slow part; live frames carry slow part + jitter. Then the minute values learned from history match the minute medians seen live.

Crew profiles [param], chosen to stay clear of the hard limits:

| Field | Range over the 7 people | Why |
|---|---|---|
| Resting heart rate | 56–68 | sleep value must stay well above 40 |
| Sleep heart rate | rest − 8…10, never below 46 | heart rate ≤ 40 in sleep is a hard Alert |
| SpO₂ mean | 96.5–98.0 | — |
| Breathing, rest | 12–16; night = rest − 1 | — |
| Skin temperature | 32.5–34.5 °C, **same day and night** | see trap E below |

Clamp normal output so a hard limit can never fire without a scenario: heart rate in rest and sleep within [44, 108]; breathing within [9.5, 20.4]; SpO₂ within [mean − 1.8, 100].

Day schedule: 8 h sleep, 16 h awake, two exercise blocks.

Motion: sleep `act_mg` 0–5 (the sleep rule counts minutes at ≤ 12 up to 15; a restless minute takes 2 off); rest 15–40; exercise ≥ 100 (active is ≥ 80).

Signal quality: 85–100 normally.

The traps below were each reproduced today by driving `vigil.core.pipeline.CrewState` with 21 synthetic days and counting incidents after day 8 [verified]:

| # | What the generator does | Incidents per person-day | Fix |
|---|---|---|---|
| A | Heart rate steps to the sleep value exactly when the context becomes `sleep` (the 15th quiet minute) and back to the rest value in the same minute motion returns | **0.00** | this is the target behavior |
| B | Heart rate drops in the first quiet minute | 1.00 (bradycardia, in `rest`) | hold the rest value for the first 14 quiet minutes |
| C | Heart rate drops 30 min after sleep starts | 1.00 (tachycardia_rest, in `sleep`) | drop at minute 15, within 2 minutes |
| D | Heart rate stays low for 10 min after waking | 1.00 (bradycardia, in `rest`) | raise it in the same minute motion returns |
| E | Skin temperature +0.8 °C at night | 1.00 (fever_like) | no night offset |
| G | Sleep heart rate 42 | 1.62 (hard Alert in sleep), and the baseline never finishes learning | keep ≥ 46 |
| H | `EXERCISE` flag ends when motion ends, heart rate recovers over 20 min | 1.00 (tachycardia_rest Alert) | see J |
| I | Flag kept 10 min into a 20-min recovery | 0.92 | not enough |
| J | Flag kept for the whole recovery | **0.00** | keep `EXERCISE` set until heart rate is back within rest + 5 |

### 2.6 Cabin channels: real NASA data [SIM-4]

Same values for all seven devices at a given `vt` (one cabin).

- **CO₂:** `data/eda/RR-12_co2_iss.json` — ISS CO₂ in ppm every 5 minutes, 40 days, from the NASA OSDR EDA API. Clean: values below 1000 ppm are sensor glitches, set them to missing. Interpolate linearly to one value per minute across gaps of at most 15 minutes. Loop the profile: index = `(vt // 60) mod length`.
- **Why RR-12** [verified today]: its highest 1-hour mean is 2.77 mmHg, so the 3.0 mmHg Watch limit never fires on normal data. RR-19 is also clean (2.68). **Do not use RR-1 or RR-3 as the normal profile**: their 1-hour mean is above 3.0 on 14 of 43 and 28 of 51 days, which would put the whole crew on Watch. **Do not use RR-9**: its CO₂ is dated 2018 and its radiation 2017 in the API.
- **Pressure:** 1013.0 hPa with noise of at most ±0.3 hPa [param]. A drop of more than 2 % within 10 minutes is an Alert.
- **Cabin temperature:** 22.5 ± 0.2 °C [param].
- The Docker image does not contain `data/` (`.dockerignore`). Commit the small cleaned profile as `vigil/vdev/assets/co2_iss_rr12.csv` and add `"vigil.vdev" = ["assets/*"]` under `[tool.setuptools.package-data]` in `pyproject.toml`. NASA open data may be redistributed; credit it in `docs/DATA_LICENSES.md`.

### 2.7 Scenarios

Minimum set for the demo, in this order: `hypoxia`, `exercise`, `sensor_off`, `tachycardia_rest`. Then `hypercapnia`, `depressurization`, `bradycardia`, `fever_like`, `motion_artifact` (SIM-5).

**`hypoxia` must be staged relative to the person's own SpO₂ mean `μ`.** Verified today with the core pipeline (σ floor for SpO₂ is 1.0, so the usual band is μ ± 2):

| Stage | SpO₂ | Minutes | Result |
|---|---|---|---|
| 1 | μ − 2.5 | 7 | **Watch** at closed minute 5 (source `baseline`) |
| 2 | 93.0 | 4 | **Alert** at minute 8 (hard limit) |
| 3 | 88.0 | 4+ | **Critical** at minute 12 |
| end | back to μ | — | level steps down one step every 10 minutes: 3→2→1→0 takes 30 minutes |

Also add heart rate +1 bpm per −1 % SpO₂ and breathing +2…+4 (stay below 21).

Two ways this goes wrong [verified]:

- A smooth ramp (−1.2 % per minute) jumps straight from Usual to Alert at minute 4 and Critical at minute 5. The yellow Watch stage never shows.
- A fixed plateau of 94.5 works only for μ = 97. For μ = 98 it gives Alert at minute 3; for μ = 96.5 it gives no Watch at all.

In live mode add about one minute to each time: a minute closes when the first frame of the next minute arrives. At speed ×60 the full arc takes about 13 real seconds.

| Scenario | What to send | Expected [verified by tests or IMPL] |
|---|---|---|
| `exercise` (a demo control, not an anomaly) | `EXERCISE` flag, `act_mg` 120–200, heart rate up to 130–145 for 5 min, then recovery with the flag kept until heart rate ≤ rest + 5 | level stays 0; heart-rate card shows "exercising" |
| `sensor_off` | `WORN` cleared, `sqi = 0`, `hr`, `spo2`, `rr` = `None`; cabin channels unchanged | after one closed minute: cards "no data", Device page "not worn", level unchanged, no incident |
| `tachycardia_rest` | heart rate +40 at rest with low motion | Alert at the 3rd closed minute; +60 (≥ 111) is a hard Alert at the 1st; ≥ 131 is Critical |
| `hypercapnia` | raise CO₂ so ppCO₂ ≈ 6 mmHg | the limit uses a 1-hour mean. From the RR-12 level of about 2.0 mmHg: Watch (> 3.0) after about 15 minutes, Alert (> 5.3) after about 50. Use ×60 to show it |
| `depressurization` | pressure −12 % over 10 min | Alert once the drop exceeds 2 % (about minute 2), Critical below 90 % of the 24-hour median (about minute 9) |

Draw scenario parameters at random within a range on each run (PLAN §8.4), except the hypoxia stages above, which must hit their thresholds.

### 2.8 Compose

Add a `vdev` service that reuses the backend image:

```yaml
  vdev:
    build: .
    restart: unless-stopped
    command: ["uvicorn", "vigil.vdev.app:app", "--host", "0.0.0.0", "--port", "8100"]
    depends_on: [backend]
    environment:
      VDEV_INGEST_URL: ws://backend:8000/api/v1/ingest
      VDEV_BACKEND_URL: http://backend:8000/api/v1
```

**Fix the backend's vdev address.** `.env` has `VIGIL_VDEV_URL=http://localhost:8100`, and Compose substitutes that value into the backend container [verified with `docker compose config`]. Inside the container `localhost` is the container itself, so `/sim/*` would keep returning 503. In `compose.yml` set `VIGIL_VDEV_URL: http://vdev:8100` as a fixed value. Keep `localhost:8100` in `.env` only for running the backend with `uv run uvicorn` on the host.

### 2.9 Build steps and acceptance

| Step | Build | Done when |
|---|---|---|
| 1 | Skeleton: WebSocket connect with retry, one crew member, synthetic 1 Hz | Today shows numbers changing each second |
| 2 | Seven profiles, day schedule, history + live, start-up reset | see checks 1–4 |
| 3 | HTTP routes, speed, reset | demo panel works; check 8 |
| 4 | `hypoxia`, `exercise`, `sensor_off`, `tachycardia_rest` | checks 5–7 |
| 5 | CO₂ from the EDA asset | CO₂ card shows about 2.0 mmHg and moves |
| 6 | Compose service + `.env` fix | `docker compose up --build` gives a working demo from nothing |
| 7 | Remaining scenarios | each visible on its chart |

Acceptance checks (all against `http://localhost:8000/api/v1`):

1. `GET /health` → `bad_frames`, `unknown_frames`, `stale_frames` all 0 after history plus one minute of live.
2. `GET /crew` → crew 1–6 `baseline.state = "learned"`; crew 7 `"learning"`; every `level = 0`.
3. `GET /crew/1/today` → all seven cards have a value; `device.link = "connected"`.
4. `GET /crew/{id}/alerts` for all seven → only `baseline_learned` and `checkin:*` entries. **No entry with `key = "incident"`.**
5. Hypoxia on crew 1 at ×60 → level goes 1, then 2, then 3; `notices[0].pattern = "hypoxia"`, `primary = "spo2"`; the Critical screen opens; Acknowledge closes it.
6. Exercise → level stays 0.
7. Sensor off → cards "no data", level unchanged, no new incident.
8. Reset from the demo panel → within a minute the state matches checks 1–4 again.

---

## 3. T2 — False-alarm check on normal data [C7, DET-4]

Owner: ML or BE. Rough size: 1 hour. Start as soon as the vdev generator functions exist.

Write `ml/eval_false_alarms.py`. It imports the vdev signal generator and feeds minutes straight into `vigil.core.pipeline.CrewState.on_minute` — no backend, no network. Fourteen days for seven people runs in seconds.

Report per person: number of incidents by level and pattern, and incidents per person-day after day 8.

Target: zero Alert and zero Critical; at most one Watch per person-day (PLAN C7). With the rules in 2.5 the measured rate was 0.00.

Run it again after **every** change to the generator, the profiles, or `vigil/core/thresholds.py`. A false Critical during the live demo is the worst outcome we can produce ourselves.

Write the final numbers into `docs/DATA_NOTES.md`; they are the "Validity" slide.

---

## 4. T3 — Radiation page on NASA data [BE-7, FE-13]

Owner: BE + FE. Rough size: 1.5 hours.

**Use the EDA radiation series, not RadLab.** `GET https://visualization.osdr.nasa.gov/eda/api/missions/RR-12/radiation_data/` returns one row per day with `gcr`, `saa`, `total`. NASA's own chart code labels the axis "Dose [mGy/day]" [verified in `eda/static/js/radiation_plots.js`]. RR-12 has 37 days (2019-04-17 … 2019-05-23), total 0.333–0.417 mGy/day. Already downloaded: `data/eda/RR-12_radiation.json`.

The unit of RadLab's `absorbed_dose_rate` is still unknown: the RadLab documentation page returned HTTP 500 today. Do not put `data/radlab_iss.csv` numbers on screen with a unit until someone confirms it [check].

Backend:

1. Commit `vigil/backend/seed/radiation_daily.csv` (`day,total,gcr,saa`) built from the JSON, and add it to `package-data`.
2. Table `radiation_daily` exists with columns `day, dose, unit, instrument`. To store `gcr` and `saa` add `alter table radiation_daily add column if not exists gcr real;` (same for `saa`) to `schema.sql`. Editing the `create table` statement alone does nothing on an existing database, because it is `create table if not exists`.
3. Load the seed at start-up if the table is empty. `/sim/reset` does not truncate this table [verified in `db.wipe`].
4. `GET /api/v1/radiation` → `{"unit": "mGy/day", "source": "NASA OSDR Environmental Data App, RR-12, 2019-04-17 to 2019-05-23", "days": [{"day": "...", "total": 0.358, "gcr": ..., "saa": ...}], "last_24h": ..., "mean_14d": ..., "total_14d": ...}` using the last 14 rows.
5. Fill `record.radiation` in `/today` with the last daily value, or leave it `null` and change the client label.

Client:

1. `client/src/app/radiation/page.tsx`: three tiles and a 14-bar chart from the endpoint.
2. Replace "NASA OSDR RadLab" with "NASA OSDR Environmental Data App" in the page header and in `client/src/app/page.tsx` line 51.
3. Show the measurement dates on the page ("Measured on the ISS, April–May 2019"). The values are real but old; presenting them as today's dose would be false.
4. No career-limit bar in mSv: the data is absorbed dose in mGy.

---

## 5. Claims and what each one requires

| Sentence in the deck, video or project page | Allowed only if |
|---|---|
| "Cabin CO₂ is real ISS telemetry from NASA OSDR" | T1 step 5 is done |
| "Radiation page shows real ISS dose from NASA OSDR" | T3 is done |
| "Normal vital signs are real wearable recordings (PPG-DaLiA)" | T4 is done **and** T2 passes with it. Otherwise say "simulated vital signs with parameters taken from open datasets" |
| "Real sleep recordings" | sleep-accel nights are wired in (DP-4). Otherwise do not mention it |
| "An XGBoost model names the pattern" | T7 is done and loaded in the backend. Otherwise say "rule-based pattern naming" |
| "A fine-tuned on-board LLM explains each alert" | T8 is done and passes its check. Otherwise say "template explanations" |
| "False alarms: N per person-day" | the number comes from T2 on the final generator |
| "Daily report" | true today in a limited form: the Report page assembles the text in the browser from live data. Do not say it is stored or sent by the server unless T6b is done |
| "Trained on NASA astronaut data", "the LLM detects anomalies", "9x % accuracy" with no qualifier | never (PLAN §16) |

---

## 6. Block C tasks (cut from the bottom)

### T4 — Real DaLiA segments in the daytime stream [DP-1, DP-2, SIM-2]. About 2 hours.

Steps are in `docs/DATA_PLAN.md` §4 and §8: `ml/prep_dalia.py` → 15 one-second tracks; `ml/split.py` → `ml/manifest.json` (10 train, 5 held out, seed 2026); cut the 5 held-out tracks into rest and active segments; vdev plays them with heart rate re-scaled to each crew member.

Add `numpy pandas pyarrow` in a separate dependency group (`uv add --group ml …`); they are not installed now [verified].

Commit the small segment file under `vigil/vdev/assets/` (PPG-DaLiA is CC BY 4.0; credit it).

Gate: T2 must still pass. Real recordings break the rules in 2.5 in ways synthetic data does not: heart rate above 110 while labelled "rest" (driving, lunch) is a hard Alert, and real recovery after stairs is slow. If T2 fails and cannot be fixed in 30 minutes, keep the synthetic stream and change the claim (section 5).

### T5 — Sleep endpoint and page [BE-8, FE-14]. About 1.5 hours.

`GET /api/v1/crew/{id}/sleep`: from `agg_1m`, group minutes with `ctx = 1` into nights; return per night the onset time, wake time and duration for the last 7 nights. Fill `sleep_7n_mean_min` in `/crew` (now always `null`).

Client: `client/src/app/sleep/page.tsx` is static text today.

If not done: remove the Sleep link from `NAV` in `client/src/components/Shell.tsx` so the demo has no dead page.

### T6 — Server-side records

**T6a — alert text templates [LLM-0].** About 1 hour. `docs/actions.yaml` (pattern × severity → 1–3 allowed actions, written by a person) and a template that fills `Incident.text = {what, why, action}` with `text_src = "template"`. Values must come from the incident's own `metrics`. The client already prefers server text when present. PyYAML 6.0.3 is installed [verified]; add it to `pyproject.toml` if imported.

**T6b — check-in and report on the server [BE-6, FE-9, FE-11].** About 2 hours. Tables `checkin` and `report` exist and are empty. `POST /crew/{id}/checkin` should store the entry, close the `checkin:<day>` notice, and fill `checkin_ts` in `/crew`. Today a check-in filed in one browser is invisible everywhere else, and the Crew table shows "Not filed" for everyone but yourself.

**Small fix, 10 minutes:** during recovery the pattern name disappears (the rule returns `None` once SpO₂ is above the median) [verified in the simulation]. In `CrewState._refresh_incident` keep the previous value: `inc.pattern = rule_pattern(...) or inc.pattern`. Add a test.

### T7 — XGBoost pattern classifier [ML-1 … ML-4]. About 3 hours. Needs T1.

1. `vigil/core/features.py`: 40 features from a 10-minute window (PLAN §10), in z units from the personal baseline.
2. `ml/make_windows.py`: run the vdev generator offline through `CrewState`, inject scenarios with random parameters, label a window when the scenario covers ≥ 5 of its 10 minutes. Train on one set of profiles and seeds, test on another.
3. `ml/train_xgb.py`: parameters in PLAN §10; save `ml/models/pattern.json`; write macro-F1, per-class recall and the confusion matrix to `docs/DATA_NOTES.md`.
4. Backend: load the model from `VIGIL_PATTERN_MODEL` if the file exists, set `pattern` and `p`; fall back to the rule otherwise.

`xgboost` is not installed [verified]. Whether a wheel installs on Python 3.14 is untested [check]: run `uv add xgboost` first, before writing any code.

State on the slide that the abnormal classes are simulated (PLAN §10).

### T8 — LLM explanation [LLM-1 … LLM-4]. About 4 hours. Needs T6a.

Dataset from simulated incident summaries → teacher model → automatic check (every number in the output exists in the input; pattern name matches; action is from the allowed list; exactly three lines) → LoRA on Qwen3-1.7B → GGUF → Ollama → backend call with a 5 s timeout and template fallback.

This machine has an RTX 3080 (12 GB), so training may be possible locally instead of Colab [check].

If fewer than 98 % of validation answers have correct numbers, the demo uses templates (PLAN LLM-4).

With the time left this is the first task to cut. Cutting it costs nothing in the demo: the template text is already on screen.

### Not planned

Device token (PR-2), day-level drift (DET-5), light theme (FE-15), wristband hardware (P101+), Ask Vigil chat, Exercise page.

---

## 7. T10 — Submission [SUB-2, SUB-3, SUB-4, DS-6]

Owner: D2 + BE. None of this needs the code to be finished; start it in block A.

### Repository

| # | Task | Detail |
|---|---|---|
| 1 | Add `LICENSE` | Apache-2.0 full text. `pyproject.toml` already declares it |
| 2 | Make the repository public | Before that, check history: I scanned tracked files for keys and found none [verified]; `.env` is ignored |
| 3 | Delete the two `index.html?spacecraft=…` files in the root | They are stray wget output (3 MB). `git add -A` would commit them |
| 4 | Stop tracking `.idea/` | `git rm -r --cached .idea` |
| 5 | Decide on Russian documents | `docs/IMPLEMENTATION.md` (tracked) and `PLAN.md` (untracked) are in Russian. The rule says all content must be in English [check how strictly this applies to internal documents]. Safest: keep `PLAN.md` out of the repository and either translate `IMPLEMENTATION.md` or remove it from the published branch |
| 6 | Rewrite `README.md` in English | Now it says "backend only" and refers to `TASK.md`, which does not exist. Needed: what Vigil is; one command to run everything (`docker compose up --build`, then open `http://localhost:3000`); how to trigger the demo; data sources; limits ("prototype, not a medical device") |
| 7 | `docs/DATA_LICENSES.md` | Table in `docs/DATA_PLAN.md` §10. Add the EDA rows: CO₂ and radiation, RR-12, API URL, access date 2026-11-14/15 |
| 8 | `docs/AI_USE.md` | List every AI tool and what it produced. Known from this repository: an AI coding assistant (Claude Code) was used for parts of the code and documentation. Add the teacher model and the fine-tuned model if T8 is done, and anything the designers used |
| 9 | `docs/DATA_NOTES.md` | Numbers from T2 (and T7 if done) with the script that produced each |

### Demo artifact

Either a video of at most 30 seconds or at most 7 slides including the title [check against the guide]. Outline for 7 slides is in PLAN §14. For a video, see T11.

Public link, no login. No NASA logos.

### Project page fields

| Field | Content |
|---|---|
| Summary | one paragraph (PLAN §1) |
| NASA data | OSDR EDA: ISS cabin CO₂ (RR-12) drives the cabin channel; EDA daily radiation dose; NASA-STD-3001 Vol. 2 CO₂ limit of 3 mmHg (1-hour mean) used as the Watch threshold. List only what is wired in (section 5) |
| Other data | PPG-DaLiA, BIDMC, sleep-accel — only those actually used; NEWS2 thresholds |
| Use of AI | same content as `docs/AI_USE.md` |
| Links | public repository; public demo |

A public live deployment (SUB-1) is not required if the repository and the demo link are public [check]. Skip it unless everything else is done.

---

## 8. T11 — Demo script and backup

Rehearse at least twice after T2 passes. Record the screen on the second run; that recording is the backup if the network or the laptop fails.

| Step | Action | What the audience sees |
|---|---|---|
| 0 | Reset from the demo panel, wait for history | Crew page: six "Learned", one "Learning · day 4 of 7" |
| 1 | Today, crew 1, speed ×1 | seven cards ticking each second; CO₂ from ISS data |
| 2 | Switch to crew 7 | "Learning your baseline", cards without a usual range |
| 3 | Crew 1, run `exercise` | heart rate 130+, card says "exercising", background unchanged |
| 4 | Speed ×60, run `hypoxia` | background turns yellow (Watch), amber with banner (Alert), then the red Critical screen with reason and steps; about 15 s |
| 5 | Speed ×1, Acknowledge, "Show readings" | SpO₂ chart with the usual band and the marked event |
| 6 | Run `sensor_off` | cards "No data", Device page "not worn", no alarm |
| 7 | Report page | summary text assembled from the day's data |

Before step 4 make sure step 3's recovery has finished (heart rate back to rest), or the two effects overlap.

After a Critical the level needs 30 virtual minutes to return to Usual (30 s at ×60). Use Reset between rehearsals.

Test ×60 in the browser before recording: the client receives 60 messages per second per crew member, and smoothness on the demo laptop is untested [check].

---

## 9. Final checklist before pressing Submit

- [ ] Deadline and rules re-read today (section 0, items 3–4)
- [ ] `docker compose down -v && docker compose up --build` on a clean checkout gives a working demo
- [ ] Acceptance checks 1–8 from 2.9 pass
- [ ] T2 report: zero Alert/Critical on normal data, numbers written down
- [ ] `uv run pytest` passes; `uv run ruff check` clean
- [ ] Every claim in the deck, video and project page is in the "allowed" column of section 5
- [ ] UI text, README, deck, project page are in English
- [ ] `LICENSE` present; repository public; opens in a private browser window
- [ ] Demo link opens in a private browser window, no login
- [ ] `DATA_LICENSES.md` and `AI_USE.md` present and true
- [ ] No NASA logos anywhere
- [ ] No stray files, no `data/`, no `.env` in the repository
- [ ] Backup recording saved in two places

---

## 10. What I could not verify

| Item | Why | Who should check |
|---|---|---|
| Submission rules and deadline | spaceappschallenge.org is unreachable from this machine | D2, today |
| Unit of RadLab `absorbed_dose_rate` | documentation page returned HTTP 500 | only matters if RadLab is shown |
| Mapping of DaLiA activity codes 1–8 | inferred from the order in `S1_activity.csv`; the readme PDF was not read | ML, before T4 |
| `xgboost` on Python 3.14 | not installed, not tried | ML, before T7 |
| Browser smoothness at ×60 | not tested | FE, during T11 |
| Whether the EDA CO₂ sensor is open cabin air or next to the rodent habitat | EDA's page text says "ISS cabin"; the API gives no sensor location | wording in the deck: "ISS cabin CO₂ telemetry, NASA OSDR EDA" |
