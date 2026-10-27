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

**Replay schema.** An event replay reads `hazard_timeline` and `discharge_daily` from `EventSpec.hazard_schema` when set, whatever `FF_LIVE_DATA` says (`events.hazard_schema`). EMSR517 sets `floodsense_seed`: the live `floodsense` hazard views hold Valencia only, and the real Ahr extract (ERA5 hourly rain, GloFAS daily discharge, migrations 051/052) is in the seed. `exposure_join`, `gauge_levels` and `provenance` keep the configured schema. `GET /views/{name}?event_id=…&source=replay` serves the same rows to the UI (hazard views only, filtered to the event's point ids, `x-schema` / `x-source` headers). Rain thresholds: the Watchers flag an hour >= 30 mm or a window total >= 50 mm; the Skeptic's rain check passes on an hour >= 20 mm or a window total >= 50 mm, because ERA5 smooths the Ahr storm to 5.6-18.5 mm/h. A check that cannot apply (a warning check on a view with no warnings) is recorded as `skipped:` in the rationale and is not support; a hypothesis whose checks were all skipped stays `proposed`. A model claim keeps every number that is a cell of its cited rows; one that is not is dropped only when each mention in the text is a date or clock part, a declared line named in its unit after a comparison word ("above the 100 m3/s line"), or the coordinate filter of the cited SQL, and the drop is recorded on `Claim.numbers_dropped`. A claim whose numbers were all dropped is unverified in the Judge (numbers_match false).

`replay_ts` is the "now" of a replay: the Watchers and the Investigator only see rows at or before it, so the demo can step through 29 Oct 2024 hour by hour.

## LLM provider switch (local benchmarking only)

Every model call goes to Nightshift (NVIDIA Nemotron). That is the default, and
the demo and the submission run on it. For local speed and quality comparisons
only, set `LLM_PROVIDER_SWITCH=true` and `ANTHROPIC_API_KEY` in `agents/.env`.
`GET /config` then lists `llm_providers: ["nightshift", "anthropic"]`, the
operator console shows an LLM select next to Run, and `POST /runs` accepts
`"llm_provider": "anthropic"`. The choice is per run. Trace steps record
`model_id` as `anthropic/<model>` (fast lane `ANTHROPIC_MODEL_FAST`, default
`claude-haiku-5-5`; deep lane `ANTHROPIC_MODEL_DEEP`, default
`claude-sonnet-5-5`). With the gate off, any value other than `nightshift` is
rejected with 422. The API cache keeps each provider's answers apart.

## Nightshift speed and retries

Measured on Nightshift: both lanes answer with Nemotron 3.5 Lightning 30B A3B at about 60 to 70 completion tokens/s, and most completion tokens are hidden reasoning even with `enable_thinking=false`, so latency follows token count. Long generations get a **502 from the gateway at about 45 s**.

- Retry policy (`nightshift.py`): a reply with `finish_reason: length` is an error and is not retried, so a truncated reply never reaches a parser or the Judge. A 429 waits `Retry-After` seconds (at most 10). A timeout (`LLM_TIMEOUT_S`, 180) or an error that arrives after `LLM_SLOW_FAIL_S` (20 s) is final, and the node falls back to its deterministic path. Other errors (fast 5xx, connection, a 200 with no `choices`) get `LLM_MAX_ATTEMPTS` (2) tries in total.
- `LLM_MAX_TOKENS_FAST` / `LLM_MAX_TOKENS_DEEP` (6000 / 8000) are runaway caps, not length budgets; `0` sends no `max_tokens`.
- The ~45 s cut is Meterless' own (`provider_deadline` / `empty_response`), not prompt size. Hidden reasoning varies between 1,300 and 5,500 tokens even on a 900-character prompt. `LLM_STREAM=true` (the default) streams every call (SSE) and assembles the usual reply. A non-streamed request is cut at 45 s, but a streamed one often runs to the end (measured up to 131 s). A stream that ends in a provider error is retried once, even after `LLM_SLOW_FAIL_S`.
- Investigator: the deterministic chain is reworded with one call per link (rain->catchment, catchment->river, river->site), run concurrently through `map_ordered`. Each call carries only that link's draft claims and the rows they cite: at most 8 rows per table, rows holding the claimed numbers first, numbers written plainly, and query ids shown as aliases (Q1..). It answers `{"statement", "claims": [...]}` with at most 4 claims. Links merge in chain order and claims are renumbered C1... A failed link keeps its deterministic claims, and the trace says `k/3 links worded by the model`. Model claims are checked the same way as before: unknown ids are dropped, all-empty evidence drops the claim, and numbers go through `cited_numbers`.
- Playbook: exposure totals and the 5 largest sites, not the full asset list; at most 4 actions of at most 30 words.
- `model_ids` on the run is read from the trace. It lists every model that answered a node, once each in node order, and leaves out "deterministic".
- Skeptic rationale calls and Judge per-claim grounding calls run on up to `LLM_MAX_PARALLEL` (6) threads. Results are applied in input order, so scores, hypotheses and the trace are the same as a serial run. `1` runs them serially.
- The repair round runs only when the Judge flags claims **and** the run does not pass. `JUDGE_REPAIR_WHEN_PASSING=true` repairs flagged claims on a passing run too.

Benchmark one full run against real Nightshift and Zetaris inside the agents container, without rebuilding it:

```
docker cp agents/floodsense_agents floodsense-app-agents-1:/tmp/bench/floodsense_agents
docker cp scripts/bench_nightshift.py floodsense-app-agents-1:/tmp/bench_nightshift.py
docker exec -w /tmp -e PYTHONPATH=/tmp/bench floodsense-app-agents-1 python /tmp/bench_nightshift.py --doc-query "Valencia DANA flood warnings"
```

`PYTHONPATH=/app` measures the image's code instead. It prints per-node trace latency and per-call lane, seconds, prompt size and answering model (`--json` for one object). It reads the container env and prints no secret.

`AnthropicClient` (the test-only provider switch) keeps its own `max_tokens` (16000) and its own retry policy (3 attempts). None of the `LLM_*` settings above apply to it, so bench numbers for the two providers are not like-for-like.

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

The NVIDIA chat key is not a variable in `.env`. It lives only in Nightshift's Providers tab. Document embeddings use `NVIDIA_NIM_API_KEY` in a gitignored env file, and that key is not the chat key (ADR 0009). Chat calls send `Authorization: Bearer <METERLESS_RUNTIME_TOKEN>`, `meterless-app`, and `meterless-scope: user`.

### Getting the NIM embeddings key

Only needed for layer (c) (`FF_RAG_DOCS`, `scripts/rag_ingest.py`). Generate your own key. It is a separate key from the one in Nightshift's Providers tab, even when both come from the same NVIDIA account.

1. Sign in at [build.nvidia.com](https://build.nvidia.com) with a free NVIDIA account.
2. Open the `nvidia/nemotron-3.5-embed-1b` model page. (`nvidia/llama-nemotron-embed-1b-v2` is retired and answers HTTP 410.)
3. Choose **Get API Key**, then **Generate**. The key starts with `nvapi-`. The free tier's trial credits cover the corpus.
4. Put it in your gitignored `agents/.env` as `NVIDIA_NIM_API_KEY=`. Leave `NIM_EMBEDDINGS_URL` empty to use the default `https://integrate.api.nvidia.com/v1/embeddings`.
5. Do not commit it, paste it in chat, or put it in a fixture or screenshot. CI's gitleaks rule fails on an `nvapi-` string.

The ingest command on the host reads the same variable from its environment. Why NIM and why this model: [ADR 0009](../docs/adr/0009-vector-search-next-to-zetaris.md).

Lane ids: fast `meterless/fast`, deep `meterless/deep`. The app sends these ids. Nightshift picks the model. No `meterless/auto`. The map to the model that answers today is the table at the top of `docs/architecture/c4.md`. Super VL answers both lanes today, so the fast lane is not by itself a large wall-time cut. It helps when `MODEL_FAST` is a cheaper or faster model, such as Lightning.

Independent Zetaris reads in one node run together, up to `ZETARIS_MAX_PARALLEL` (default 8). Set it to 1 to run them one after another, in call order. A query that raises is recorded as `Evidence.error`. The other queries in that batch still come back. That overlap is the guaranteed gain while both Nightshift lanes are answered by the same model.

## Germany: routing, the Rhine right now, and context

**Event routing** (`events.route_event`, called by `Runtime.start`). `RunRequest.event_id` is optional. An explicit id always stands, so `EMSR773` forces Valencia. When it is unset, the run picks in this order: `context` (event_id, then a known `point_id`, then a `station`, which is always German, then `place`); then a question naming Rhine/Rhein/Köln/Koeln/Cologne/Bonn/Koblenz/Mosel/Ahr (any case, including AHR and the AHR point ids)/Germany/NRW/Rheinland-Pfalz goes to EMSR517; otherwise EMSR773. A question that also names a Valencia town from `POINT_NAMES` (Paiporta, Catarroja, Sedaví, ...) stays on EMSR773. The reason is on the scope trace step ("event EMSR517: question names 'Köln' ..."). The UI sends `event_id` only when the page has one.

**The Rhine right now.** Live mode on EMSR517 reads `{schema}.gauge_levels` (PEGELONLINE). It first counts `hazard_now` rows for the German points and says plainly when there are none, without borrowing Valencia rows. Each station gets one claim: level in cm, UTC time and "N h ago", and the trend from `trend_cm_h`. Without that column, the trend is given as "from P cm at T to L cm", using two cited cells. The threshold is `mhw_cm`, falling back to any numeric column named like threshold/warn/hsw. The wording uses `band` (below/near/above) when present. A row with `is_stale` is reported as "stale reading from <time>", never as current. With no live row, the answer is a "Status:" claim with no numbers. Every gauge claim says: not an official warning; official: Hochwassermeldedienst (Länder) / DWD. The Skeptic checks the gauge hypothesis against `gauge_levels`.

**RunRequest.context** (`models.RunContext`): `{page, role: citizen|insurer, place, point_id, station, event_id, replay_date}`. Keys are allowlisted, so an unknown key is a 422. Every field is short and pattern-checked. Context values are never SQL identifiers. A `point_id` is used only when it is one of the event's known points. The station is uppercased and quote-escaped, and only appears inside a quoted string value. The context focuses the Watchers queries (`point_id = …`, `station = …`) and the live hazard chain, and puts the selected station first. It also phrases the answer for the role: a citizen gets "In plain words: …" and what to do, an insurer gets "Exposure: …" first. The scope trace step records it. The API cache key and replay matching include the context, so a cached answer never crosses places or roles.
