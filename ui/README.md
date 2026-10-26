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

The header has the product name, Citizen and Insurer links (`#/citizen`, `#/insurer`), a light/dark control, a notification bell, and an account icon. A collapsible left nav lists that desk's pages. Citizen: Overview, Place, Rain (`#/citizen/place`, `#/citizen/rain`). Insurer: Overview, Map, Point, Book, Review, Sources (`#/insurer/map` and the same pattern). An empty hash opens the insurer overview. An unknown page opens that desk's overview. The nav starts collapsed at 980px or narrower. Each page still shows the current citizen page or insurer desk. A thin replay strip shows the date, point, and whether playback is running. A Replay answer chip at the bottom right reads the fixture answer and does not call a model. The theme key is `floodsense-theme`, the same string in `index.html` and `src/lib/theme.ts`. The first visit follows the system preference and does not write `localStorage` until the control is used, so a later OS change still applies until then. The account control is a stub: it does not collect credentials.

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

## Fixture and live

On load the screen paints the fixtures, then checks the API.

1. `GET ${VITE_API_URL}/health` — the API on `main` returns `{"status":"ok"}`.
2. If that succeeds, it tries a JSON array at each of these paths:
   - `/views/discharge_daily`
   - `/views/hazard_timeline`
   - `/views/exposure_join`
   - `/views/provenance`

A 200 body is used only when every element has the view columns below (numbers as JSON numbers, `in_footprint` as a boolean). `warning_level` may be missing; a missing value is null. `discharge_m3s` on hazard rows may be null. An empty JSON array is an empty view response, not a silent return to the fixture. A 404, a network error, a failed health check, or a different shape keeps the fixture. `GET /health` on its own does not change the label. The header pill, origin banner, map caption, and citizen caption use **Fixture**, **Seed**, or **Live**. Seed means the view response is seed-stamped (`source` starts with `seed:`); an adopted sibling with no stamp takes that seed label too. Live is a response whose rows each carry a source stamp that does not start with `seed:`, and none of those rows has `synthetic` equal to `yes`. An empty array stays empty and is labelled Fixture, not Live. Rows with no source stamp stay Fixture; the caption says unstamped. A seed discharge response still marks an unstamped sibling Seed. A live discharge response does not mark that sibling Live. `exposure_join` with `synthetic` equal to `yes` (migration 018) is Seed, including when discharge is Live. Fixture, seed, cache, and replay chrome do not say “live” and do not use the green live colour. The replay answer banner says **cached at HH:MM UTC · replay**.

`ts_utc` with no zone is treated as UTC. Provenance `source_url` and citation `source_url` must be `http:` or `https:`. Other schemes are rejected and are not put in an `href`.

Those paths are optional reads, not the run contract. This desk does not call `/runs`. The API serves `/health`, `/config`, `/runs`, and approval. A health check alone does not select Live. CORS must allow the UI origin before a browser can read even `/health`; a blocked call stays on the fixture.

The reviewed answer is always the fixture in `ui/src/fixtures/answer.json`. It uses the shared contract (`served_from`, `cached_at`, claims, citations, evidence, judge, playbook action). `served_from` is `replay` and `cached_at` is `2026-10-24T14:32:00Z`, so the insurer banner reads **cached at 14:32**. Cache and replay are never labelled live. `query_id` values in that file are fixture ids, not Zetaris query ids, and the SQL is not executed.

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

After PR #12 is on `main`, Zetaris has the views. This UI still will not read Zetaris itself. Point `VITE_API_URL` at an API that serves the arrays above, or keep the fixtures until that route exists. The answer banner stays on the replay fixture until a runs API returns an `Answer` with its own `served_from` and `cached_at`.

`compose.yaml` is unchanged. The UI container still runs `npm run dev` on port 5173.
