"""FloodSense EU API.

The UI and the demo call this service on host port 18000. It owns the public
contract (docs/GAMEPLAN.md) and proxies the run lifecycle to the agents
service at AGENTS_URL: http://agents:8100 under Compose, 127.0.0.1:8100 on the
host.

``POST /runs`` and ``GET /runs/{id}`` gain a ``contract`` object: a projection
of the graph snapshot onto ``contracts/schemas/floodsense.schema.json``.
The graph payload stays beside it. Approval and citation payloads are left
alone. Fake, seed, and replay answers are not relabelled live here.
A semantic-cache hit is labelled cache by this service: a clocked run read
back from the agents still says replay, and that banner must not leak.

The semantic cache and labelled replay sit here, in front of the proxy, each
behind its flag (FF_SEMANTIC_CACHE, FF_CACHED_REPLAY; see app/cache.py). A
cached or replayed answer is never presented as live. Cache and replay
lookups use CACHE_LOOKUP_TIMEOUT_S, not the 600s run budget. Rate limits
(app/ratelimit.py) guard POST /runs with a per-client token bucket and cap live runs in flight; both answer 429 with
Retry-After. GET routes are not limited.

GET  /health                      this service
GET  /config                      flags and lanes, from the agents
POST /runs                        start a run; returns when the graph pauses for human approval
                                  (thread_id continues a conversation: short-term thread memory)
                                  200 + served_from cache: a repeat of a finished question (FF_SEMANTIC_CACHE)
                                  200 + served_from replay: the live run failed (FF_CACHED_REPLAY)
                                  {"fresh": true} skips the cache
GET  /runs/past                   earlier runs (?thread_id= for one conversation)
GET  /runs/{id}                   run snapshot
GET  /runs/{id}/replay            a recorded run, labelled replay
GET  /runs/{id}/events            SSE trace stream (proxied as-is)
GET  /runs/{id}/approval          the approval payload (409 unless awaiting approval)
POST /runs/{id}/approval          {action: approve | edit | reject, edits?, reviewer_note?, reviewer?}
GET  /runs/{id}/citations         citation records + evidence + provenance
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.cache import (
    AnswerCache,
    annotate_replay,
    approved_by_a_person,
    is_follow_up,
    mark_cached,
    past_row_matches,
    same_ask,
)
from app.project import project_run
from app.ratelimit import RateLimiter

AGENTS_URL = os.environ.get("AGENTS_URL", "http://127.0.0.1:8100").rstrip("/")
UI_ORIGINS = [
    o
    for o in os.environ.get("UI_ORIGINS", "http://localhost:15173,http://127.0.0.1:15173").split(
        ","
    )
    if o
]
# Full run snapshots only. /runs/{id}/approval and /citations are thinner
# and must not grow a contract that fills missing citation URLs.
# /runs/{id}/replay is the same snapshot, labelled replay, so it projects too.
_RUN_SNAPSHOT = re.compile(r"^/runs/[^/]+(?:/replay)?$")

TIMEOUT = httpx.Timeout(
    600.0, connect=5.0
)  # a run waits for the deep lane; the connect timeout stays short

app = FastAPI(title="FloodSense EU", version="0.12.0")
cache = AnswerCache()
limiter = RateLimiter()
app.add_middleware(
    CORSMiddleware, allow_origins=UI_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"]
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "floodsense-api"}


def _lookup_timeout() -> httpx.Timeout:
    """Budget for a cache or replay lookup. Not the 600s a live run may take."""
    seconds = cache.settings.lookup_timeout_s
    return httpx.Timeout(seconds, connect=min(5.0, seconds))


async def _agents_request(
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.Response:
    """One async client for every proxied call. SSE uses its own stream below."""
    async with httpx.AsyncClient(timeout=timeout or TIMEOUT) as client:
        return await client.request(method, f"{AGENTS_URL}{path}", json=body, params=params)


def _attach_contract(path: str, response: Response) -> Response:
    """Add the schema projection on POST /runs, GET /runs/{id} and GET /runs/{id}/replay."""
    if response.status_code >= 400:
        return response
    if path != "/runs" and _RUN_SNAPSHOT.match(path) is None:
        return response
    media = response.media_type or ""
    if "json" not in media:
        return response
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError:
        return response
    if not isinstance(payload, dict):
        return response
    projected = project_run(payload)
    if projected is None:
        return response
    payload["contract"] = projected
    return Response(
        content=json.dumps(payload),
        status_code=response.status_code,
        media_type="application/json",
    )


def _json_run(payload: dict, status_code: int) -> JSONResponse:
    """A cache or replay body. The same projection as a live run snapshot."""
    projected = project_run(payload)
    if projected is not None:
        payload["contract"] = projected
    return JSONResponse(payload, status_code=status_code)


async def _forward(
    method: str, path: str, body: dict | None = None, params: dict | None = None
) -> Response:
    try:
        r = await _agents_request(method, path, body=body, params=params)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"agents service unreachable at {AGENTS_URL}: {type(e).__name__}")
    response = Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )
    return _attach_contract(path, response)


async def _agents_json(
    method: str,
    path: str,
    params: dict | None = None,
    timeout: httpx.Timeout | None = None,
) -> tuple[int, Any]:
    """Call the agents and parse JSON. (503, None) when they cannot be reached."""
    try:
        r = await _agents_request(method, path, params=params, timeout=timeout)
    except httpx.HTTPError:
        return 503, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


async def _agents_config() -> dict | None:
    code, data = await _agents_json("GET", "/config")
    return data if code == 200 and isinstance(data, dict) else None


async def _flag_fingerprint() -> str | None:
    """The agents' flag fingerprint. None when /config cannot be read.

    The cache memos this. A fresh memo skips another /config call. The fetch
    is async and uses the short lookup timeout, so a hung agents service does
    not hold a cache probe for the whole run budget.
    """
    memo = cache.cached_flags()
    if memo is not None:
        return memo
    code, data = await _agents_json("GET", "/config", timeout=_lookup_timeout())
    config = data if code == 200 and isinstance(data, dict) else None
    return cache.flags(lambda: config)


async def _from_cache(body: dict) -> dict | None:
    """The original run for a repeat of a finished question, or None.

    GET /runs/{id} keeps a clocked run labelled replay. A cache hit is cache,
    and the historical clock on that body is left as it is.
    """
    flags = await _flag_fingerprint()
    if flags is None:
        return None
    entry = cache.lookup(body, flags)
    if entry is None:
        return None
    code, run = await _agents_json("GET", f"/runs/{entry.run_id}", timeout=_lookup_timeout())
    if code != 200 or not isinstance(run, dict):
        cache.drop(entry.run_id)  # the agents no longer hold it
        return None
    age = int(time.time() - entry.stored_at)
    run["cache"] = {
        "original_run_id": entry.run_id,
        "age_s": age,
        "expires_in_s": max(0, int(entry.ttl_s - age)),
    }
    return mark_cached(run)


def _failed_run_id(payload: Any) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("run_id"), str):
        return payload["run_id"]
    return None


def _live_failure(resp: Response) -> tuple[str, str | None] | None:
    """Why the live run failed, and that run's id when the body has one."""
    if resp.status_code >= 500:
        try:
            payload = json.loads(resp.body)
        except ValueError:
            payload = None
        return f"the agents answered HTTP {resp.status_code}", _failed_run_id(payload)
    if resp.status_code in (200, 201):
        try:
            run = json.loads(resp.body)
        except ValueError:
            return None
        if isinstance(run, dict) and run.get("status") == "failed":
            detail = str(run.get("error") or "no detail")[:200]
            return f"the live run failed: {detail}", _failed_run_id(run)
    return None


