# API

Purpose: the FastAPI service the UI and the demo call. It owns the public contract (gameplan §5.5) and proxies the run lifecycle to the agents service at `AGENTS_URL`: `POST /runs` (an optional `thread_id` continues a conversation), `GET /runs/past` (`?thread_id=` for one conversation), `GET /runs/{id}`, `GET /runs/{id}/replay`, `GET /runs/{id}/events` (SSE), `GET|POST /runs/{id}/approval`, `GET /runs/{id}/citations`, `GET /config`, `GET /health`. Every response carries `served_from` and `cached_at`. The cache and labelled replay sit here, in front of the proxy (below); rate limits guard the write routes (below). CORS is open to the UI origins only (`UI_ORIGINS`, default `http://localhost:15173,http://127.0.0.1:15173`).

Owner: Zain (runs, SSE, approval) and Ayush (cache and past runs). Mihir (rate limits).

PowerShell, from this directory. `python -m uvicorn` avoids the `Scripts` vs `bin` difference. `curl` in PowerShell is not curl.

```powershell
py -m pip install -r requirements.txt
py -m uvicorn app.main:app --reload --port 8000
Invoke-RestMethod http://127.0.0.1:8000/health
```

bash:

```bash
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --port 8000
curl -s http://127.0.0.1:8000/health
```

Inside compose the process listens on port 8000 and is published on host port 18000. On the host, run `python -m floodsense_agents` from `agents/` first and set `AGENTS_URL=http://127.0.0.1:8100` (the default). From the repo root, `python tasks.py init-env` copies `.env.example` to `.env` before `up`.

The NVIDIA chat key is not a variable for this service. It lives only in Nightshift's Providers tab. Document embeddings use `NVIDIA_NIM_API_KEY` in a gitignored env file (ADR 0009). This service does not call them.

## Cache and labelled replay

GAMEPLAN "Caching and the honest demo", in `app/cache.py`. Both are off unless their flag is on in `api/.env`.

- **Cache (`FF_SEMANTIC_CACHE`).** A run is cached when a person approved or edited it and the Judge passed it. A repeat of that question is answered with the original run, `200` instead of `201`, `served_from: "cache"` and a `cache` block (`original_run_id`, `age_s`, `expires_in_s`). The banner is "Cached answer from HH:MM · not live · original run R", including when the stored run was a clocked replay: the hit is cache, not replay and not live, and `replay_ts` / `cached_at` stay that UTC instant. The key is the question with case, spacing and punctuation folded, plus the event, customer, replay clock, language, and the agents' flags, lanes and schema, so a change of flags is a miss. The replay clock is normalised to `YYYY-MM-DDTHH:MM:SSZ` on lookup and on remember, so a zone-less or short form hits. Live data expires after `CACHE_TTL_LIVE_S` (900), a historical replay after `CACHE_TTL_REPLAY_S` (86400). `{"fresh": true}` in the body skips the cache. A follow-up in a thread is never cached or served from the cache. "Similar" means equal after folding for now; embedding similarity needs Nightshift's embed lane.
- **Replay (`FF_CACHED_REPLAY`).** When the live run fails (the agents are unreachable, answer 5xx, or return a failed run), and the request is not a follow-up, the API serves the newest person-approved run for the same question, event, customer, replay clock and language. `valencia_2024` matches `EMSR773` (and `ahr_2021` matches `EMSR517`). A different question is not served. `served_from` is `"replay"`, the banner is "Replay of a recorded run from HH:MM · not live · original run R" plus the original question, and the `replay` block carries that question, the clock, the reason, and `failed_run_id` when a live run failed. Lookups use `CACHE_LOOKUP_TIMEOUT_S` (3s), not the 600s run timeout. The agents' checkpointer holds the recordings; the API also keeps the last `REPLAY_MAX_RECORDINGS` (8) itself, and an unreachable agents service is answered from that recording without scanning the past list. With no matching recording, the failure is passed through. `GET /runs/{id}/replay` carries the same contract projection as a run snapshot.
- **Never presented as live.** The trace keeps the original run's timestamps, and `GET /config` reports the cache under `api_cache`.

The cache lives in this process (`CACHE_MAX_ENTRIES`, 256). `REDIS_URL` is not read yet, so a restart empties the cache but not the agents' recordings.

## Rate limits

`app/ratelimit.py`, in this process, no extra dependency. `POST /runs` has a token bucket per client IP: `RATE_LIMIT_RUNS_PER_MIN` (10) per minute, with a burst of the same size (at least 1). `POST /runs/{id}/approval` is not limited, so a reviewer can always approve a run. Live `POST /runs` calls in flight to the agents are capped at `RATE_LIMIT_MAX_CONCURRENT_RUNS` (2); a cache hit does not take a slot, and with `FF_CACHED_REPLAY` on a full cap is answered with the labelled replay when one exists. Either refusal is `429` with a `Retry-After` header (the bucket's wait, or `RATE_LIMIT_CONCURRENCY_RETRY_AFTER_S`, 30, when the cap is full). `0` turns a guard off. GET routes (health, config, past runs, replay, SSE events) are not limited. Limits are per process and per client IP; behind a reverse proxy run uvicorn with `--forwarded-allow-ips` so the client IP is the real one.
