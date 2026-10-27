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

**Live pipeline and HITL (v0.15).** Ask FloodSense starts runs with `POST /runs?wait=false` and follows `GET /runs/{id}/events` (SSE; it falls back to polling `GET /runs/{id}` if the stream drops). The pipeline Scope → Watchers → Memory → Investigator ⇄ Skeptic → Exposure → Playbook → Judge → Human review lights each node on `started` and shows ✓, duration, model (`nemotron-3.5-lightning · Nightshift`, `deterministic`, `SQL · Zetaris`) and a one-line summary on `trace`; Skeptic revise and Judge repair loops are listed. An mm:ss timer and a rotating tip keep a ~6 min run watchable; updates go to an `aria-live="polite"` region. Then the final run is fetched and rendered. A 200 cache/replay answer is labelled "Recorded/cached · not live"; a 429 shows a Retry-After countdown; `failed` and `not_found` show inline errors; a `{kind: "reply", answer}` body is a plain message. Each sentence shows source chips from `citations[].layer` (a = Zetaris query, b = Provenance, c = Document). "Memories used" lists `memory_used` at run level only, never per sentence. The Approvals page loads the newest live run waiting for review (`GET /runs/{id}/approval`, else the packed example) as mock-style cards: action-type chip, title, region, site count, Judge badge, status, draft message, Edit (sends `draft_messages`), reviewer note, Approve/Edit/Reject; 422s show inline. Nothing is sent. Logic: `src/lib/liveRun.ts`, `src/lib/hitl.ts`, `src/api/liveRun.ts`.

The header has the product name, Citizen and Insurer links (`#/citizen`, `#/insurer`), a light/dark control, a notification bell, and an account icon.

A collapsible left nav lists that desk's pages, one task per page. Citizen: Overview, My area, What to do, Evidence (`#/citizen`, `#/citizen/area`, `#/citizen/actions`, `#/citizen/evidence`). Insurer: Approvals, Portfolio, Sites / map, Alerts, Review (`#/insurer/approvals` and the same pattern). `#/insurer` and an empty hash open Approvals while the decision is pending, else Portfolio.

Approve, Edit, and Reject live only on Approvals, in a sticky bar. Review has the Causal chain, Skeptic, and Judge tabs.

Citizen What to do lists the answer's suggested actions only after an insurer approves them, so a pending action is never shown to a citizen.

The #36 hashes still work: Place and Rain open My area, Map and Point open Sites / map, Overview and Book open Portfolio, and Sources opens Review. An unknown page opens that desk's home. The hash is rewritten in place (`history.replaceState`) to the page it resolved to, so an old link leaves no extra history entry.

The nav starts collapsed at 980px or narrower. The Evidence drawer is mounted once on the shell and closes on a page change. A thin replay strip shows the date, point, and whether playback is running, with Stop while it plays. On pages that show the selected event (Replay, Sites / map, and Portfolio on Valencia) the date and point follow that event (`replayBarView` in `src/lib/events.ts`), e.g. "14 Jul 2021 · AHR01 Altenahr" on Ahr. Simulate steps only the Valencia date, so on an Ahr page the strip shows no Playing/Paused; while the Valencia simulation runs it says "Valencia simulation playing" and keeps Stop. Simulate alert is on Alerts.

An Ask FloodSense launcher sits at the bottom right. Its popup is closed at start, is never opened by a route change, and does not push the page. Esc or the close button closes it. Focus goes back to the launcher when it was inside the popup. The popup header says the answer is a replay and when it was cached. It shows the reviewed answer with numbered citations, and the query trace is behind How I got this. It has no question box: it reads the fixture answer and does not call a model or `/runs`. Citizen Overview has See the reviewed answer, which opens the same popup.

The theme key is `floodsense-theme`, the same string in `index.html` and `src/lib/theme.ts`. The first visit follows the system preference and does not write `localStorage` until the control is used, so a later OS change still applies until then. The account control is a stub: it does not collect credentials.

Demo dates, the simulation window, map bounds, band cuts, the 8 km drill-down radius, fixture detail strings, and the optional view paths live in `src/config/scenario.ts`.

