"""Agents service. FastAPI on port 8100, unpublished; the API container proxies it.

Routes follow the contract in docs/GAMEPLAN.md. Every data response carries
served_from (live | cache | replay) and cached_at when it is not live.
Fake Zetaris, the seed schema, a replay clock, and a re-read are not live.
GET /health is liveness only and may say live. Other envelopes follow the
data plane. A run posted with replay_ts stays replay when it is read back.

The product UI is the Vite console in ``ui/`` (compose port 15173). This
service does not ship ``ui/app`` or ``ui/mock``. ``GET /`` and ``GET /console``
serve ``console.html``, a secondary operator page on this unpublished port.

GET  /  and  GET /console          secondary operator page (console.html)
GET  /desk/events                  every known event and the case standing on it
GET  /desk/events/{id}             one case; starts it if nobody has
GET  /runs/{id}/outbound           approved messages per exposed site (never sent from here)
GET  /runs/{id}/exposure.csv       exposed policies for the claims system
GET  /runs/{id}/verify             every agent step checked, plus which data path it used
GET  /runs/{id}/record             the decision record: answer, sources, scores, signature
POST /runs/{id}/dispatch           post the decision to DECISION_WEBHOOK, off unless set
GET  /health                       liveness: service, graph, version. Touches nothing.
GET  /ready                        readiness: Zetaris answers a trivial query (503 if not)
GET  /version                      build sha and timestamp
GET  /config                       flags, lanes, schema, checkpointer (no secrets)
GET  /readiness                    the eight foundations checked against the newest run
POST /runs                         RunRequest -> runs until the HITL interrupt; returns the run snapshot (status awaiting_approval)
GET  /runs/past                    runs started by this process, newest first (the checkpointer holds every run's state)
GET  /runs/{id}                    snapshot: contract state + claims, evidence, judge_summary, trace
GET  /runs/{id}/replay             the same run labelled as a replay (served_from replay, cached_at its start)
GET  /runs/{id}/approval           what the reviewer sees (409 unless awaiting approval)
POST /runs/{id}/approval           ApprovalDecision {action: approve|edit|reject, edits?, reviewer_note?, reviewer?} -> resumes the run
GET  /runs/{id}/citations          every citation record of the run plus the evidence and provenance they point at
GET  /runs/{id}/events             SSE: the run's trace replayed in order, then one `status` event. POST /runs finishes the graph first, so this is not a live feed yet

    python -m floodsense_agents            # host: http://127.0.0.1:8100
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from floodsense_agents import __version__
from floodsense_agents import desk, labelling
from floodsense_agents.events import spec
from floodsense_agents.models import ApprovalDecision, RunRequest
from floodsense_agents.readiness import report as readiness_report
from floodsense_agents.verify import report as verify_report
from floodsense_agents.runtime import NotAwaitingApproval, RunNotFound, Runtime, ThreadNotFound
from floodsense_agents.settings import settings
from floodsense_agents.zetaris import now_utc

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = FastAPI(title="FloodSense EU — agents", version=__version__)
CONSOLE = Path(__file__).resolve().parent / "console.html"
# The desk asks the graph the same thing every time; the operator picks the
# event, not the wording.
_DESK_QUESTION = desk.DESK_QUESTION
_rt: Runtime | None = None


def runtime() -> Runtime:
    global _rt
    if _rt is None:
        _rt = Runtime()
    return _rt


def set_runtime(rt: Runtime) -> None:
    global _rt
    _rt = rt


def _envelope(body: dict) -> dict:
    """Label a response that is not itself a finished computation.

    Does not force live. FakeZetaris and the seed schema become replay.
    A caller that already set served_from keeps that value, so GET /health
    can stay a liveness check.
    """
    zetaris = None
    if _rt is not None and getattr(_rt, "deps", None) is not None:
        zetaris = _rt.deps.zetaris
    return labelling.labelled(body, zetaris=zetaris)


def _with_run_label(body: dict, run: dict) -> dict:
    """An envelope that holds a run uses that run's label, not a fresh live one."""
    body["served_from"] = run.get("served_from")
    body["cached_at"] = run.get("cached_at")
    body["run_id"] = run.get("run_id")
    return labelling.labelled(body)


