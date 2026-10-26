"""Skeptic. Tries to disprove each hypothesis before it is trusted.

Runs at most SKEPTIC_MAX_ROUNDS SQL counter-checks per hypothesis and marks
it supported or not_supported. Counter-checks are deterministic predicates
over fresh queries, so a verdict is reproducible and every check has a
query_id. The fast lane only writes the rationale from the same rows.
How many checks run is SKEPTIC_MAX_ROUNDS (default 3). A smoke run can set
that to 1; the node does not hardcode the cap.
"""

from __future__ import annotations

import logging
import time

from floodsense_agents.governance import DEFINITIONS, IN_FOOTPRINT_SQL, OUTSIDE_FOOTPRINT_SQL
from floodsense_agents.models import Evidence, Hypothesis
from floodsense_agents.nightshift import parse_json
from floodsense_agents.nodes.watchers import last_complete_day, window
from floodsense_agents.prompts import SKEPTIC, rows_block
from floodsense_agents.settings import settings
from floodsense_agents.state import Deps, FloodState, add_evidence, trace

log = logging.getLogger("floodsense.skeptic")


def _checks_for(h: Hypothesis, state: FloodState) -> list[tuple[str, str, tuple[str, ...]]]:
    """(name, sql): each query must return >= 1 row for the check to pass."""
    s, ev = settings.schema, state["event"]
    t0, t1 = window(state)
    clock = (t0, t1)
    day = (t0[:10], last_complete_day(t1))
    rain_pts = ", ".join(f"'{p}'" for p in ev["rain_points"])
    river_pts = ", ".join(f"'{p}'" for p in ev["river_points"])
    if h.link == "rain->catchment":
        return [
            (
                DEFINITIONS["extreme_rain"].wording,
                f"SELECT point_id, MAX(rain_mm) AS max_mm FROM {s}.hazard_timeline WHERE point_id "
                f"IN ({rain_pts}) AND ts_utc BETWEEN ? AND ? GROUP BY point_id HAVING "
                f"MAX(rain_mm) >= {DEFINITIONS['extreme_rain'].value}",
                clock,
            ),
            (
                "rain lasted more than one hour",
                f"SELECT point_id, COUNT(*) AS hours FROM {s}.hazard_timeline WHERE point_id IN "
                f"({rain_pts}) AND rain_mm > 0 AND ts_utc BETWEEN ? AND ? GROUP BY "
                f"point_id HAVING COUNT(*) >= 2",
                clock,
            ),
            (
                "rain started before the discharge peak",
                f"SELECT MIN(r.ts_utc) AS first_rain, MAX(d.ts_utc) AS peak FROM "
                f"{s}.hazard_timeline r, {s}.hazard_timeline d WHERE r.point_id IN ({rain_pts}) "
                f"AND r.rain_mm > 0 AND d.point_id IN ({river_pts}) AND d.discharge_m3s IS NOT "
                f"NULL AND r.ts_utc BETWEEN ? AND ? AND d.ts_utc BETWEEN ? AND ? "
                f"HAVING MIN(r.ts_utc) < MAX(d.ts_utc)",
                clock + clock,
            ),
        ]
    if h.link == "catchment->river":
        return [
            (
                DEFINITIONS["extreme_discharge_rise"].wording,
                f"SELECT MAX(discharge_m3s) AS mx, MIN(discharge_m3s) AS mn FROM "
                f"{s}.hazard_timeline WHERE point_id IN ({river_pts}) AND discharge_m3s IS NOT "
                f"NULL AND ts_utc BETWEEN ? AND ? HAVING MAX(discharge_m3s) >= 10 * "
                f"MIN(discharge_m3s)",
                clock,
            ),
            (
                "daily discharge confirms the rise",
                f"SELECT MAX(discharge_m3s) AS mx, MIN(discharge_m3s) AS mn FROM "
                f"{s}.discharge_daily WHERE point_id IN ({river_pts}) AND date BETWEEN ? AND ? "
                f"HAVING MAX(discharge_m3s) >= 10 * MIN(discharge_m3s)",
                day,
            ),
            (
                "a warning was issued for the river point",
                f"SELECT point_id, MIN(ts_utc) AS first_utc FROM {s}.hazard_timeline WHERE "
                f"point_id IN ({river_pts}) AND warning_level IS NOT NULL AND ts_utc BETWEEN "
                f"? AND ? GROUP BY point_id",
                clock,
            ),
        ]
    if h.link == "river->site":
        return [
            (
                "the footprint contains insured sites",
                f"SELECT COUNT(*) AS n FROM {s}.exposure_join WHERE {IN_FOOTPRINT_SQL} HAVING "
                f"COUNT(*) >= 1",
                (),
            ),
            (
                "the footprint does not swallow every site (it is a footprint, not a region)",
                f"SELECT COUNT(*) AS n FROM {s}.exposure_join WHERE {OUTSIDE_FOOTPRINT_SQL} HAVING "
                f"COUNT(*) >= 1",
                (),
            ),
            (
                "sites in the footprint carry coordinates",
                f"SELECT COUNT(*) AS n FROM {s}.exposure_join WHERE {IN_FOOTPRINT_SQL} AND lat IS "
                f"NOT NULL AND lon IS NOT NULL HAVING COUNT(*) >= 1",
                (),
            ),
        ]
    return []


