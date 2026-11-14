# Vigil client

Next.js (App Router) front end for the Vigil backend. Design: `../Space Apps Challenge Design/Vigil v2.dc.html`
plus the changes in `../DESIGN_TZ.md` (night theme, Geist, level backgrounds, Critical screen).

## Run

```bash
cp .env.example .env.local      # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_CREW_ID
npm install
npm run dev                     # http://localhost:3000
```

The backend must be running (`docker compose up` in the repo root, API on :8000).

## Screens

| Route | Data |
|---|---|
| `/` Today | `GET /crew/{id}/today` every 10 s + `WS /live` (ticks, alert, level, baseline) |
| `/metric/[m]` | `GET /crew/{id}/metric/{m}?range=1h\|24h\|7d` — norm band, limits, deviations, gaps, context ribbon |
| `/device` | `today.device`, 24 h presence from `/metric`, sensors from card states |
| `/crew` | `GET /crew` |
| `/report` | today cards, `GET /crew/{id}/alerts`, data coverage from `/crew` |
| `/checkin` | stored in the browser (no backend endpoint yet) |
| `/sleep`, `/radiation` | empty states (no backend endpoints yet — BE-6a, BE-7) |
| Critical screen | opens over any page when `level = 3` and not acknowledged; Acknowledge → `POST /alerts/{id}/ack` |

Page background follows the server level (`html[data-level]`, `src/app/globals.css`).
Card colors follow each card's own `state`, never the page level.
Notice / banner / Critical copy is built from `pattern` + `metrics` (`src/lib/text.ts`) until the backend fills `text`.

The **Demo** button (bottom right) switches crewmember and drives `/sim/*` (scenario, speed, reset).
