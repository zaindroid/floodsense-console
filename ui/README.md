# UI

The insurer desk and a plain citizen page for FloodSense EU. Vite, React, and TypeScript. This `ui/src` console is the product UI. `ui/app` and `ui/mock` are not part of it. The screen runs from fixtures shaped like the Zetaris seed views. Those views are on main (`v0.1.0`). A row stays a fixture unless `VITE_API_URL` returns that view.

Owner: Zain. Mihir landed the console.

## Run

From the repo root, `python tasks.py init-env` copies `ui/.env.example` when `ui/.env` is missing. Or, in this directory:

```powershell
Copy-Item .env.example .env
npm install
npm run dev
```

```bash
cp .env.example .env
npm install
npm run dev
```

`npm run build` typechecks, then builds. npm runs the `&&` in that script through `cmd.exe` on Windows, where `&&` works. Do not paste that script into PowerShell 5, which has no `&&`.

`npm run lint` is `tsc --noEmit`. `npm test` runs Vitest. `python tasks.py test` runs that suite from the repo root after the Python tests.

Compose publishes the dev server on host port 15173 (container port 5173). `VITE_API_URL` defaults to `http://localhost:18000`, which is the API as the browser sees it. `VITE_API_TIMEOUT_MS` is optional and defaults to 1500.

Do not put tokens in `ui/.env`. Vite exposes every `VITE_*` value to the browser. The NVIDIA provider key lives only in Nightshift's Providers tab. This package does not call Nightshift or Zetaris.

## What the screen does

The header has the product name, Citizen and Insurer links (`#/citizen`, `#/insurer`), a light/dark control, a notification bell, and an account icon.

A collapsible left nav lists that desk's pages, one task per page. Citizen: Overview, My area, What to do, Evidence (`#/citizen`, `#/citizen/area`, `#/citizen/actions`, `#/citizen/evidence`). Insurer: Approvals, Portfolio, Sites / map, Alerts, Review (`#/insurer/approvals` and the same pattern). `#/insurer` and an empty hash open Approvals while the decision is pending, else Portfolio.

Approve, Edit, and Reject live only on Approvals, in a sticky bar. Review has the Causal chain, Skeptic, and Judge tabs.

Citizen What to do lists the answer's suggested actions only after an insurer approves them, so a pending action is never shown to a citizen.

The #36 hashes still work: Place and Rain open My area, Map and Point open Sites / map, Overview and Book open Portfolio, and Sources opens Review. An unknown page opens that desk's home. The hash is rewritten in place (`history.replaceState`) to the page it resolved to, so an old link leaves no extra history entry.

The nav starts collapsed at 980px or narrower. The Evidence drawer is mounted once on the shell and closes on a page change. A thin replay strip shows the date, point, and whether playback is running, with Stop while it plays. Simulate alert is on Alerts.

An Ask FloodSense launcher sits at the bottom right. Its popup is closed at start, is never opened by a route change, and does not push the page. Esc or the close button closes it. Focus goes back to the launcher when it was inside the popup. The popup header says the answer is a replay and when it was cached. It shows the reviewed answer with numbered citations, and the query trace is behind How I got this. It has no question box: it reads the fixture answer and does not call a model or `/runs`. Citizen Overview has See the reviewed answer, which opens the same popup.

The theme key is `floodsense-theme`, the same string in `index.html` and `src/lib/theme.ts`. The first visit follows the system preference and does not write `localStorage` until the control is used, so a later OS change still applies until then. The account control is a stub: it does not collect credentials.

Demo dates, the simulation window, map bounds, band cuts, the 8 km drill-down radius, fixture detail strings, and the optional view paths live in `src/config/scenario.ts`.

The insurer desk shows:

- a schematic Valencia map with one marker per `point_id`
- a replay-date slider across the discharge dates
- a drill-down that names the `discharge_daily` columns and the hazard columns when that day is in the extract
- an evidence drawer, “Why this source”, opened from the drill-down
- a causal chain, Skeptic notes, Judge scores, and approve / edit / reject

Approve, edit, and reject stay in the browser. Nothing is sent.

