# Vigil

Crew health monitoring for long space missions, built for NASA Space Apps 2026.

Each crew member wears a wristband. Vigil learns that person's own usual range for heart rate, blood oxygen, breathing and skin temperature, watches the cabin air, and raises a clear, staged alert — Watch, Alert, Critical — with the reason and the next steps, without waiting for the ground.

**Prototype, not a medical device.** There is no hardware yet: a virtual device (`vdev`) streams the same 32-byte frames a wristband would send.

## Run it

```bash
docker compose up --build
```

Then open <http://localhost:3000>. The first start takes about 20 seconds: the virtual device sends 14 days of history so that six of the seven crew members already have a learned baseline (the seventh is on day 4 of learning).

If port 5432 is taken on your machine: `POSTGRES_PORT=5433 docker compose up --build`.

## Deploy on a server

One script does everything. The server needs Docker Engine with the Compose plugin, about 45 GB of free disk while the datasets are prepared, and (for HTTPS) a domain name that points to it with ports 80 and 443 open.

```bash
cp .env.example .env        # set DOMAIN_URL, COMPOSE_PROJECT_NAME, ACME_EMAIL
# optional: put the three dataset archives into data_archives/ (otherwise they are downloaded, 3.6 GB)
./deploy.sh
```

`./deploy.sh` runs these steps in order and stops with a clear message if one fails:

1. checks Docker, `.env` and disk space (it does not install or start Docker);
2. takes the datasets from `data_archives/` or downloads them, extracts them, downloads the NASA files and converts everything to the formats the code uses;
3. trains the XGBoost pattern classifier and checks that the virtual devices raise no alert on normal data;
4. makes the prepared files readable for the containers;
5. builds the images and starts Postgres, the backend (it creates the database schema), the virtual devices, the client, nginx and Traefik;
6. waits until the stream is live, checks the whole chain and prints the address.

The first run takes 20–30 minutes, most of it data preparation. Running it again is safe: finished slow steps are skipped.

```
Traefik (HTTPS, certificates)  ─▶  nginx (HTTP, port 80)  ─▶  backend   for /api/*  (REST and WebSockets)
                                                         └─▶  client    for everything else
```

Only Traefik is reachable from outside. With `TRAEFIK_MODE=external` the script uses a Traefik that already runs on the server (Docker network `traefik`, certificate resolver `letsencrypt`) instead of starting its own.

| Command | What it does |
|---|---|
| `./deploy.sh incident hypoxia [crew] [severity]` | start a demo incident on demand; `./deploy.sh incidents` lists them |
| `./deploy.sh speed 60` | clock rate of the virtual devices (1, 10 or 60) |
| `./deploy.sh status` | containers, stream state, level of each crew member |
| `./deploy.sh reset` | wipe the readings and replay the history |
| `./deploy.sh up` / `down` / `logs [service]` | start without touching the data / stop / follow logs |
| `./deploy.sh train --force` | redo the data preparation and the training |

## Try the demo

Open the **Demo** panel in the bottom corner.

| Do this | You see |
|---|---|
| Speed ×60, scenario `hypoxia` | Background turns yellow (Watch), then amber with a banner (Alert), then the red Critical screen with the reason and the steps. About 15 seconds |
| Scenario `exercise` | Heart rate climbs past 130 and the card says "Exercise". No alert: effort is not an anomaly |
| Scenario `sensor_off` | Cards show "No data". No alert: a missing reading is never shown as a good one |
| Scenario `hypercapnia` at ×60 | Cabin CO₂ passes the 3.0 mmHg limit; the alert is for the whole crew |
| Reset | Everything starts again from a clean history |

Other scenarios: `tachycardia_rest`, `bradycardia`, `fever_like`, `depressurization`, `motion_artifact`.

## How it works

```
vdev  ──32-byte frames, 1 Hz──▶  backend  ──REST + WebSocket──▶  client
(virtual wristbands)            (pipeline)                      (Next.js)
```

