"""Watchers. Deterministic SQL over the contract views.

Scans the event window, cut at replay_ts, so the Investigator starts from
anomalies that each carry a query_id. Reads gauge_levels for that window
when the event lists stations, and loads the provenance view once for
layer (b) citations. An event with no stations skips the gauge query.
Gauge rows stay evidence. They are not a new anomaly kind. No model call.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from floodsense_agents.governance import DEFINITIONS
from floodsense_agents.models import Anomaly, normalize_utc
from floodsense_agents.settings import settings
from floodsense_agents.state import Deps, FloodState, add_evidence, trace
from floodsense_agents.zetaris import run_sql_parallel


def last_complete_day(end_utc: str) -> str:
    """The last date whose daily aggregate is actually known at end_utc.

    S2: discharge_daily was filtered with end[:10], so a replay standing at
    noon read that whole day's total, which nobody had yet. A daily value is
    known once the day is over.
    """
    date, _, clock = end_utc.partition("T")
    if clock.rstrip("Z") >= "23:59":
        return date
    day = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def window(state: FloodState) -> tuple[str, str]:
    """The event window, cut at the replay clock.

    The clock is re-checked here because these values are interpolated into
    SQL predicates, and state can be resumed from a checkpoint written by an
    older build.
    """
    ev = state["event"]
    try:
        end = normalize_utc(str(state.get("replay_ts") or ev["window_to_utc"]))
        start = normalize_utc(str(ev["window_from_utc"]))
        cap = normalize_utc(str(ev["window_to_utc"]))
    except ValueError as e:
        raise ValueError(f"replay_ts is not a UTC instant: {state.get('replay_ts')!r}") from e
    return start, min(end, cap)


def make(deps: Deps):
    def watchers(state: FloodState) -> dict:
        t = time.time()
        s = settings.schema
        rain_at = DEFINITIONS["anomaly_rain"]
        flow_at = DEFINITIONS["anomaly_discharge"]
        t0, t1 = window(state)
        clock = (t0, t1)
        q = {
            "rain": (
                f"SELECT point_id, ts_utc, rain_mm FROM {s}.hazard_timeline WHERE ts_utc "
                f"BETWEEN ? AND ? AND rain_mm >= {rain_at.value} ORDER BY rain_mm DESC",
                clock,
            ),
            "discharge": (
                f"SELECT point_id, ts_utc, discharge_m3s FROM {s}.hazard_timeline WHERE "
                f"ts_utc BETWEEN ? AND ? AND discharge_m3s >= {flow_at.value} "
                f"ORDER BY discharge_m3s DESC",
                clock,
            ),
            "warning": (
                f"SELECT point_id, MIN(ts_utc) AS first_utc, warning_level FROM "
                f"{s}.hazard_timeline "
                f"WHERE ts_utc BETWEEN ? AND ? "
                f"AND warning_level IS NOT NULL GROUP BY point_id, warning_level ORDER BY first_utc",
                clock,
            ),
        }
        # Valencia lists none. The Ahr lists the Rhine gauges between Koblenz and Bonn.
        if state["event"].get("gauges"):
            q["gauges"] = (
                f"SELECT station, water, ts_utc, level_cm, source FROM {s}.gauge_levels "
                f"WHERE ts_utc BETWEEN ? AND ? ORDER BY station, ts_utc",
                clock,
            )
        # View queries, in dict order, then provenance. None of them depend
        # on another, so they run together. Evidence order follows this list.
        ordered = [
            *q.items(),
            (
                "provenance",
                (
                    f"SELECT dataset, source_url, publisher, licence, attribution, fetched_at FROM "
                    f"{s}.provenance",
                    None,
                ),
            ),
        ]
        ran = run_sql_parallel(deps.zetaris, [job for _name, job in ordered])
        by_name = {name: evidence for (name, _job), evidence in zip(ordered, ran)}
        evid = {name: by_name[name] for name in q}
        prov = by_name["provenance"]
        items: list[Anomaly] = []
        for r in evid["rain"].rows_sample[:5]:
            items.append(
                Anomaly(
                    id=f"A{len(items) + 1}",
                    kind="rain",
                    point_id=r["point_id"],
                    ts_utc=r["ts_utc"],
                    value=r["rain_mm"],
                    unit="mm/h",
                    why=rain_at.wording,
                    query_id=evid["rain"].query_id,
                )
            )
        for r in evid["discharge"].rows_sample[:3]:
            items.append(
                Anomaly(
                    id=f"A{len(items) + 1}",
                    kind="discharge",
                    point_id=r["point_id"],
                    ts_utc=r["ts_utc"],
                    value=r["discharge_m3s"],
                    unit="m3/s",
                    why=flow_at.wording,
                    query_id=evid["discharge"].query_id,
                )
            )
        for r in evid["warning"].rows_sample:
            items.append(
                Anomaly(
                    id=f"A{len(items) + 1}",
                    kind="warning",
                    point_id=r["point_id"],
                    ts_utc=r["first_utc"],
                    why=f"warning level {r['warning_level']}",
                    query_id=evid["warning"].query_id,
                )
            )
        return {
            "anomalies": [i.model_dump() for i in items],
            "evidence": add_evidence(state, *evid.values(), prov),
            "provenance": prov.rows_sample,
            "status": "running",
            "trace": trace(
                state,
                "watchers",
                f"{len(items)} anomalies in window {t0[:16]}..{t1[:16]} ({len(evid)} view "
                f"queries)",
                lane="sql",
                started=t,
                evidence_ids=[e.query_id for e in evid.values()],
            ),
        }

    return watchers