The alert control steps 28–31 Oct 2024 and adds a notice if modelled discharge crosses 80 m³/s (`SIMULATED_ALERT_M3S` in `src/config/scenario.ts`). That threshold is a demo line for the map. It is not the Watchers anomaly, which is 100 m³/s (`anomaly_discharge` in `agents/floodsense_agents/governance.py`). `warning_level` in the hazard rows is null, and the notice is labelled a simulation.

The citizen page uses the same points, dates, and discharge series, in plain language, without the review controls.

### Look and citizen Overview

Colours, type, and cards follow the team's mock UI (`Hackathon-Monorepo-mock-ui`); the tokens are at the top of `src/styles/global.css`. Citizen Overview asks "Is my area at risk, and why?": place search and chips, a Risk right now card (discharge band and m³/s for the replay date, the answer's serving label, and the Judge overall score as 0.00–1.00, as on the other pages; there is no separate risk score), three numbered Why sentences with numbered source chips, What should I do (approved steps only), a river-gauge map, and gauge cards. Table and column names in claim text are reworded by `src/lib/plain.ts` on citizen and insurer pages; the original sentence stays under Technical detail or in the hover text. The answer serving line appears once, in the replay strip. Sources and licences are one collapsed footer. Under 760px the nav is a drawer (backdrop, Escape, closes after a pick) and the header is two rows.

### Agent pipeline and document retrieval

`src/components/AgentPipeline.tsx` (model: `src/lib/pipeline.ts`) draws any run body (live, cache or replay) as Scope → Watchers → Memory → Investigator ⇄ Skeptic → Exposure → Playbook → Judge → Human approval. Each node shows its status, the summed trace `latency_ms`, its lane, how many times it ran, and the trace summary. The revise loop appears when `revise_rounds` > 0 and the repair loop when `repair_rounds` > 0. Badges:

- "Zetaris · N queryIds" on SQL-lane steps.
- "Nightshift · …" only when the step's `provider` or the run's `request.llm_provider` is `nightshift`. Any other nvidia id is "NVIDIA Nemotron · …", and every other id is shown as stored.
- "H-MEM recall · N" only when the memory step recalled at least one finding.
- "World Model" with the last board (H1 supported / not_supported …).
- "pgvector + Zetaris JDBC" when layer (c) citations exist.

The reveal is CSS and stops under `prefers-reduced-motion`. `src/components/RetrievalPanel.tsx` (model: `src/lib/retrieval.ts`) shows the layer (c) query, the passages per claim (title, page, publisher, licence, quote, attribution), the Zetaris query id that hydrated them, and the Judge's verdict, including "Flagged by Judge". Both views appear in the Ask popup under "How I got this". On insurer Review they form the "Causal chain" header, which reads `VITE_REPLAY_RUN_ID` or, failing that, the bundled recording `src/fixtures/run_f16733274f1c.json`. That header carries a "Recorded run · not live" badge and a note that says when it fell back to the bundled recording. Claim C2 in that recording is a known degenerate agent output and is shown as recorded.

### Disaster replay

Page `replay` on both desks, right after Now. Two events:

- Ahr valley, 13–16 Jul 2021 (EMSR517). The page reads `GET /views/hazard_timeline?event_id=EMSR517&source=replay` (Zetaris `floodsense_seed`, migrations 051/052, even when `FF_LIVE_DATA` points the app at the live views) and uses the result when it holds AHR points inside the window, badged "Replay · Zetaris floodsense_seed · not live". Otherwise it uses `src/fixtures/ahr_2021.json`, badged "Bundled modelled data (Open-Meteo, CC BY 4.0), not from Zetaris". `VITE_AHR_SOURCE=fixture` forces the fixture. The fixture holds Open-Meteo Flood API (GloFAS v4 daily discharge) and Historical Weather API (ERA5 hourly precipitation) data for Altenahr, Bad Neuenahr-Ahrweiler and an upper-Ahr point, fetched 2026-10-27, CC BY 4.0 Open-Meteo.com, modelled values.
- Valencia, 28–31 Oct 2024 (EMSR773), from the loaded `hazard_timeline` rows.

