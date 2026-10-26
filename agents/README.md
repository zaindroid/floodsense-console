# Agents

Purpose: the LangGraph runtime. Graph: **Watchers → Investigator → Skeptic → Exposure → Playbook → Judge → human-in-the-loop interrupt**, as planned. Agents read data only through Zetaris (`zetaris.py`, SELECT-only) and call models only through the Nightshift client (`nightshift.py`, pinned lanes).

Owner: Ayush (Nightshift client, H-MEM, World Model, memory, embeddings) and Zain (graph, HITL, Judge with Mihir).

```
watchers → investigator → skeptic ─┬─ not_supported, first time → revise → investigator → skeptic
                                   └─ → exposure → playbook → judge ─┬─ flagged, first time → playbook (repair) → judge
                                                                      └─ → hitl (interrupt) → learn → end
```

With `ENGINES_URL` set, the Watchers, Investigator and Skeptic also write to the World Model board, and behind `FF_HMEM` the Investigator recalls past approved findings and Learn stores the approved run. See [Engines: memory and World Model](#engines-memory-and-world-model).

| Node | Lane | What it does | Owner |
| --- | --- | --- | --- |
| `nodes/watchers.py` | SQL | Anomalies from `hazard_timeline` in the event window, cut at `replay_ts`; reads `gauge_levels` for that window when the event lists stations; loads `provenance` | Zain, Ayush |
| `nodes/investigator.py` | fast | Hypotheses H1–H3 (rain→catchment→river→site) backed by claims; every claim cites a `query_id` (layer a) and the provenance row (layer b). Deterministic chain from aggregate queries run together; the model refines it from the same evidence on `meterless/fast` | Zain, Ayush |
| `nodes/skeptic.py` | SQL (+fast rationale) | ≤ `SKEPTIC_MAX_ROUNDS` counter-check queries per hypothesis (default 3; a smoke run can set 1) → `supported` / `not_supported`; one revise edge back to the Investigator, which drops what was not supported. The rationale is `meterless/fast` | Zain, Ayush |
| `nodes/exposure.py` | SQL | `exposure_join` with `in_footprint = TRUE`: policies, sum insured, by segment → H4 with number claims. The sample, the segment rollup, and the total run together | Ayush, Zain |
| `nodes/playbook.py` | fast draft, deep repair | Actions for 6 / 24 / 72 h citing claim ids; `outbound` ones wait for approval. The first draft is `meterless/fast`. A model action that cites no claim of this run is dropped. The repair round, when the Judge flags a claim, stays on `meterless/deep` | Ayush, Zain |
| `nodes/judge.py` | deep | Per-claim coverage, citation faithfulness, numbers match, licence, grounding → `judge[]` + `judge_summary`. Never deletes or rewrites | Zain, Mihir |
| `hitl.py` | — | `interrupt()`; approve / edit / reject; `approval{}`; outbound actions released only on approve / edit | Zain |
| `nodes/memory.py` | — | Behind `FF_HMEM`: recall before the Investigator's first pass, and the Learn node after `hitl`, which stores an approved or edited run | Ayush |
| `nodes/world_model.py` | — | With `ENGINES_URL`: writes the Watchers' anomalies and each hypothesis write to the World Model board | Ayush |

Contracts (gameplan v2 §5.5) are in `models.py` field for field: Evidence, Citation, Judge score, agent state (`run_id, thread_id, event_id, customer_id, replay_ts, anomalies[], hypotheses[], exposure{}, playbook[], judge[], approval{}, trace[]`), trace events. Extras (`claims[]`, `evidence{}`, `judge_summary`, `summary`) sit next to them and the UI may ignore them. The nodes use only the contract views (`hazard_timeline`, `discharge_daily`, `exposure_join`, `gauge_levels`, `provenance`), so switching to live is `FF_LIVE_DATA=true` plus credentials. `FF_LIVE_DATA` defaults to false and stays off until that flag is set.

Watchers query `gauge_levels` only when `events.py` lists stations for that event. EMSR517 (Ahr) lists Bonn, Köln, and Koblenz, because the Ahr joins the Rhine between Koblenz and Bonn. EMSR773 (Valencia) lists none, and the gauge query is skipped. Watchers read `hazard_timeline`, not `hazard_now`. A live PEGELONLINE pull is the last 30 days, so those rows never overlap the frozen event windows (12–16 July 2021 and 28–30 October 2024). The seed rows name the Ahr stations at `window_from_utc` and leave `level_cm` empty.

Point ids in `events.py` are the warehouse ids. Valencia is `VAL01`–`VAL08` (`ingestion/prep/valencia_points.csv`, migrations 004 and 012). Chiva is `VAL07`. Paiporta on the Barranco del Poyo is `VAL01`. Turís is not on that list. The Ahr uses `AHR01` (Altenahr) and `AHR02` (Ahrweiler), the same ids as `ingestion/feeds/feeds.py`. `floodsense_seed` hazard and discharge views are the Valencia series only, so an Ahr replay against those views still has no hazard rows. FakeZetaris uses the same ids and does carry the Ahr rows. `exposure_join.in_footprint` is boolean (`in_flood_footprint = 'yes'` in migrations 014, 016, and 018). The SQL predicate is `in_footprint = TRUE`.

## Run it

From the repo root, `python tasks.py init-env` copies `.env.example` to `.env` here when it is missing (Windows: `py tasks.py init-env`). With nothing filled in, the runtime starts on **FakeZetaris** (the contract views as SQLite seed rows for Valencia 2024 / Ahr 2021, Rhine gauge stations with no invented level, plus a synthetic portfolio) and **FakeNightshift** (deterministic), so the whole graph, the API and the UI work before credentials and live views exist. Fill `ZETARIS_REST_URL` / `ZETARIS_API_KEY` and `METERLESS_BASE_URL` / `METERLESS_RUNTIME_TOKEN` to go live.

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests          # 20 tests, < 1 s, no network
python3 -m floodsense_agents                   # http://127.0.0.1:8100 (compose: not published; the API proxies it)
```

```bash
curl -s -X POST 127.0.0.1:8100/runs -H 'content-type: application/json' \
  -d '{"question":"Why are our Valencia sites at risk?","event_id":"EMSR773","customer_id":"demo-insurer","replay_ts":"2024-10-29T18:00:00Z"}'
# -> status awaiting_approval, hypotheses[], claims[] with citations, exposure{}, playbook[], judge[], trace[]
curl -s 127.0.0.1:8100/runs/<id>/approval
curl -s -X POST 127.0.0.1:8100/runs/<id>/approval -H 'content-type: application/json' -d '{"action":"approve","reviewer":"zain"}'
curl -N 127.0.0.1:8100/runs/<id>/events        # SSE: one TraceEvent per node, then a status event
```

`POST /runs`, `GET /runs/past`, `GET /runs/{id}`, `GET /runs/{id}/replay` (the run labelled replay, `cached_at` its start), `GET|POST /runs/{id}/approval`, `GET /runs/{id}/citations`, `GET /runs/{id}/events`, `GET /config`, `GET /health`. Every response carries `served_from` and `cached_at` when it is not live. A fresh read of `floodsense.*` through live Zetaris, with no replay clock, is `live`. Fake Zetaris, the seed schema, and a replay clock are `replay`. A re-read with no replay clock, including a cached event timeline, is `cache`. A run posted with `replay_ts` stays `replay` on `GET /runs/{id}`. `/ready`, `/config`, `/version`, `/runs/past`, an empty `/desk/events`, and `/desk/dispatch-target` are `replay` on FakeZetaris or the seed schema. `GET /health` is liveness only and may say `live`.

The product UI is the Vite console in `ui/` (compose publishes it on `127.0.0.1:15173`). This service does not serve `ui/app` or `ui/mock`. `GET /` and `GET /console` serve `console.html`, a secondary operator page on this unpublished port.

`replay_ts` is the "now" of a replay: the Watchers and the Investigator only see rows at or before it, so the demo can step through 29 Oct 2024 hour by hour.

## Human-in-the-loop

`hitl.py` pauses with `interrupt()`; the checkpointer is **SQLite under `/data/checkpoints`** (the compose volume, `checkpoints.py`), so a paused run survives a restart of the container. Resume with `POST /runs/{id}/approval`: `approve` releases the outbound playbook actions, `edit` replaces the summary with the analyst's `edits` and releases, `reject` releases nothing. The decision lands in `approval{status, decision, edits, reviewer_note}` and in the trace. `FF_HITL=false` auto-approves and says so (`approval.status = "auto"`): dev only.

## Judge

`FF_JUDGE=true` scores every claim before the interrupt: coverage (≥ 1 citation), citation faithfulness (the cited query exists and returned rows; layer-c quote hash), numbers match (every number in the claim is in its cited rows, 2 % tolerance, sums over a column count), licence (no full text from a pointer-only source), grounding (deep lane sees only the claim and its evidence; offline fallback from the deterministic checks). A number the rows do not hold is never `supported`, whatever the model says. `score = 0.4·grounding + 0.2·coverage + 0.2·faithful + 0.2·numbers`. One repair round back to the Playbook for flagged claims; the repaired claim stays visible, marked `[repaired]`. `judge_summary.passes` = hallucination ≤ 5 %, coverage 100 %, overall ≥ `JUDGE_MIN_SCORE` (0.7, a proposal until the first eval run).

Eval set and runner: [`../evals/`](../evals/README.md).

## Engines: memory and World Model

`engines.py` is the client for the `engines/` sidecar (Meterless H-MEM and World Model behind HTTP on `:8300`). `ENGINES_URL` unset means the engines are off: the graph keeps `NoMemory` and `NoWorld`, sends nothing, and the trace is the same as without them.

| What | When | Engines call | Trace event |
| --- | --- | --- | --- |
| Anomalies become observations | after the Watchers | `POST /wm/observations` | `world_model`: observed, already known, events appended |
| Hypotheses with their status | after the Investigator and after the Skeptic | `POST /wm/hypotheses`, `at` = the replay clock | `world_model`: the board, for example `H1 supported, H2 not_supported` |
| Past approved findings on the same event | before the Investigator's first pass, `FF_HMEM` | `POST /hmem/recall` with the question; keeps memories tagged with the run's event | `memory`: how many were recalled |
| Write-on-approval | `learn`, after `hitl`, `FF_HMEM` | `POST /hmem/store` with the run's claims and `approval` | `learn`: stored, already remembered, or why nothing was stored |

- Recalled findings go into the Investigator's prompt as context, never as evidence: claims still cite only this run's query ids. The reviewer sees them as `memories` in the approval payload.
- Recall is scoped to the run's flood event. The engines' reference embedder is a token hash, not semantic, so a related and an unrelated question score alike (about 0.2 to 0.3). Recall therefore asks for a wide pool with no score cut (`HMEM_RECALL_THRESHOLD`, default 0) and keeps the findings tagged with the same event. Recall across events needs real embeddings, from Nightshift's embed lane; raise the threshold then.
- Only an `approved` or `edited` run is remembered. `rejected` and `auto` write nothing. A retried store writes nothing twice, because the engines key a memory by `(run_id, claim_id)`.
- `at` is the scenario clock (the end of the event window, cut at `replay_ts`), so a replayed run appends no new World Model events.
- The engines never fail a run. A call that fails, or engines that are not running, become a trace note, and the run and the approval stand.

To try it on the host: `cd engines && npm start` (Node 22.18 or newer), then run the agents with `ENGINES_URL=http://127.0.0.1:8300` and `FF_HMEM=true`. In compose the agents service uses `ENGINES_URL=http://engines:8300` (`compose.yaml` sets it). `ENGINES_TIMEOUT_S` (default 5) caps each call, and `HMEM_RECALL_TOP_N` (default 3) is how many findings are recalled. `GET /ready` names the memory and World Model in use.

## Thread memory

Short-term memory for a conversation. `POST /runs` takes an optional `thread_id`: the `thread_id` of an earlier run (a first run's thread is its own `run_id`). The new run gets that thread's last three turns in `state.thread`, each with the question, the run status, the approval status and the summary. The Investigator's prompt shows them as context only, never as evidence, so a follow-up still derives every claim from its own queries. The `memory` trace step says how many turns it carried, and the reviewer sees them as `thread` in the approval payload. No flag is involved: a run without `thread_id` is unchanged.

- An unknown `thread_id` is a 404, not a silent new thread, so a client continuing a conversation hears when it is not.
- `GET /runs/past?thread_id=` lists one conversation, and every row carries its `thread_id`.
- Threads come from the checkpointer, so they survive a restart. A rebuilt run list keeps each run's real start time, taken from its first trace event.

## Hooks for the pair

- **Nightshift client** (Ayush): `nightshift.LLM.complete(lane, system, user, json=True) -> (text, model_id)`. `NightshiftClient` here sends the three headers and `enable_thinking=false`; replace or extend it, the nodes only use the protocol. `FakeNightshift` keys on the `TASK:` line of each system prompt (`prompts.py`).
- **Memory** (Ayush, `FF_HMEM`): `state.Memory.recall(request)` and `.store(run_id, request, claims, approval)`. `recall` runs before the Investigator; `store` runs in the Learn node after the decision, on approve or edit only (`nodes/memory.py`). `engines.EnginesClient` implements it over the sidecar; plain `NoMemory` means memory is off.
- **World Model** (Ayush): `Deps.world`, `engines.WorldModel` (`observe`, `update_hypotheses`). `NoWorld` records nothing.
- **Views** (Mihir; Saleeta secondary on prep): every SQL string lives in the node that runs it; column names follow `contracts` v1. If a real field differs, change the SQL there and the matching seed row in `zetaris.py`. Urvashi remains for Zetaris expertise.

In compose, the agents service reaches the engines sidecar at `ENGINES_URL=http://engines:8300`. On the host that URL is `http://127.0.0.1:8300`. `compose.yaml` sets the compose value.

The NVIDIA provider key is not a variable in `.env`. It lives only in Nightshift's Providers tab. Calls send `Authorization: Bearer <METERLESS_RUNTIME_TOKEN>`, `meterless-app`, and `meterless-scope: user`.

Lane ids: fast `meterless/fast`, deep `meterless/deep`. The app sends these ids. Nightshift picks the model. No `meterless/auto`. The map to the model that answers today is the table at the top of `docs/architecture/c4.md`. Super VL answers both lanes today, so the fast lane is not by itself a large wall-time cut. It helps when `MODEL_FAST` is a cheaper or faster model, such as Lightning.

Independent Zetaris reads in one node run together, up to `ZETARIS_MAX_PARALLEL` (default 8). Set it to 1 to run them one after another, in call order. A query that raises is recorded as `Evidence.error`. The other queries in that batch still come back. That overlap is the guaranteed gain while both Nightshift lanes are answered by the same model.