def _generic_ok(h: Hypothesis, state: FloodState) -> tuple[bool, str]:
    """Every claim of the hypothesis must cite at least one layer-(a) query that returned rows."""
    if not h.citations:
        return False, "hypothesis has no claims"
    ev = state["evidence"]
    for c in state["claims"]:
        if c["claim_id"] in h.citations:
            qids = [
                x["query_id"] for x in c["citations"] if x["layer"] == "a" and x.get("query_id")
            ]
            if not qids or not any(ev.get(q, {}).get("row_count", 0) > 0 for q in qids):
                return False, f"claim {c['claim_id']} cites no query with rows"
    return True, ""


def make(deps: Deps):
    def skeptic(state: FloodState) -> dict:
        t = time.time()
        hyps = [Hypothesis(**h) for h in state["hypotheses"]]
        new_ev: list[Evidence] = []
        model_id = None
        for h in hyps:
            ok, why = _generic_ok(h, state)
            rounds, qids, notes = 0, [], []
            if ok:
                for name, sql, params in _checks_for(h, state)[: settings.skeptic_max_rounds]:
                    rounds += 1
                    e = deps.zetaris.run_sql(sql, params or None)
                    new_ev.append(e)
                    qids.append(e.query_id)
                    passed = e.row_count >= 1 and not e.error
                    notes.append(f"{'ok' if passed else 'FAILED'}: {name}")
                    if not passed:
                        ok, why = False, f"counter-check failed: {name}"
                        break
            verdict = "supported" if ok else "not_supported"
            rationale = why or "; ".join(notes)
            try:  # optional model rationale from the same rows
                text, model_id = deps.llm.complete(
                    "fast",
                    SKEPTIC,
                    f"HYPOTHESIS {h.id} ({h.link}): {h.statement}\nCOUNTER-CHECKS:\n"
                    f"{rows_block(new_ev[-rounds:] if rounds else [])}\nDETERMINISTIC RESULT: "
                    f"{verdict} ({rationale})",
                )
                js = parse_json(text)
                if js.get("rationale"):
                    rationale = f"{rationale} | model: {str(js['rationale'])[:240]}"
            except Exception as e:
                log.debug("skeptic: model rationale skipped (%s)", str(e)[:100])
            h.status, h.rounds, h.evidence, h.rationale = verdict, rounds, qids, rationale
        n_bad = sum(1 for h in hyps if h.status == "not_supported")
        return {
            "hypotheses": [h.model_dump() for h in hyps],
            "evidence": add_evidence(state, *new_ev),
            "trace": trace(
                state,
                "skeptic",
                f"{len(hyps) - n_bad} supported, {n_bad} not supported after {len(new_ev)} "
                f"counter-check queries",
                lane="sql",
                model_id=model_id,
                started=t,
                evidence_ids=[e.query_id for e in new_ev],
            ),
        }

    return skeptic


def route_after_skeptic(state: FloodState) -> str:
    bad = any(h.get("status") == "not_supported" for h in state["hypotheses"])
    return "revise" if bad and state.get("revise_rounds", 0) < 1 else "exposure"


def bump_revise(state: FloodState) -> dict:
    return {
        "revise_rounds": state.get("revise_rounds", 0) + 1,
        "trace": trace(state, "skeptic", "revise edge -> investigator"),
    }