The page has an hourly scrubber, day buttons and Play/Pause. Under reduced motion Play steps once a second, and the time readout is not announced while playing. Each point shows its rain and discharge at the scrubbed time. Because GloFAS discharge is daily, a crossing of the 100 m³/s Watchers line is dated by day ("Crossed the line on 14 Jul 2021 (daily value)"), never by hour. "Ask the agents about this moment" opens Ask pre-filled and sends `context` {page, event_id, replay_date, point_id, place}. Everything is labelled "Replay of … · not live".

### Ask screen context

Every Ask request carries `context` from `screenContext()` in ConsoleContext (role, page, selected point and place), merged with a page's own context. It is added only by `withAskContext` (`src/lib/askContext.ts`); `VITE_ASK_CONTEXT=off` stops sending it. The agents' `RunRequest` ignores unknown fields (pydantic default).

### River-gauge map

`GET {VITE_API_URL}/views/gauge_levels` (Zetaris `floodsense.gauge_levels`, PEGELONLINE Rhine/Mosel gauges). The browser never calls PEGELONLINE. Numbers sent as strings are coerced. Markers sit at the view's `lat`/`lon` (fallback: `STATION_POSITIONS` in `src/lib/gauges.ts`), coloured by `band` (below, near, above, unknown = No threshold). Cards show level, `trend_cm_h` as rising/steady/falling, MW and MHW, and the measured time. Each row's origin comes from `source`: a seed, fixture or replay stamp is labelled Seed or Fixture (dashed marker), never Live. A row with `is_stale` true (or missing) is labelled Stale. Live appears only for a live-source, fresh row, and the map chip says Live only when every gauge is. The view is re-read every 5 minutes; a failed or empty read is retried, not cached. An empty or unreachable view says "No live gauge readings yet". No sample gauges are drawn. Tiles: OpenStreetMap via Leaflet.

## Fixture and live

On load the screen paints the fixtures, then checks the API.

1. `GET ${VITE_API_URL}/health` — the API on `main` returns `{"status":"ok"}`.
2. If that succeeds, it tries a JSON array at each of these paths:
   - `/views/discharge_daily`
   - `/views/hazard_timeline`
   - `/views/exposure_join`
   - `/views/provenance`

A 200 body is used only when every element has the view columns below (numbers as JSON numbers, `in_footprint` as a boolean). `warning_level` may be missing; a missing value is null. `discharge_m3s` on hazard rows may be null. An empty JSON array is an empty view response, not a silent return to the fixture. A 404, a network error, a failed health check, or a different shape keeps the fixture. `GET /health` on its own does not change the label. The top bar has one honesty chip: **Preview** while any view is a fixture or seed, **Cached** when every view is live but the answer is cached or replayed, and **Live** only when every view and the answer are live. Opening the chip shows the answer serving line and each view's origin. Approvals and Review also show the serving line inline above the answer, so a replay is labelled without opening the chip. The same per-view list is under Data origin on Portfolio. The view list, map caption, and citizen caption use **Fixture**, **Seed**, or **Live**. Seed means the view response is seed-stamped (`source` starts with `seed:`); an adopted sibling with no stamp takes that seed label too. Live is a response whose rows each carry a source stamp that does not start with `seed:`, and none of those rows has `synthetic` equal to `yes`. An empty array stays empty and is labelled Fixture, not Live. Rows with no source stamp stay Fixture; the caption says unstamped. A seed discharge response still marks an unstamped sibling Seed. A live discharge response does not mark that sibling Live. `exposure_join` with `synthetic` equal to `yes` (migration 018) is Seed, including when discharge is Live. Fixture, seed, cache, and replay chrome do not say “live” and do not use the green live colour. The answer serving line under the chip says **cached at HH:MM UTC · replay**.

`ts_utc` with no zone is treated as UTC. Provenance `source_url` and citation `source_url` must be `http:` or `https:`. Other schemes are rejected and are not put in an `href`.

Those paths are optional reads, not the run contract. This desk does not call `/runs`. The API serves `/health`, `/config`, `/runs`, and approval. A health check alone does not select Live. CORS must allow the UI origin before a browser can read even `/health`; a blocked call stays on the fixture.

