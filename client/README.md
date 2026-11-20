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

## Languages

UI copy lives in `src/i18n/` — one dictionary per language (`en.ts` defines the shape, `ru.ts` is typed against it).
The switcher in the sidebar stores the choice in `localStorage` (`vigil.locale`); without one, the browser language is used if supported.

To add a language: copy `src/i18n/en.ts` to `src/i18n/<code>.ts`, translate it (`export const xx: Dict = { … }` — a missing key fails
the build), and add it to `LOCALES` in `src/i18n/index.tsx`. Sentences are functions, so word order, plurals
(`Intl.PluralRules`, see `ru.ts`) and cases are up to each language.

The server writes alert text and Ask Vigil answers in English only. Locales with `serverText: false` use the client's
own templates for alert text instead; Ask Vigil answers stay in English.
