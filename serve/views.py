"""The four view paths the console probes, served from the warehouse.

`ui/src/config/scenario.ts` names them and `ui/src/lib/validate.ts` decides
whether a reply is usable: one malformed row and `parseRows` drops the whole
dataset back to the fixture, so every value is cast here rather than passed
through. Zetaris answers every column as a string, including numbers and
booleans.

A view that cannot be read answers 503. That is the case the console already
handles: it keeps the fixture and says so, which is better than a half-filled
desk presented as live.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from typing import Any, Callable

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

log = logging.getLogger("floodsense.views")

REST_URL = (os.environ.get("ZETARIS_REST_URL") or "").rstrip("/")
API_KEY = os.environ.get("ZETARIS_API_KEY") or ""
SCHEMA = os.environ.get("ZETARIS_SCHEMA") or "floodsense"
ROW_LIMIT = int(os.environ.get("VIEWS_ROW_LIMIT", "5000"))
# The console aborts a view fetch after 1500 ms (API_TIMEOUT_MS_DEFAULT), which
# no Zetaris round trip reliably beats. So a request is never allowed to wait on
# the warehouse: a refresher keeps a snapshot warm and every request is served
# from it. STALE_S bounds how long a snapshot may answer after a failed refresh.
REFRESH_S = float(os.environ.get("VIEWS_REFRESH_S", "120"))
STALE_S = float(os.environ.get("VIEWS_STALE_S", "900"))
TIMEOUT_S = float(os.environ.get("VIEWS_TIMEOUT_S", "25"))

app = FastAPI(title="FloodSense EU — views")

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _num(value: Any) -> float | None:
    """A float, or None. Zetaris sends '11.02'; the console wants 11.02."""
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _flag(value: Any) -> bool | None:
    """A real bool. `in_footprint` arrives as the string 'true'."""
    if isinstance(value, bool):
        return value
    text = _text(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in ("true", "yes", "1", "t"):
        return True
    if lowered in ("false", "no", "0", "f"):
        return False
    return None


async def _rows(sql: str) -> list[dict[str, Any]]:
    """One statement, one fresh queryId: the engine refuses a repeat."""
    body = {"sql": sql, "queryId": str(uuid.uuid4()), "limit": ROW_LIMIT}
    headers = {
        "authorization": f"Bearer {API_KEY}",
        "content-type": "application/json",
        # Cloudflare answers the default client with 403 error 1010.
        "user-agent": "floodsense-console/1.0",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        r = await client.post(f"{REST_URL}/sql-editor/sqls/run", json=body, headers=headers)
    r.raise_for_status()
    payload = r.json()
    names = payload.get("headers") or []
    return [dict(zip(names, row)) for row in (payload.get("data") or [])]


def _discharge(row: dict[str, Any]) -> dict[str, Any] | None:
    point, date = _text(row.get("point_id")), _text(row.get("date"))
    discharge, source = _num(row.get("discharge_m3s")), _text(row.get("source"))
    if not point or not date or discharge is None or not source:
        return None
    return {"point_id": point, "date": date[:10], "discharge_m3s": discharge, "source": source}


def _hazard(row: dict[str, Any]) -> dict[str, Any] | None:
    # ts_utc keeps the shape migration 007 wrote: the console's own regex
    # takes a zone-less stamp and reads a missing zone as UTC.
    point, stamp = _text(row.get("point_id")), _text(row.get("ts_utc"))
    rain = _num(row.get("rain_mm"))
    if not point or not stamp or rain is None:
        return None
    return {
        "point_id": point,
        "ts_utc": stamp,
        "rain_mm": rain,
        "discharge_m3s": _num(row.get("discharge_m3s")),
        "warning_level": _text(row.get("warning_level")),
    }


def _exposure(row: dict[str, Any]) -> dict[str, Any] | None:
    policy, site = _text(row.get("policy_id")), _text(row.get("site_id"))
    lat, lon = _num(row.get("lat")), _num(row.get("lon"))
    insured, segment = _num(row.get("sum_insured_eur")), _text(row.get("segment"))
    footprint = _flag(row.get("in_footprint"))
    if not policy or not site or lat is None or lon is None:
        return None
    if insured is None or not segment or footprint is None:
        return None
    out = {
        "policy_id": policy,
        "site_id": site,
        "lat": lat,
        "lon": lon,
        "in_footprint": footprint,
        "sum_insured_eur": insured,
        "segment": segment,
    }
    synthetic = _text(row.get("synthetic"))
    if synthetic:
        # The book is not a real one, and the desk says so from this field.
        out["synthetic"] = synthetic
    return out


def _provenance(row: dict[str, Any]) -> dict[str, Any] | None:
    fields = ("dataset", "source_url", "publisher", "licence", "attribution", "fetched_at")
    out = {name: _text(row.get(name)) for name in fields}
    if any(value is None for value in out.values()):
        return None
    if not str(out["source_url"]).startswith(("http://", "https://")):
        return None
    return out


VIEWS: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any] | None]]] = {
    "discharge_daily": (
        "SELECT point_id, date, discharge_m3s, source FROM {s}.discharge_daily "
        "ORDER BY point_id, date",
        _discharge,
    ),
    "hazard_timeline": (
        "SELECT point_id, ts_utc, rain_mm, discharge_m3s, warning_level "
        "FROM {s}.hazard_timeline ORDER BY point_id, ts_utc",
        _hazard,
    ),
    "exposure_join": (
        "SELECT policy_id, site_id, lat, lon, in_footprint, sum_insured_eur, segment, "
        "synthetic FROM {s}.exposure_join ORDER BY policy_id",
        _exposure,
    ),
    "provenance": (
        "SELECT dataset, source_url, publisher, licence, attribution, fetched_at "
        "FROM {s}.provenance ORDER BY dataset",
        _provenance,
    ),
}


async def _load(name: str) -> list[dict[str, Any]] | None:
    """Read one view and cast it. None when it cannot be used as it stands."""
    sql, cast = VIEWS[name]
    try:
        raw = await _rows(sql.format(s=SCHEMA))
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("views %s unavailable: %s", name, str(e)[:160])
        return None

    rows = [cast(row) for row in raw]
    kept = [row for row in rows if row is not None]
    if len(kept) != len(rows):
        # The console drops the whole dataset on one bad row, so a partial
        # answer would show the fixture anyway while looking like a success.
        log.warning("views %s: %d of %d rows unusable", name, len(rows) - len(kept), len(rows))
        return None
    return kept or None


async def _refresh() -> None:
    """Keep every view warm. Started once, runs for the life of the process."""
    while True:
        for name in VIEWS:
            rows = await _load(name)
            if rows is not None:
                _cache[name] = (time.monotonic(), rows)
        await asyncio.sleep(REFRESH_S)


_task: asyncio.Task | None = None


def start_refresher() -> None:
    """Called by the parent app. A mounted sub-app gets no lifespan of its own:
    Starlette runs startup and shutdown for the outermost app only."""
    global _task
    if _task is None and REST_URL and API_KEY:
        _task = asyncio.create_task(_refresh())


async def stop_refresher() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None


async def _serve(name: str) -> JSONResponse:
    if not REST_URL or not API_KEY:
        return JSONResponse({"detail": "no warehouse configured"}, status_code=503)

    hit = _cache.get(name)
    if hit and time.monotonic() - hit[0] < STALE_S:
        return JSONResponse(hit[1])

    # Only before the first refresh has landed. After that the refresher owns
    # the snapshot and this path is never the one the console waits on.
    rows = await _load(name)
    if rows is None:
        return JSONResponse({"detail": f"{name} unavailable"}, status_code=503)
    _cache[name] = (time.monotonic(), rows)
    return JSONResponse(rows)


@app.get("/discharge_daily")
async def discharge_daily() -> JSONResponse:
    return await _serve("discharge_daily")


@app.get("/hazard_timeline")
async def hazard_timeline() -> JSONResponse:
    return await _serve("hazard_timeline")


@app.get("/exposure_join")
async def exposure_join() -> JSONResponse:
    return await _serve("exposure_join")


@app.get("/provenance")
async def provenance() -> JSONResponse:
    return await _serve("provenance")