def _stored(run_id: str) -> dict:
    """A snapshot of a run computed earlier. Serving it as live would be a lie.

    A clocked replay stays replay. Only a re-read with no replay clock is cache.

    The label comes from the in-memory index when this process has the row.
    After a restart that row is missing, so this records the snapshot it just
    read. It does not call past(), which lists every checkpoint.
    """
    rt = runtime()
    run = rt.snapshot(run_id)
    row = rt.index.get(run_id)
    if row is None:
        row = rt._remember(run_id, run)
    kind, at = labelling.reread_label(
        run.get("cached_at") or row.get("created_at"),
        replay_ts=run.get("replay_ts"),
    )
    run["served_from"] = kind
    run["cached_at"] = at
    return run


def _console() -> HTMLResponse:
    """Secondary operator page. The product UI is the Vite app, not this file."""
    if not CONSOLE.is_file():
        raise HTTPException(404, "operator console was not copied into the build")
    return HTMLResponse(
        CONSOLE.read_text(encoding="utf-8"),
        headers={"cache-control": "no-store, must-revalidate"},
    )


@app.get("/", include_in_schema=False)
def home():
    return _console()


@app.get("/console", include_in_schema=False)
def console():
    return _console()


@app.get("/desk/events", include_in_schema=False)
def desk_events():
    """What the desk opens on: every known event, and the case on it."""
    events = desk.events(runtime().past())
    body: dict = {"events": events}
    stamped = [e.get("updated_at") for e in events if e.get("run_id") and e.get("updated_at")]
    if stamped:
        # The list points at runs computed earlier. The catalog itself is not a live answer.
        body["served_from"] = labelling.CACHE
        body["cached_at"] = stamped[0]
    return _envelope(body)


@app.get("/desk/events/{event_id}", include_in_schema=False)
def desk_event(event_id: str):
    """The case for one event. Starts it if nobody has yet."""
    rt = runtime()
    row = next(
        (r for r in rt.past() if r.get("event_id") == event_id and desk.is_case(r)),
        None,
    )
    if row is not None:
        run = _stored(row["run_id"])
    else:
        try:
            run = rt.start(RunRequest(question=_DESK_QUESTION, event_id=event_id))
        except KeyError as e:
            raise HTTPException(400, str(e).strip('"')) from e
    run = labelling.labelled(run)
    return _with_run_label(
        {"run": run, "figures": desk.summarise(run), "released": desk.is_released(run)},
        run,
    )


_TIMELINE: dict[str, dict] = {}


@app.get("/desk/events/{event_id}/timeline", include_in_schema=False)
def desk_timeline(event_id: str):
    """The same question asked at each declared moment of the event.

    What was knowable when: the chain fills in, the footprint appears only
    once Copernicus published it, and the gauge going out is visible as the
    reading that stops rather than as a gap nobody mentions.
    """
    if event_id in _TIMELINE:
        cached = dict(_TIMELINE[event_id])
        cached["served_from"] = labelling.CACHE
        return labelling.labelled(cached)
    try:
        ev = spec(event_id)
    except KeyError as e:
        raise HTTPException(400, str(e).strip('"')) from e
    rt = runtime()
    points = []
    for ts, label in ev.moments:
        try:
            run = rt.start(RunRequest(question=_DESK_QUESTION, event_id=event_id, replay_ts=ts))
            point = desk.moment(run)
        except Exception as e:  # noqa: BLE001 - one bad moment must not lose the rest
            point = {"replay_ts": ts, "error": f"{type(e).__name__}: {e}"[:160]}
        point["label"] = label
        points.append(point)
    body = {
        "event_id": event_id,
        "name": ev.name,
        "footprint_published_utc": ev.footprint_published_utc,
        "moments": points,
        # Each moment is a replay of the event. The first response is that
        # replay; a later read of this dict is cache (see the branch above).
        "served_from": labelling.REPLAY,
        "cached_at": now_utc(),
    }
    _TIMELINE[event_id] = body
    return labelling.labelled(dict(body))