The reviewed answer is always the fixture in `ui/src/fixtures/answer.json`. It uses the shared contract (`served_from`, `cached_at`, claims, citations, evidence, judge, playbook action). `served_from` is `replay` and `cached_at` is `2026-10-24T14:32:00Z`, so the serving line under the chip reads **cached at 14:32 UTC**. Cache and replay are never labelled live. `query_id` values in that file are fixture ids, not Zetaris query ids, and the SQL is not executed.

Skeptic notes in `ui/src/fixtures/console.ts` are display copy for this screen. The outcome names (`held`, `challenged`, `revised`) live in `src/types/skeptic.ts` and are not a shared contract yet. They are not an agent payload and they do not choose a Nightshift lane. The Judge fixture stores `meterless/deep`. The Judge tab shows a routing name as stored. A concrete Nightshift id is labelled "answered by" that model, using the names in the table at the top of `docs/architecture/c4.md`. Super VL answers both lanes today, so it is not shown as one lane. Lightning is not shown as `meterless/fast`. This UI does not call a model. Skeptic counter-checks that quote fixture numbers are hidden while discharge rows are live.

`src/types/contract.ts` is a type-only re-export of `contracts/typescript`. Compose builds the UI image from `./ui` only, so that path is outside the image. Vite drops `import type` at build time, and `npm run dev` in the container does not need the file. `tsc` from a full checkout still resolves it. Do not copy `contracts/` into `ui/`.

## How the fixtures map to the views

Numbers and column names were copied on 24 Oct 2026 from `feat/zetaris-data-sync` (PR #12’s branch) and the prep CSVs on `feat/ingestion-sources-terms`. This branch does not modify those branches. When the views change, replace the JSON under `ui/src/fixtures/` and keep the column names.

| Fixture | View | Columns |
| --- | --- | --- |
| `discharge_daily.json` | `floodsense_seed.discharge_daily` (migration 012; live twin is migration 004) | `point_id`, `date`, `discharge_m3s`, `source` |
| `hazard_timeline.json` | `floodsense_seed.hazard_timeline` for 28–30 Oct 2024 (migration 013; live twin is 007) | `point_id`, `ts_utc`, `rain_mm`, `discharge_m3s`, `warning_level` |
| `exposure_join.json` | `floodsense_seed.exposure_join` (migration 016; live twin is 014) | `policy_id`, `site_id`, `lat`, `lon`, `in_footprint`, `sum_insured_eur`, `segment` |
| `provenance.json` | `floodsense_seed.provenance` (migration 017; live twin is 015), six datasets | `dataset`, `source_url`, `publisher`, `licence`, `attribution`, `fetched_at` |
| `valencia_points.json` | prep CSV `ingestion/prep/valencia_points.csv`, not a view | joins to discharge on `point_id` |

`discharge_daily.source` in the seed extract is `seed:open-meteo-flood-glofas`. The live view stamps the same series as `open-meteo-flood-glofas`. The evidence drawer says the series is modelled GloFAS only when the source stamp is that one. A fixture notice is built from the loaded rows and is removed when those rows are live. `fetched_at` is the prep `accessed_at` date written as midnight UTC, which is what the provenance view does when it casts that date to a timestamp. The provenance fixture is the six migration 017 datasets (EMSR773, OSM sites, the synthetic portfolio, Open-Meteo Flood, Open-Meteo historical rain, AEMET). PEGELONLINE and DWD prep rows are not in that view. Source stamps map to those datasets by a fixed table, not by searching for the word “flood”.

The discharge figures are the frozen Open-Meteo Flood (GloFAS) copy from migration 012: VAL01–VAL08, 20 Oct–5 Nov 2024, modelled, not observed. Neighbouring points can share a value because Open-Meteo snaps them to a 0.05° cell. The portfolio behind `exposure_join` is synthetic.

After PR #12 is on `main`, Zetaris has the views. This UI still will not read Zetaris itself. Point `VITE_API_URL` at an API that serves the arrays above, or keep the fixtures until that route exists. The serving line stays on the replay fixture until a runs API returns an `Answer` with its own `served_from` and `cached_at`.

`compose.yaml` is unchanged. The UI container still runs `npm run dev` on port 5173.