async def _replay_from_agents(body: dict) -> dict | None:
    """The newest recorded run of this question, or None when the agents cannot say.

    A timed-out read stops the scan. The caller then uses the in-process recording
    rather than waiting out the rest of the list.
    """
    timeout = _lookup_timeout()
    code, past = await _agents_json("GET", "/runs/past", params={"limit": 200}, timeout=timeout)
    if code == 503 and past is None:
        return None
    rows = past.get("runs") if code == 200 and isinstance(past, dict) else None
    for row in rows or []:
        if not past_row_matches(body, row):
            continue
        c, run = await _agents_json("GET", f"/runs/{row['run_id']}/replay", timeout=timeout)
        if c == 503 and run is None:
            return None
        if c == 200 and isinstance(run, dict) and same_ask(body, run):
            return run
    return None


async def _replay_for(
    body: dict,
    reason: str,
    *,
    agents_down: bool = False,
    failed_run_id: str | None = None,
) -> dict | None:
    """A person-approved recording of this same question, or None.

    A follow-up (thread_id) is not replayed. When the agents are unreachable
    the in-process recording is used and the past list is not scanned.
    """
    if body.get("thread_id"):
        return None
    replay = None if agents_down else await _replay_from_agents(body)
    if replay is None:
        replay = cache.recording_for(body)
    if replay is None:
        return None
    return annotate_replay(replay, reason, failed_run_id=failed_run_id)