The insurer desk shows:

- a Leaflet + OpenStreetMap map (Sites / map, `src/components/MapPanel.tsx`) for the selected event: Valencia 2024 (EMSR773, VAL01-VAL08 from `valencia_points`) or Ahr 2021 (EMSR517, AHR01-AHR04 Altenahr, Bad Neuenahr-Ahrweiler, Schuld, Dernau, the `floodsense_seed` rows from `ingestion/prep/ahr_hazard.py`). Markers sit at the rows' lat/lon, are coloured by discharge band, carry a permanent place label (code and value in the popup), and fit the event's bounds. Exposed sites are a toggleable layer for EMSR773; Ahr has no insured book, so the toggle is off and Portfolio says so. There is no river line.
- a replay-date slider across the discharge dates
- a drill-down that names the `discharge_daily` columns and the hazard columns when that day is in the extract
- an evidence drawer, “Why this source”, opened from the drill-down
- a causal chain, Skeptic notes, Judge scores, and approve / edit / reject

Approve, edit, and reject stay in the browser. Nothing is sent.

The alert control steps 28–31 Oct 2024 and adds a notice if modelled discharge crosses 80 m³/s (`SIMULATED_ALERT_M3S` in `src/config/scenario.ts`). That threshold is a demo line for the map. It is not the Watchers anomaly, which is 100 m³/s (`anomaly_discharge` in `agents/floodsense_agents/governance.py`). `warning_level` in the hazard rows is null, and the notice is labelled a simulation.

The selected event is one value in `ConsoleContext` (`eventId`, default EMSR517 so Replay opens on Ahr; the Ahr map date and point live there too, and the Ask `context` carries the active event, date and point), shared by Replay, Sites / map and Portfolio. The header subtitle is the product tagline "Explainable flood risk for Europe" (`headerSubtitle` in `src/lib/events.ts`). The context strip under the header (`replayBarView`) says "Live · Europe live watch" on Now, "Live data" on citizen Overview, My area, What to do and Evidence (or "Viewing: … (replay of a past event)" when the chosen place is a replay place), and "Viewing: Valencia flood · 29 Oct 2024 (replay of a past event)" (or the Ahr event) on Replay and Sites / map. Other pages show no strip, except Stop while the simulation plays and the serving line on Approvals and Review. Citizen Now has one Europe live-watch map and "Places to watch"; insurer Now keeps the dense page (see "Citizen live-first").

The citizen side is live-first (see "Citizen live-first" below). The Valencia points, dates and discharge series appear there only when a Valencia replay place is chosen, and on Replay.

### Citizen live-first

