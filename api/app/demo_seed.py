"""Demo seed: approved findings in H-MEM and two warmed answers in Redis.

In real use the system starts empty: memory fills when an analyst approves a
run, and the cache fills when an approved, Judge-passed run is asked again.
For a recorded demo this module fills both ahead of time, and labels all of it.

    python tasks.py demo-seed        # runs `python -m app.demo_seed seed` in the api container
    python tasks.py demo-reset       # removes what seed put in Redis

Memory. Each seed is sent to the engines' POST /hmem/store, the endpoint the
agents call on approval (agents/floodsense_agents/engines.py, store()). The
reviewer is "demo-seed", the run ids start with "demo-seed-", and every claim
carries the entity "demo-seed", so the stored provenance reads "run
demo-seed-... approved by demo-seed" and GET /system flags it seeded. The
texts are copied from a recorded run (ui/src/fixtures/run_f16733274f1c.json)
with their citations, and the Ahr one is written from the floodsense_seed rows
in ui/src/fixtures/ahr_2021.json in the agents' own wording. The engines key a
memory by (run_id, claim_id), so seeding twice writes nothing twice. H-MEM has
no delete route; demo-reset says how to drop the engines volume instead.

Cache. Two real runs already in the agents that a person approved and the
Judge passed are written to Redis through app/cache.py: AnswerCache.remember
(the cache entry, floodsense:cache:v1:) and AnswerCache.record (the 30-day
recording, floodsense:replay:v1:). Asking one of those questions again is then
answered "Cached answer from HH:MM · not live · original run R". Nothing is
invented: with no such run, seed says so and warms nothing. A marker key
floodsense:demo:v1:seeded lists the warmed runs for /system.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

from app.cache import (
    CACHE_PREFIX,
    DEMO_SEED_KEY,
    REPLAY_PREFIX,
    AnswerCache,
    Entry,
    _slot,
    approved_by_a_person,
    ask_of,
    canonical_event,
    finished_well,
    fingerprint,
    is_follow_up,
    key_of,
)

REVIEWER = "demo-seed"
NOTE = "seeded for demo"
WARM_RUNS = 2
TIMEOUT = httpx.Timeout(10.0, connect=3.0)

_VAL_Q = (
    "Why was Paiporta exposed on 29 Oct 2024, and what does the Copernicus delineation "
    "and the literature say about the Barranc del Poyo?"
)


def _cite(cid: str, claim: str, title: str, query_id: str | None, **extra: Any) -> dict[str, Any]:
    return {"citation_id": cid, "claim_id": claim, "layer": "a", "title": title, "query_id": query_id, **extra}


# Copied from ui/src/fixtures/run_f16733274f1c.json (claims C3 to C6, citations kept)
# and, for the Ahr, from the floodsense_seed rows in ui/src/fixtures/ahr_2021.json.
SEEDS: list[dict[str, Any]] = [
    {
        "run_id": "demo-seed-valencia-paiporta",
        "event_id": "EMSR773",
        "question": _VAL_Q,
        "claims": [
            {
                "claim_id": "C3",
                "text": (
                    "Daily discharge for Paiporta (VAL01) (open-meteo-flood-glofas) was 467.81 m3/s "
                    "on 2024-10-30, up from 23.38 m3/s on 2024-10-28."
                ),
                "hypothesis_id": "H2",
                "entities": ["Paiporta", "Barranc del Poyo", "VAL01", REVIEWER],
                "citations": [
                    _cite("C3-a1", "C3", "floodsense.discharge_daily", "1223e572-6676-4b30-bad6-15c20cbb70e0")
                ],
            },
            {
                "claim_id": "C4",
                "text": "The Copernicus EMS footprint (EMSR773) covers 91 insured sites across 2 segments.",
                "hypothesis_id": "H3",
                "entities": ["Paiporta", "Horta Sud", "EMSR773", REVIEWER],
                "citations": [
                    _cite("C4-a1", "C4", "floodsense.exposure_join", "a23655ae-5c1a-4876-8a93-d942e3a12735")
                ],
            },
        ],
    },
    {
        "run_id": "demo-seed-valencia-exposure",
        "event_id": "EMSR773",
        "question": "How many of our policies are inside the Copernicus footprint?",
        "claims": [
            {
                "claim_id": "C5",
                "text": (
                    "91 policies sit inside the mapped footprint, sum insured 313,166,000 EUR; "
                    "the largest is SYN-00034 (industrial, 10,900,000 EUR)."
                ),
                "hypothesis_id": "H4",
                "entities": ["Paiporta", "Barranc del Poyo", "EMSR773", REVIEWER],
                "citations": [
                    _cite("C5-a1", "C5", "floodsense.exposure_join", "db656b44-29e8-4b3f-91fb-38f8405604e9")
                ],
            },
            {
                "claim_id": "C6",
                "text": "The most exposed segment is industrial: 30 policies, 161,701,000 EUR sum insured.",
                "hypothesis_id": "H4",
                "entities": ["Paiporta", "EMSR773", REVIEWER],
                "citations": [
                    _cite("C6-a1", "C6", "floodsense.exposure_join", "18111c22-1483-4ce9-a351-7652ba9f9d99")
                ],
            },
        ],
    },
    {
        "run_id": "demo-seed-ahr-altenahr",
        "event_id": "EMSR517",
        # Not an eval question (ahr-03 asks "What discharge did the Altenahr gauge reach?").
        "question": "How high did the Ahr run at Altenahr in July 2021?",
        "claims": [
            {
                "claim_id": "C2",
                "text": (
                    "Daily discharge for Altenahr (AHR01) (open-meteo-flood-glofas) was 249.61 m3/s "
                    "on 2021-07-14, up from 6.91 m3/s on 2021-07-12."
                ),
                "hypothesis_id": "H2",
                "entities": ["Altenahr", "Ahr", "AHR01", "EMSR517", REVIEWER],
                "citations": [
                    _cite(
                        "C2-a1",
                        "C2",
                        "floodsense_seed.discharge_daily",
                        None,
                        publisher="Open-Meteo (GloFAS v4 reanalysis)",
                        licence="CC-BY-4.0",
                        attribution="Open-Meteo.com, modelled, not gauge readings",
                    )
                ],
            },
        ],
    },
]


def _post(client: httpx.Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    r = client.post(path, json=body)
    r.raise_for_status()
    return r.json()


def seed_memory(engines_url: str, transport: httpx.BaseTransport | None = None) -> int:
    """Store every seed through POST /hmem/store. Returns the number of new memories."""
    new = 0
    with httpx.Client(base_url=engines_url.rstrip("/"), timeout=TIMEOUT, transport=transport) as c:
        for seed in SEEDS:
            body = {
                "run_id": seed["run_id"],
                "question": seed["question"],
                "event_id": seed["event_id"],
                "approval": {"status": "approved", "reviewer": REVIEWER, "reviewer_note": NOTE},
                "claims": seed["claims"],
            }
            report = _post(c, "/hmem/store", body)
            stored = len(report.get("stored") or [])
            again = len(report.get("already_stored") or [])
            new += stored
            print(f"  memory {seed['run_id']} ({seed['event_id']}): {stored} stored, {again} already there")
    return new


def _get(client: httpx.Client, path: str, **params: Any) -> Any:
    r = client.get(path, params=params or None)
    if r.status_code != 200:
        return None
    try:
        body = r.json()
    except ValueError:
        return None
    return body


def pick_runs(rows: list[dict[str, Any]], runs: dict[str, dict[str, Any]], n: int = WARM_RUNS) -> list[str]:
    """Up to n run ids that may be cached: approved by a person, Judge-passed, not a follow-up.

    Newest first, one per event before a second from the same event.
    """
    good = [
        r["run_id"]
        for r in rows
        if isinstance(r, dict)
        and r.get("run_id") in runs
        and finished_well(runs[r["run_id"]])
        and not is_follow_up(runs[r["run_id"]])
    ]
    picked: list[str] = []
    seen: set[str] = set()
    for rid in good:
        ev = canonical_event(runs[rid].get("event_id") or (runs[rid].get("request") or {}).get("event_id"))
        if ev not in seen:
            picked.append(rid)
            seen.add(ev)
    for rid in good:
        if rid not in picked:
            picked.append(rid)
    return picked[:n]


def warm_cache(agents_url: str, cache: AnswerCache, transport: httpx.BaseTransport | None = None) -> list[str]:
    """Cache entry and recording for two approved runs. Returns the warmed run ids."""
    if cache.backend() != "redis":
        print("  cache: Redis is not reachable from here (REDIS_URL unset or down); nothing warmed.")
        print("         Start the cache profile (python tasks.py up-all) and set REDIS_URL in api/.env.")
        return []
    with httpx.Client(base_url=agents_url.rstrip("/"), timeout=TIMEOUT, transport=transport) as c:
        config = _get(c, "/config")
        if not isinstance(config, dict):
            print("  cache: agents GET /config failed; nothing warmed.")
            return []
        flags = fingerprint(config)
        past = _get(c, "/runs/past", limit=200)
        rows = [r for r in ((past or {}).get("runs") or []) if isinstance(r, dict)]
        rows = [r for r in rows if r.get("status") == "approved" and not str(r.get("run_id", "")).startswith(REVIEWER)]
        runs: dict[str, dict[str, Any]] = {}
        for row in rows[:40]:
            run = _get(c, f"/runs/{row['run_id']}")
            if isinstance(run, dict) and approved_by_a_person(run):
                runs[row["run_id"]] = run
        picked = pick_runs(rows, runs)
        if not picked:
            print("  cache: no approved, Judge-passed run in the agents yet; nothing warmed.")
            print("         Ask two questions, approve them on the Approvals page, then seed again.")
            return []
        ttl = cache.settings.recording_ttl_s
        entries: list[dict[str, str]] = []
        slots: list[str] = []
        questions: list[str] = []
        warmed: list[str] = []
        for rid in picked:
            run = runs[rid]
            if not cache.remember(run, flags):
                continue
            # A warmed entry lives as long as the recording (30 days), not the 15 min
            # (live) or 1 day (replay) a cache entry gets, so it survives until recording.
            key = key_of(run.get("request") or {}, flags)
            cache._write_entry(key, Entry(rid, time.time(), ttl), ttl)
            warmed.append(rid)
            cache_key = _slot(CACHE_PREFIX, key)
            slots.append(cache_key)
            entries.append({"run_id": rid, "cache_key": cache_key})
            replay = _get(c, f"/runs/{rid}/replay")
            if isinstance(replay, dict):
                cache.record(replay)
                slots.append(_slot(REPLAY_PREFIX, ask_of(replay)))
            q = str((run.get("request") or {}).get("question") or "")
            questions.append(q)
            print(f"  cache: run {rid} warmed ({canonical_event(run.get('event_id'))}): {q}")
    marker = {
        "run_ids": warmed,
        "entries": entries,
        "ttl_s": cache.settings.recording_ttl_s,
        "questions": questions,
        "keys": slots,
        "seeded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": NOTE,
    }
    if cache._redis is not None:
        cache._redis.set_json(DEMO_SEED_KEY, marker, cache.settings.recording_ttl_s)
    return warmed


def semantic_cache_warning(cache: AnswerCache) -> str | None:
    """The warm hit needs FF_SEMANTIC_CACHE=true on the API. This runs with the API's env."""
    if cache.settings.semantic_cache:
        return None
    return (
        "WARNING: FF_SEMANTIC_CACHE is off for the API. The warmed runs are in Redis, but a repeat "
        "question is answered live (or 429) until FF_SEMANTIC_CACHE=true is set in api/.env and "
        "the api container is recreated."
    )


