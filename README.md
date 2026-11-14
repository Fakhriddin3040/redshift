# Vigil backend

Health-monitoring server for astronaut wearables (NASA Space Apps 2026). It accepts
32-byte device frames over WebSocket, rolls them into per-minute values, learns each
crew member's personal norm, sets the status level, opens incidents and serves it all
over REST and WebSocket.

Spec: `TASK.md` (server TZ). This repo is the backend only.
How it works, step by step with every formula and number: [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).

## Layout

```
vigil/
  core/       pure pipeline, no network or DB (shared with offline ML)
    frame.py        pack / unpack / CRC-16/CCITT-FALSE, frame types 1 and 2
    minute.py       second frames -> Minute, ppCO2
    context.py      off / sleep / rest / active
    baseline.py     personal norm cells (median, MAD, sigma floor, warm-up, fallback)
    levels.py       hard thresholds, z-runs, cabin environment, hysteresis
    pipeline.py     CrewState.on_minute(): everything after a minute closes
    thresholds.py   every tunable constant
  backend/    Litestar + asyncpg
    schema.sql      created on startup (no migrations), seeds 7 crew members
    hub.py          in-memory runtime: ingest checks, minute dispatch, notices, /live
    writer.py       ordered write-behind queue, retries every 1 s if Postgres is down
    views.py        JSON for /today, /metric, /crew
    api/routes.py   HTTP + WebSocket routes
```

## Run

```bash
cp .env.example .env
docker compose up --build          # postgres + backend on :8000
```

Locally:

```bash
uv sync
docker compose up -d postgres
uv run uvicorn vigil.backend.app:app --reload
```

Swagger: <http://localhost:8000/api/v1/docs/swagger>

## API (`/api/v1`)

| Method | Path |
|---|---|
| WS | `/ingest` (binary frames) |
| WS | `/live?crew=1` |
| GET | `/crew`, `/crew/{id}/today`, `/crew/{id}/metric/{m}?range=1h\|24h\|7d` |
| GET | `/crew/{id}/alerts?open=1` |
| POST | `/alerts/{id}/ack` |
| GET/POST | `/sim/state`, `/sim/scenario`, `/sim/speed`, `/sim/reset` (forwarded to vdev) |
| GET | `/health` |

## Configuration

| Variable | Default |
|---|---|
| `VIGIL_DATABASE_URL` | `postgresql://vigil:vigil@localhost:5432/vigil` |
| `VIGIL_VDEV_URL` | `http://localhost:8100` |
| `VIGIL_OLLAMA_URL` | empty (LLM off) |
| `VIGIL_PATTERN_MODEL` | `ml/models/pattern.json` |
| `VIGIL_ACTIONS_FILE` | `docs/actions.yaml` |
| `VIGIL_CORS_ORIGIN` | `*` |

## Tests

```bash
uv run pytest
```

## License

Apache-2.0