- **Places.** `src/lib/places.ts` builds the citizen place list from every live-watch source (26 PEGELONLINE gauges from `/views/gauge_levels`, 11 GloFAS points from `/views/eu_watch`, the 8 Valencia points from `/views/hazard_now`) plus the Valencia (VAL01-VAL08) and Ahr (AHR01-AHR04) replay places. Search folds case and accents and matches name, river, country or point id ("koln", "danube", "hungary", "paiporta"). The views are read once and shared for 5 minutes (`src/hooks/useLiveWatch.ts`). The chosen place is `placeId` in ConsoleContext; null means "Right now, anywhere in our watch", the default.
- **Plain status** (`statusView` in `src/lib/places.ts`). No status is red or says "Warning": a gauge at or above MHW reads "Above mean high water" (amber), the near band "Close to mean high water". MHW is described as the long-term mean high water (not a warning level), never as an official threshold. Gauge Watch follows `ingestion/feeds/pegel_poll.py`: the level is within 25 % of the MW..MHW span below MHW. GloFAS bands read "Watch (model)" or "Elevated (model)" (at least 2× the past-30-day median) in amber, never red. Valencia points read "Above 20 m³/s demo line" (neutral) or "Above 80 m³/s demo line" (amber) against `config/scenario.ts`, labelled not official. Each place gets one calm sentence that keeps its name's casing (`calmSentence`), a "Measured" (gauge) or "Modelled" (model hour or day) time, and its number under Details. Headline counts keep "gauges above mean high water" apart from "model points elevated" (`headlineCounts`).
- **Overview.** The chosen place's "Risk right now" card comes first (or the whole watch, most notable three first), then the place picker (the current choice is always in its short list, `quickPlaces`), then "Elsewhere in our watch", What should I do, and a small "Learn from past floods" card that links to Replay. Ask FloodSense is pre-filled with the chosen place's question.
- **Now (citizen).** It leads with the chosen place, or the most notable one, as a plain status, one sentence and a `[1]` source. Then one Europe map with every source (circles = gauges, diamonds = GloFAS, squares = Valencia) and the legend inside a collapsed "How we colour the map". Then "Places to watch", most notable first. "Updated" shows the oldest fetch time of the loaded views, and Refresh reloads all three views, gauges included.
- **Now (insurer)** is the previous dense page, unchanged (`InsurerNowPage.tsx`): Valencia cards with rain, trend and sparkline, the gauge map and list with MHW bars, the dropped/truncated flags and query id, and the visibility-paused refresh.
- **Review copy.** Citizen answers are not held back. Only the agent-written playbook step of the bundled Valencia 2024 answer waits for a person, and it, with its review status, shows only for a Valencia replay place.
- **My area / What to do** follow the chosen place. Warning links follow its country (`warningCountriesForCountry` in `src/lib/safety.ts`): DE gives the Germany links, ES the Spain links, any other country only the EU-wide Meteoalarm link "Find your national warning service" (`https://meteoalarm.org/en/live/`). No place shows all three groups. The allowlist test pins every URL.
- **Numbered sources.** Every live data point (Overview risk card, Places to watch rows, replay story moments) has a `[n]` badge (`LiveSourceBadge`) that opens the right-side Evidence drawer on that point (`LiveEvidenceView`, model `src/lib/liveEvidence.ts`): the pipeline ("PEGELONLINE REST (WSV) → FloodSense poller every 10 min → Zetaris file store → view floodsense.gauge_levels", or "Open-Meteo Flood API → Zetaris REST table → view floodsense.eu_watch"), the Zetaris query id and `x-executed-at` from the view response headers, the measured time, licence and upstream link, and "Not an official warning". In Ask, "Memories used" opens the same drawer with the run's H-MEM memories.
- **Evidence** lists the live views behind the chosen place (query id, fetch time, place count) before the past-event evidence.
- **Replay (citizen)** opens on "What happened": 3-5 moments derived from the replay rows (`storyMoments` in `src/lib/story.ts`: the heaviest rain hour, the first crossings of the event's line and always the peak flow, merged into the crossing sentence when they fall on the same point and day), each with a `[n]` source. Daily GloFAS values read "By end of <day>" with no time and sort after any hourly moment that day. Chart, table and step buttons sit behind "Show the data". The chart has an axis line ("rain (mm/h), top ↓ / river flow (m³/s) ↑") and a legend. Insurers keep the full data view.
- **How it works** is role-aware (`humanBox`): citizens read "Insurer alerts are checked by a person before they're sent. Your answers aren't held back."; insurers keep "Human approval".
- **Context strip.** Citizen Overview, My area, What to do and Evidence say "Live data", or "Viewing: … (replay of a past event)" when the chosen place is a replay place. Replay says "Viewing: …" on both desks.

### Look and citizen Overview

Colours, type, and cards follow the team's mock UI (`Hackathon-Monorepo-mock-ui`); the tokens are at the top of `src/styles/global.css`. Citizen Overview asks "Is my area at risk right now?" and is described under "Citizen live-first". Table and column names in claim text are reworded by `src/lib/plain.ts` on citizen and insurer pages; the original sentence stays under Technical detail or in the hover text. The answer serving line appears once, in the replay strip. Sources and licences are one collapsed footer. Under 760px the nav is a drawer (backdrop, Escape, closes after a pick) and the header is two rows.

### Clarity pass (judge-ready)

- No global Preview badge. The citizen Risk right now card leads with a plain status ("Elevated — higher than normal river flow"), then the m³/s figure, then "Checked: 0.89" (the Judge, tooltip "Score from our independent checker agent"). No cache chip on the citizen card.
- What should I do: official guidance, 112 and warning links first; the approval gate is a neutral note ("Personalised advice from our agents is reviewed by a person before it's shown."), then Ask.
- Grounded sources per claim (`src/components/SourceBadges.tsx`, model `src/lib/sources.ts`). Every number badge, on Overview and in the Ask chat, opens that source inline: Zetaris data shows the view, query id and the upstream feed link (Open-Meteo GloFAS; eu_watch as "model, not an official warning"; Open-Meteo weather; PEGELONLINE; exposure_join as "Synthetic insurer portfolio (demo data) · OSM sites"; Copernicus EMS only for footprint fields, using the answer's or run's own event id; seed views say "Seed data"); a document shows title, publisher, page and paragraph, the quote and the source URL from the citation (the manifest URL the agents already copy into `source_url`). Memories read "H-MEM · approved run <id>" or "H-MEM · Demo seed", with the World Model board where present. A legend says "Every sentence links to its source: data via Zetaris, documents, or approved memory."
- How it works (`src/components/HowItWorks.tsx`, page `how` on both desks): router and lanes, the agents, Zetaris data, Nightshift / Nemotron lanes, H-MEM + World Model, RAG (pgvector + NIM nemotron-embed), Redis, human approval. Each box has a status dot from `GET /config` and `GET /system` (`src/api/system.ts`, `src/lib/howItWorks.ts`); a 404 on `/system` leaves those dots "unknown".
- `friendlyError` says "Here is the latest recorded answer" only when one is shown, and strips bare and quoted service hostnames (agents, api, engines, pgvector, redis) and IPv6 with a port.

### Agent pipeline and document retrieval

The pipeline is a compact stepper: one line per agent (status icon, name, status, duration, model chip such as "Nemotron 3.5 Lightning 30B · Nightshift fast lane" from the trace `lane`), details collapsed until clicked, loop chips ("Skeptic revise ×1", "Judge repair ×1") and World Model hypotheses on one line. In the Ask chat it streams open while agents work and folds to one summary line once the answer arrives ("8 agents · 5 min 12 s · Nemotron 3.5 Lightning 30B via Nightshift · Judge 0.90 ▸ show steps"). The live "Live · model" badge uses the same chip text (`src/lib/modelChip.ts`).

`src/components/AgentPipeline.tsx` (model: `src/lib/pipeline.ts`) draws any run body (live, cache or replay) as Scope → Watchers → Memory → Investigator ⇄ Skeptic → Exposure → Playbook → Judge → Human approval. Each node shows its status, the summed trace `latency_ms`, its lane, how many times it ran, and the trace summary. The revise loop appears when `revise_rounds` > 0 and the repair loop when `repair_rounds` > 0. Badges:

- "Zetaris · N queryIds" on SQL-lane steps.
- One provider rule (`providerOf` in `src/lib/lanes.ts`) for badges, chips and the live model line: the trace's explicit provider wins when present; otherwise an `nvidia/…nemotron…` id is "Nightshift · …", `anthropic/…` is "Anthropic (test switch) · …", and every other id is shown as stored.
- "H-MEM recall · N" only when the memory step recalled at least one finding.
- "World Model" with the last board (H1 supported / not_supported …).
- "pgvector + Zetaris JDBC" when layer (c) citations exist.

The reveal is CSS and stops under `prefers-reduced-motion`. `src/components/RetrievalPanel.tsx` (model: `src/lib/retrieval.ts`) shows the layer (c) query, the passages per claim (title, page, publisher, licence, quote, attribution), the Zetaris query id that hydrated them, and the Judge's verdict, including "Flagged by Judge". Both views appear in the Ask popup under "How I got this". On insurer Review they form the "Causal chain" header, which reads `VITE_REPLAY_RUN_ID` or, failing that, the bundled recording `src/fixtures/run_f16733274f1c.json`. That header carries a "Recorded run · not live" badge and a note that says when it fell back to the bundled recording. Claim C2 in that recording is a known degenerate agent output and is shown as recorded.

### Disaster replay

Page `replay` on both desks, right after Now. Two events:

- Ahr valley, 13–16 Jul 2021 (EMSR517). The page reads `GET /views/hazard_timeline?event_id=EMSR517&source=replay` (Zetaris `floodsense_seed`, migrations 051/052, even when `FF_LIVE_DATA` points the app at the live views) and uses the result when it holds AHR points inside the window, badged "Replay · Zetaris floodsense_seed · not live". Otherwise it uses `src/fixtures/ahr_2021.json`, badged "Bundled modelled data (Open-Meteo, CC BY 4.0), not from Zetaris". `VITE_AHR_SOURCE=fixture` forces the fixture. The fixture holds Open-Meteo Flood API (GloFAS v4 daily discharge) and Historical Weather API (ERA5 hourly precipitation) data for four points (AHR01 Altenahr, AHR02 Bad Neuenahr-Ahrweiler, AHR03 Schuld, AHR04 Dernau), rendered from `ingestion/prep/ahr_*.csv` (the same rows as `floodsense_seed`), CC BY 4.0 Open-Meteo.com, modelled values.
- Valencia, 28–31 Oct 2024 (EMSR773), from the loaded `hazard_timeline` rows.

The page has an hourly scrubber, day buttons and Play/Pause. Under reduced motion Play steps once a second, and the time readout is not announced while playing. Each point shows its rain and discharge at the scrubbed time. Because GloFAS discharge is daily, a crossing of the 100 m³/s Watchers line is dated by day ("Crossed the line on 14 Jul 2021 (daily value)"), never by hour. "Ask the agents about this moment" opens Ask pre-filled and sends `context` {page, event_id, replay_date, point_id, place}. Everything is labelled "Replay of … · not live".

### Ask opening, suggestions and declined questions

The Ask popup opens with a greeting fitted to role and page (`greetingFor` in `src/lib/chatGreeting.ts`): "Hi! I'm FloodSense. Ask me about flood risk where you are — every answer cites its sources." and three suggested questions that send on click (citizen: Paiporta, the Rhine at Köln, the Ahr valley in July 2021; insurer: exposure and insured value). The recorded run (`VITE_REPLAY_RUN_ID`, or the fixture answer) is behind "See an example answer" and is labelled "Recorded run · not live". Real answers keep the badge, pipeline, retrieval and trace. When the agents decline a question that belongs to the other event (`status` out_of_scope with `scope.elsewhere`), the answer shows "Ask about Ahr 2021 instead" (or Valencia 2024), which re-sends the question with that `event_id`. Citizen pages send no `event_id`, so a question naming the other event is routed there and answered directly; insurer Replay and Sites send the page's `event_id`, so the same question is declined first and the switch button is the way across. Suggestions follow the event the page shows (`shownEventId`): an Ahr Replay or Sites page suggests Ahr questions, never a Valencia exposure one. "Recorded run · not live" appears once, only while the example is open; the toggle has `aria-expanded` and `aria-controls`.

The header subtitle uses the same rule as the replay strip (`shownEventId`): the selected event only on pages that show it (insurer Replay, Sites, and Portfolio on EMSR773), else "Valencia replay · EMSR773"; "Live" on Now. `src/lib/headerBar.test.ts` checks every role, page and event.

Citizen "What should I do?" shows general guidance at once: "Follow your official warning service" and the agents' own `CITIZEN_ADVICE` text, verbatim (`src/lib/safety.ts`; `safety.test.ts` fails if it drifts from `agents/floodsense_agents/live.py`). The agent-written, tailored step stays behind human review ("A tailored step from our agents appears here after a person checks it."). An Ask FloodSense button opens the chat. Below the advice: "In an emergency call 112." and official warning-service links for the country of the chosen place (`warningCountriesForCountry`: DE gets Germany, ES gets Spain, any other country only the EU-wide Meteoalarm link; without a country `warningCountriesFor` reads the names, and no place shows all groups). The URLs live only in `WARNING_LINKS` in `src/lib/safety.ts` and are pinned by an allowlist test; they render through `SafeLink` (new tab, `rel="noopener noreferrer"`, and a visually hidden "(opens in new tab)").

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