def reset(cache: AnswerCache) -> int:
    """Delete the Redis keys seed wrote, and the marker. H-MEM keeps its memories."""
    marker = cache.demo_seeded()
    if marker is None:
        print("  cache: no demo-seed marker in Redis; nothing to remove.")
    else:
        keys = [k for k in (marker.get("keys") or []) if isinstance(k, str)]
        if cache._redis is not None:
            cache._redis.delete(*keys, DEMO_SEED_KEY)
        print(f"  cache: removed {len(keys)} warmed keys and the marker.")
    print("  memory: H-MEM has no delete route. To start empty, stop the stack and remove the")
    print("          engines volume: python tasks.py down, then docker volume rm floodsense-app_engines")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.demo_seed", description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["seed", "reset"])
    p.add_argument("--engines-url", default=os.environ.get("ENGINES_URL") or "http://engines:8300")
    p.add_argument("--agents-url", default=os.environ.get("AGENTS_URL") or "http://agents:8100")
    p.add_argument("--skip-memory", action="store_true")
    p.add_argument("--skip-cache", action="store_true")
    args = p.parse_args(argv)
    cache = AnswerCache()
    if args.action == "reset":
        return reset(cache)
    print("Demo seed (labelled: reviewer demo-seed, note 'seeded for demo')")
    warning = semantic_cache_warning(cache)
    if warning:
        print(warning)
    code = 0
    if not args.skip_memory:
        try:
            n = seed_memory(args.engines_url)
            print(f"  memory: {n} new memories")
        except httpx.HTTPError as e:
            print(f"  memory: engines not reachable or refused the store ({type(e).__name__})")
            code = 1
    if not args.skip_cache:
        try:
            warm_cache(args.agents_url, cache)
        except httpx.HTTPError as e:
            print(f"  cache: agents not reachable ({type(e).__name__})")
            code = 1
    if warning and not args.skip_cache:
        print(warning)
    print(json.dumps({"done": code == 0}))
    return code


if __name__ == "__main__":
    sys.exit(main())