@app.get("/desk/dispatch-target", include_in_schema=False)
def desk_dispatch_target():
    raw = desk.webhook_target()
    target = raw if raw and desk.is_https_url(raw) else None
    return _envelope({"configured": target is not None, "target": target})


def _released_run(run_id: str) -> dict:
    run = _stored(run_id)
    if not desk.is_released(run):
        raise HTTPException(409, "nothing is released until a reviewer approves or edits")
    return run


@app.get("/runs/{run_id}/outbound", include_in_schema=False)
def run_outbound(run_id: str):
    """The messages, rendered. This endpoint does not send them."""
    run = _released_run(run_id)
    return _with_run_label({"messages": desk.outbound(run)}, run)


@app.get("/runs/{run_id}/exposure.csv", include_in_schema=False)
def run_exposure_csv(run_id: str):
    return PlainTextResponse(
        desk.exposure_csv(_released_run(run_id)),
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="exposure-{run_id}.csv"'},
    )


@app.get("/runs/{run_id}/verify", include_in_schema=False)
def run_verify(run_id: str):
    """Every agent step, checked against the run's own record."""
    return _envelope(verify_report(_stored(run_id)))


@app.get("/runs/{run_id}/record", include_in_schema=False)
def run_record(run_id: str):
    return _envelope(desk.record(_stored(run_id)))


@app.post("/runs/{run_id}/dispatch", include_in_schema=False)
def run_dispatch(run_id: str):
    """Post the decision to the nominated endpoint. Off unless one is set."""
    run = _released_run(run_id)
    return _with_run_label(desk.dispatch(run), run)


@app.get("/readiness", include_in_schema=False)
def readiness(run_id: str | None = None):
    """The eight foundations, checked against one run. Newest run by default."""
    rt = runtime()
    if run_id is None:
        past = rt.past(limit=1)
        run_id = past[0]["run_id"] if past else None
    run = _stored(run_id) if run_id else {}
    routes = {getattr(r, "path", "") for r in app.routes}
    return _envelope(readiness_report(run, rt.deps, routes))


def _dep_name(rt: Runtime, attr: str) -> str:
    return type(getattr(rt.deps, attr, None)).__name__ if rt.deps else "injected"


@app.get("/health")
def health():
    # Liveness only. A slow probe here marks every app on the node unhealthy.
    # served_from live here is the process, not a Zetaris answer. Data-plane
    # routes leave it unset so FakeZetaris cannot inherit this label.
    return labelling.labelled(
        {
            "status": "ok",
            "service": "floodsense-agents",
            "graph": "compiled",
            "version": __version__,
            "served_from": labelling.LIVE,
            "cached_at": None,
        }
    )


@app.get("/ready")
def ready():
    rt = runtime()
    try:
        probe = rt.deps.zetaris.run_sql("SELECT 1")
    except Exception as e:
        raise HTTPException(503, f"zetaris unreachable: {type(e).__name__}")
    # run_sql reports a failed read on Evidence.error. It does not raise.
    if probe is None or getattr(probe, "error", None):
        detail = getattr(probe, "error", None) or "no result"
        raise HTTPException(503, f"zetaris unreachable: {detail}")
    return _envelope(
        {
            "status": "ready",
            "llm": _dep_name(rt, "llm"),
            "zetaris": _dep_name(rt, "zetaris"),
            "memory": _dep_name(rt, "memory"),
            "world_model": _dep_name(rt, "world"),
        }
    )


@app.get("/version")
def version():
    return _envelope({"sha": settings.git_sha, "built": settings.built_at, "version": __version__})