@app.get("/config")
async def config() -> Response:
    code, data = await _agents_json("GET", "/config")
    if code == 503 and data is None:
        raise HTTPException(503, f"agents service unreachable at {AGENTS_URL}")
    if code != 200 or not isinstance(data, dict):
        return await _forward("GET", "/config")
    data["api_cache"] = cache.stats()
    return JSONResponse(data)


def _too_many(detail: str, retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"detail": detail, "served_from": None, "cached_at": None},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _bucket_refusal(request: Request) -> JSONResponse | None:
    wait = limiter.buckets.take(_client_key(request))
    if wait is None:
        return None
    return _too_many("rate limit: too many requests from this client", wait)


@app.post("/runs", status_code=201)
async def start_run(request: Request) -> Response:
    refused = _bucket_refusal(request)
    if refused is not None:
        return refused
    body = await request.json()
    fresh = bool(body.pop("fresh", False)) if isinstance(body, dict) else False
    settings = cache.settings
    if settings.semantic_cache and not fresh and isinstance(body, dict):
        hit = await _from_cache(body)
        if hit is not None:
            return _json_run(hit, 200)
    if not limiter.slots.try_acquire():
        if settings.cached_replay and isinstance(body, dict):
            replay = await _replay_for(body, "too many live runs in flight")
            if replay is not None:
                return _json_run(replay, 200)
        return _too_many(
            "rate limit: too many runs in flight, try again shortly",
            limiter.settings.concurrency_retry_after_s,
        )
    try:
        resp = await _forward("POST", "/runs", body=body)
    except HTTPException as e:
        if settings.cached_replay and isinstance(body, dict):
            replay = await _replay_for(
                body,
                f"the agents could not be reached ({e.detail})",
                agents_down=True,
            )
            if replay is not None:
                return _json_run(replay, 200)
        raise
    finally:
        limiter.slots.release()  # a replay fallback above is a short lookup
    if settings.cached_replay and isinstance(body, dict):
        failure = _live_failure(resp)
        if failure:
            reason, failed_id = failure
            replay = await _replay_for(body, reason, failed_run_id=failed_id)
            if replay is not None:
                return _json_run(replay, 200)
    return resp


@app.get("/runs/past")
async def past_runs(limit: int = 50, thread_id: str | None = None) -> Response:
    params: dict = {"limit": limit}
    if thread_id:
        params["thread_id"] = thread_id
    return await _forward("GET", "/runs/past", params=params)


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> Response:
    return await _forward("GET", f"/runs/{run_id}")


@app.get("/runs/{run_id}/approval")
async def get_approval(run_id: str) -> Response:
    return await _forward("GET", f"/runs/{run_id}/approval")


@app.post("/runs/{run_id}/approval")
async def post_approval(run_id: str, request: Request) -> Response:
    resp = await _forward("POST", f"/runs/{run_id}/approval", body=await request.json())
    settings = cache.settings
    if resp.status_code == 200 and (settings.semantic_cache or settings.cached_replay):
        try:
            run = json.loads(resp.body)
        except ValueError:
            return resp
        if settings.semantic_cache:
            flags = await _flag_fingerprint()
            if flags is not None:
                cache.remember(run, flags)
        if settings.cached_replay and approved_by_a_person(run) and not is_follow_up(run):
            code, replay = await _agents_json(
                "GET", f"/runs/{run_id}/replay", timeout=_lookup_timeout()
            )
            if code == 200 and isinstance(replay, dict):
                cache.record(replay)
    return resp


@app.get("/runs/{run_id}/replay")
async def get_replay(run_id: str) -> Response:
    return await _forward("GET", f"/runs/{run_id}/replay")


@app.get("/runs/{run_id}/citations")
async def get_citations(run_id: str) -> Response:
    return await _forward("GET", f"/runs/{run_id}/citations")


@app.get("/runs/{run_id}/events")
async def events(run_id: str) -> StreamingResponse:
    async def gen():
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                async with client.stream("GET", f"{AGENTS_URL}/runs/{run_id}/events") as r:
                    if r.status_code != 200:
                        yield f'event: error\ndata: {{"status": {r.status_code}}}\n\n'
                        return
                    async for chunk in r.aiter_text():
                        yield chunk
        except httpx.HTTPError as e:
            yield f'event: error\ndata: {{"error": "agents service unreachable: {type(e).__name__}"}}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")
