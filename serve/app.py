"""The one app this container serves.

Mounts the team's API under /api and the built UI at /. The four endpoints
the platform asks for live here, because they describe the container rather
than any one service inside it.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.main import app as api_app  # api/app/main.py, mirrored from main
from serve import views

AGENTS_URL = os.environ.get("AGENTS_URL", "http://127.0.0.1:8100").rstrip("/")
DIST = Path(os.environ.get("UI_DIST", "/srv/ui")).resolve()

app = FastAPI(title="FloodSense EU — console", version=api_app.version)


@app.get("/health")
def health() -> dict[str, str]:
    """Process liveness only. It must not wait on anything behind it:
    a slow dependency here marks the whole node unhealthy."""
    return {"status": "ok", "service": "floodsense-console"}


@app.get("/ready")
async def ready() -> JSONResponse:
    """Ready when the graph behind the API answers, and not before."""
    checks: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in (("agents", f"{AGENTS_URL}/ready"),):
            try:
                r = await client.get(url)
                checks[name] = "ok" if r.status_code == 200 else f"http {r.status_code}"
            except httpx.HTTPError as e:
                checks[name] = type(e).__name__
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)


@app.get("/version")
def version() -> dict[str, str]:
    return {
        "sha": os.environ.get("GIT_SHA", "dev"),
        "built": os.environ.get("BUILT_AT", "unknown"),
        "source": os.environ.get("SOURCE_REF", "main"),
    }


# Order matters, twice over. /api/views is claimed before /api, so the view
# paths reach the warehouse instead of the team's API, which does not serve
# them; and /api is claimed before the UI takes everything else.
app.mount("/api/views", views.app)
app.mount("/api", api_app)


@app.on_event("startup")
async def _warm_views() -> None:
    """A mounted app has no lifespan of its own, so the warehouse snapshot is
    started here. Without it the console's 1500 ms fetch would wait on Zetaris
    and fall back to its fixtures."""
    views.start_refresher()


@app.on_event("shutdown")
async def _stop_views() -> None:
    await views.stop_refresher()

if DIST.is_dir():
    # html=True serves index.html for a bare directory. The console routes on
    # the hash, so there is no history fallback to arrange.
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