@app.get("/config")
def config():
    return _envelope(
        {
            "flags": {
                "FF_LIVE_DATA": settings.live_data,
                "FF_SKEPTIC": settings.ff_skeptic,
                "FF_JUDGE": settings.ff_judge,
                "FF_HITL": settings.ff_hitl,
                "FF_HMEM": settings.ff_hmem,
                "FF_RAG_DOCS": settings.ff_rag_docs,
            },
            "lanes": {"fast": settings.lane("fast"), "deep": settings.lane("deep")},
            "engines_url": settings.engines_url,
            "schema": settings.schema,
            "checkpointer": settings.checkpointer,
            "skeptic_max_rounds": settings.skeptic_max_rounds,
            "judge_repair_rounds": settings.judge_repair_rounds,
            "judge_min_score": settings.judge_min_score,
            "events": ["EMSR773", "EMSR517"],
        }
    )


@app.post("/runs", status_code=201)
def start_run(req: RunRequest):
    try:
        return _envelope(runtime().start(req))
    except ThreadNotFound as e:
        raise HTTPException(404, f"thread {e.args[0]} not found; omit thread_id to start one")
    except KeyError as e:
        raise HTTPException(422, str(e))


@app.get("/runs/past")
def past_runs(limit: int = 50, thread_id: str | None = None):
    return _envelope({"runs": runtime().past(limit, thread_id=thread_id)})


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    try:
        return _envelope(_stored(run_id))
    except RunNotFound:
        raise HTTPException(404, f"run {run_id} not found")


@app.get("/runs/{run_id}/replay")
def replay_run(run_id: str):
    """A recorded run, labelled as a replay.

    cached_at is the run's start. The row comes from the in-memory index, or
    from the snapshot just read after a restart. This does not call past(),
    which lists every checkpoint and deadlocks the shared SqliteSaver.
    """
    rt = runtime()
    try:
        run = rt.snapshot(run_id)
    except RunNotFound:
        raise HTTPException(404, f"run {run_id} not found")
    row = rt.index.get(run_id)
    if row is None:
        row = rt._remember(run_id, run)
    run["served_from"] = labelling.REPLAY
    run["cached_at"] = row.get("created_at")
    return _envelope(run)


@app.get("/runs/{run_id}/approval")
def get_approval(run_id: str):
    try:
        return _envelope(runtime().approval(run_id))
    except RunNotFound:
        raise HTTPException(404, f"run {run_id} not found")
    except NotAwaitingApproval as e:
        raise HTTPException(409, str(e))


@app.post("/runs/{run_id}/approval")
def post_approval(run_id: str, decision: ApprovalDecision):
    if decision.action == "edit" and not (decision.edits or "").strip():
        raise HTTPException(422, "action=edit requires edits")
    try:
        return _envelope(runtime().resume(run_id, decision))
    except RunNotFound:
        raise HTTPException(404, f"run {run_id} not found")
    except NotAwaitingApproval as e:
        raise HTTPException(409, str(e))


@app.get("/runs/{run_id}/citations")
def get_citations(run_id: str):
    try:
        return _envelope(runtime().citations(run_id))
    except RunNotFound:
        raise HTTPException(404, f"run {run_id} not found")


@app.get("/runs/{run_id}/events")
async def events(run_id: str):
    rt = runtime()
    try:
        rt.snapshot(run_id)
    except RunNotFound:
        raise HTTPException(404, f"run {run_id} not found")

    async def gen():
        sent, t0 = 0, time.time()
        while time.time() - t0 < 900:
            s = rt.snapshot(run_id)
            for ev in s["trace"][sent:]:
                yield f"event: trace\ndata: {json.dumps(ev)}\n\n"
            sent = len(s["trace"])
            if s["status"] != "running":
                done = {
                    "run_id": run_id,
                    "status": s["status"],
                    "served_from": s["served_from"],
                    "cached_at": s["cached_at"],
                }
                yield f"event: status\ndata: {json.dumps(done)}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