1. **Minute values.** Seconds are rolled into one value per minute; seconds with poor signal are left out.
2. **Context.** Each minute is `sleep`, `rest`, `active` or `off`, from wrist motion and heart rate. A fast heart rate during exercise is not judged against the resting norm.
3. **Personal norm.** For each person, metric, context and time of day: the median and a robust spread of their own last 14 days.
4. **Levels.** Watch and Alert when a value stays outside the personal range; fixed safety limits apply from the first minute, before any norm is learned. Cabin CO₂ uses the NASA-STD-3001 limit of 3 mmHg as a one-hour mean.
5. **Alert.** One incident per person with the primary metric, the pattern name, the reason and the steps to take. The pattern is named by a small XGBoost classifier (a rule is the fallback); the text is a template filled with the alert's own numbers, and the steps come from [`docs/actions.yaml`](docs/actions.yaml), written by people.

Every formula and number: [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) (in Russian).

## Data

| Source | Used for |
|---|---|
| NASA OSDR Environmental Data App — ISS cabin CO₂, mission RR-12 | the cabin CO₂ channel in the stream (real telemetry, looped) |
| NASA OSDR Environmental Data App — daily radiation dose, RR-12 | the Radiation page (real ISS dose, measured April–May 2019) |
| NASA-STD-3001 Vol. 2 | cabin CO₂ limit |
| PPG-DaLiA, sleep-accel | fitting and testing the context rule (`sleep` / `rest` / `active`) |
| BIDMC PPG and Respiration | noise parameters for simulated SpO₂ and breathing |

The crew's vital signs in the demo are **simulated**; the abnormal episodes are simulated too. Licenses and citations: [`docs/DATA_LICENSES.md`](docs/DATA_LICENSES.md). Every number we report and the script that produces it: [`docs/DATA_NOTES.md`](docs/DATA_NOTES.md). Use of AI: [`docs/AI_USE.md`](docs/AI_USE.md).

## Measured

| What | Result | Script |
|---|---|---|
| False alarms on normal data | 0 incidents in 315 simulated person-days | `python -m ml.eval_false_alarms --seeds 3` |
| Context rule on people it was not fitted on (real recordings) | 88 % by day (5 people), 81–85 % by night (9 nights) | `python -m ml.calc_context` |
| Pattern classifier on simulated people it was not trained on | macro-F1 0.99 over 8 classes | `python -m ml.train_xgb` |
| Time to each level per scenario | hypoxia: Watch at minute 5, Alert at 8, Critical at 12 | `python -m ml.eval_scenarios` |

The abnormal classes are simulated, so the last two rows say how well Vigil recognises **our models** of each deviation, not real patients. Details and limits: [`docs/DATA_NOTES.md`](docs/DATA_NOTES.md).

## Layout

```
vigil/
  core/       the pipeline: no network, no database (shared with the offline scripts)
  backend/    Litestar + asyncpg: ingest, live updates, REST
  vdev/       virtual device: signal generator, scenarios, NASA CO₂ profile
client/       Next.js interface
nginx/        reverse proxy between Traefik and the backend / client
deploy.sh     one script for a new server: data, training, start, checks, demo incidents
ml/           data preparation and evaluation scripts
docs/         implementation notes, data notes, licenses, allowed actions
tests/
```

## Develop

```bash
uv sync --group ml
docker compose up -d postgres
uv run uvicorn vigil.backend.app:app --reload          # :8000
uv run uvicorn vigil.vdev.app:app --port 8100          # virtual device
cd client && npm ci && npm run dev                     # :3000
uv run pytest && uv run ruff check
```

API reference (Swagger): <http://localhost:8000/api/v1/docs/swagger>

| Variable | Default |
|---|---|
| `VIGIL_DATABASE_URL` | `postgresql://vigil:vigil@localhost:5432/vigil` |
| `VIGIL_VDEV_URL` | `http://localhost:8100` (fixed to `http://vdev:8100` in Compose) |
| `VIGIL_ACTIONS_FILE` | `docs/actions.yaml` |
| `VIGIL_CORS_ORIGIN` | `*` |
| `VDEV_INGEST_URL` | `ws://localhost:8000/api/v1/ingest` |
| `VDEV_BACKEND_URL` | `http://localhost:8000/api/v1` |

## License

Apache-2.0. See [`LICENSE`](LICENSE).
