"""Investigator. Builds the cited causal chain rain -> catchment -> river -> site.

One hypothesis per link, backed by claims. Every claim carries a layer (a)
citation (the Zetaris query_id) and, where the provenance view knows the
dataset, layer (b) citations.

The deterministic path builds the chain from aggregate queries, so the graph
runs without a model. Those queries do not depend on each other, so they run
together. The fast lane, when available, writes the claims and summary from
the same evidence; unknown query_ids are dropped. Repair stays on the deep
lane, in the Playbook.
"""

from __future__ import annotations

import logging
import re
import time

from floodsense_agents.events import point_label
from floodsense_agents.governance import IN_FOOTPRINT_SQL
from floodsense_agents.models import Citation, Claim, Evidence, Hypothesis, Locator
from floodsense_agents.nightshift import parse_json
from floodsense_agents.nodes.watchers import last_complete_day, window
from floodsense_agents.prompts import INVESTIGATOR, rows_block
from floodsense_agents.settings import settings
from floodsense_agents.state import Deps, FloodState, add_evidence, trace
from floodsense_agents.zetaris import now_utc, run_sql_parallel

log = logging.getLogger("floodsense.investigator")
# 21,600,000 is one number, not 21.6 and 0, and the 3 in "m3/s" is not a
# number at all. The Judge checks whatever comes out of here against the
# cited rows, so a bad split becomes a false mismatch.
_NUM = re.compile(
    r"(?<![A-Za-z\d.,])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # grouped thousands
    r"|(?<![A-Za-z\d.,])-?\d+(?:\.\d+)?"  # plain, including decimals
)
LINKS = ("rain->catchment", "catchment->river", "river->site", "site->exposure")
MEMORY_PROMPT_MAX = 5  # recalled findings shown to the model


def numbers_in(text: str) -> list[float]:
    out = []
    for n in _NUM.findall(
        re.sub(r"\d{4}-\d{2}-\d{2}T?[\d:]*Z?", " ", text)
    ):  # timestamps are not numbers to check
        try:
            out.append(float(n.replace(",", "")))
        except ValueError:
            pass
    return out


def cite(claim_id: str, ev: Evidence, provenance: list[dict], n: int) -> list[Citation]:
    cits = [
        Citation(
            citation_id=f"{claim_id}-a{n}",
            claim_id=claim_id,
            layer="a",
            query_id=ev.query_id,
            title=ev.view,
            accessed_at=ev.executed_at_utc,
        )
    ]
    dataset = ev.view.split(".")[-1]
    for k, p in enumerate(x for x in provenance if x.get("dataset") == dataset):
        cits.append(
            Citation(
                citation_id=f"{claim_id}-b{n}.{k + 1}",
                claim_id=claim_id,
                layer="b",
                source_url=p.get("source_url"),
                title=dataset,
                publisher=p.get("publisher"),
                licence=p.get("licence"),
                attribution=p.get("attribution"),
                accessed_at=p.get("fetched_at"),
                storage="pointer",
            )
        )
    return cits


def memory_block(memories: list[dict] | None) -> str:
    """Past approved findings from H-MEM, for the prompt. Never cited: their query ids
    belong to earlier runs, and only this run's evidence can back a claim."""
    if not memories:
        return ""
    lines = [
        f"- {m.get('content', '')} (run {m.get('run_id', '?')}, relevance "
        f"{float(m.get('relevance') or 0):.2f})"
        for m in memories[:MEMORY_PROMPT_MAX]
    ]
    return (
        "PAST APPROVED FINDINGS (H-MEM; context only, not evidence; do not cite):\n"
        + "\n".join(lines)
        + "\n"
    )


def thread_block(turns: list[dict] | None) -> str:
    """Earlier turns of this conversation, for the prompt. Context, not evidence: a
    follow-up re-derives every claim from this run's queries."""
    if not turns:
        return ""
    lines = []
    for turn in turns:
        lines.append(
            f"- Q: {turn.get('question', '')} [{turn.get('approval') or turn.get('status')}] "
            f"A: {turn.get('summary') or '(no summary yet)'}"
        )
    return (
        "EARLIER IN THIS THREAD (short-term memory; context only, not evidence; do not cite):\n"
        + "\n".join(lines)
        + "\n"
    )


def _fmt(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _deterministic(
    state: FloodState, deps: Deps
) -> tuple[list[Hypothesis], list[Claim], str, list[Evidence]]:
    s, ev, prov = settings.schema, state["event"], state.get("provenance", [])
    t0, t1 = window(state)
    rain_pts = ", ".join(f"'{p}'" for p in ev["rain_points"])
    river_pts = ", ".join(f"'{p}'" for p in ev["river_points"])
    # Rain, discharge, the daily series, the footprint count, and warnings do
    # not depend on each other. Order of the tuple is the evidence order.
    rain, flow, daily, foot, warn = run_sql_parallel(
        deps.zetaris,
        [
            (
                f"SELECT point_id, SUM(rain_mm) AS total_mm, MAX(rain_mm) AS max_hourly_mm, "
                f"MIN(ts_utc) AS first_utc, MAX(ts_utc) AS last_utc, "
                f"COUNT(*) AS hours FROM {s}.hazard_timeline WHERE point_id IN ({rain_pts}) AND "
                f"rain_mm IS NOT NULL "
                f"AND ts_utc BETWEEN ? AND ? GROUP BY point_id ORDER BY total_mm DESC",
                (t0, t1),
            ),
            (
                f"SELECT point_id, ts_utc, discharge_m3s FROM {s}.hazard_timeline WHERE point_id IN "
                f"({river_pts}) "
                f"AND ts_utc BETWEEN ? AND ? ORDER BY ts_utc",
                (t0, t1),
            ),
            (
                f"SELECT point_id, date, discharge_m3s, source FROM {s}.discharge_daily WHERE "
                f"point_id IN ({river_pts}) "
                f"AND date BETWEEN ? AND ? ORDER BY date",
                (t0[:10], last_complete_day(t1)),
            ),
            (
                f"SELECT COUNT(*) AS sites_in_footprint, COUNT(DISTINCT segment) AS segments FROM "
                f"{s}.exposure_join WHERE {IN_FOOTPRINT_SQL}",
                None,
            ),
            (
                f"SELECT point_id, warning_level, MIN(ts_utc) AS first_utc FROM {s}.hazard_timeline "
                f"WHERE warning_level IS NOT NULL "
                f"AND ts_utc BETWEEN ? AND ? GROUP BY point_id, warning_level ORDER BY first_utc",
                (t0, t1),
            ),
        ],
    )

    claims: list[Claim] = []
    hyps: list[Hypothesis] = []
    n = 0

    def claim(text, kind, evs, hid, numbers):
        nonlocal n
        n += 1
        cid = f"C{n}"
        claims.append(
            Claim(
                claim_id=cid,
                text=text,
                kind=kind,
                numbers=numbers,
                hypothesis_id=hid,
                citations=[c for i, e in enumerate(evs, 1) for c in cite(cid, e, prov, i)],
            )
        )
        return cid

    # H1 rain -> catchment
    h1 = []
    for r in rain.rows_sample[:2]:
        h1.append(
            claim(
                f"Point {point_label(r['point_id'])} recorded {_fmt(r['total_mm'])} mm of rain over "
                f"{r['hours']} hours between {r['first_utc']} and {r['last_utc']}, "
                f"peak hour {_fmt(r['max_hourly_mm'])} mm.",
                "number",
                [rain],
                "H1",
                [r["total_mm"], r["hours"], r["max_hourly_mm"]],
            )
        )
    for w in warn.rows_sample[:1]:
        h1.append(
            claim(
                f"Warning level '{w['warning_level']}' was in force for point {point_label(w['point_id'])} from "
                f"{w['first_utc']}.",
                "fact",
                [warn],
                "H1",
                [],
            )
        )
    hyps.append(
        Hypothesis(
            id="H1",
            link="rain->catchment",
            citations=h1,
            statement=f"Extreme rainfall fell over the {ev['catchment']}"
            if h1
            else "No rainfall signal in the window",
        )
    )

    # H2 catchment -> river
    h2 = []
    flows = [r for r in flow.rows_sample if r.get("discharge_m3s") is not None]
    if flows:
        p = max(flows, key=lambda r: r["discharge_m3s"])
        base = flows[0]
        h2.append(
            claim(
                f"Discharge at {point_label(p['point_id'])} reached {_fmt(p['discharge_m3s'])} m3/s at "
                f"{p['ts_utc']}, from {_fmt(base['discharge_m3s'])} m3/s at {base['ts_utc']}.",
                "number",
                [flow],
                "H2",
                [p["discharge_m3s"], base["discharge_m3s"]],
            )
        )
        gaps = [r for r in flow.rows_sample if r.get("discharge_m3s") is None]
        if gaps and gaps[0]["ts_utc"] > p["ts_utc"]:
            h2.append(
                claim(
                    f"The {point_label(p['point_id'])} series has no discharge value from {gaps[0]['ts_utc']} "
                    f"on (gauge outage during the peak).",
                    "fact",
                    [flow],
                    "H2",
                    [],
                )
            )
    if len(daily.rows_sample) >= 2:
        d = max(daily.rows_sample, key=lambda r: r["discharge_m3s"])
        before = daily.rows_sample[0]
        h2.append(
            claim(
                f"Daily discharge for {point_label(d['point_id'])} ({d['source']}) was "
                f"{_fmt(d['discharge_m3s'])} m3/s on {d['date']}, up from "
                f"{_fmt(before['discharge_m3s'])} m3/s on {before['date']}.",
                "number",
                [daily],
                "H2",
                [d["discharge_m3s"], before["discharge_m3s"]],
            )
        )
    if rain.rows_sample and flows:
        first_rain = rain.rows_sample[0]["first_utc"]
        peak_ts = max(flows, key=lambda r: r["discharge_m3s"])["ts_utc"]
        if first_rain < peak_ts:
            h2.append(
                claim(
                    f"Rain began at {first_rain} and the discharge peak followed at {peak_ts}, "
                    f"consistent with catchment runoff driving the river response.",
                    "cause",
                    [rain, flow],
                    "H2",
                    [],
                )
            )
    hyps.append(
        Hypothesis(
            id="H2",
            link="catchment->river",
            citations=h2,
            statement=f"Runoff produced an extreme discharge in the {ev['river']}"
            if h2
            else "No river response recorded",
        )
    )

    # H3 river -> site
    h3 = []
    if foot.rows_sample and foot.rows_sample[0]["sites_in_footprint"]:
        f = foot.rows_sample[0]
        h3.append(
            claim(
                f"The Copernicus EMS footprint ({ev['event_id']}) covers {f['sites_in_footprint']} "
                f"insured sites across {f['segments']} segments.",
                "number",
                [foot],
                "H3",
                [f["sites_in_footprint"], f["segments"]],
            )
        )
    hyps.append(
        Hypothesis(
            id="H3",
            link="river->site",
            citations=h3,
            statement="The overflow reached built-up areas mapped by Copernicus EMS"
            if h3
            else "No mapped footprint touches an insured site",
        )
    )

    summary = " ".join(
        f"{h.statement} [{', '.join(h.citations)}]." if h.citations else f"{h.statement}."
        for h in hyps
    )
    return hyps, claims, summary, [rain, flow, daily, foot, warn]


def _model(
    state: FloodState, deps: Deps, extra: list[Evidence]
) -> tuple[list[Hypothesis], list[Claim], str, str] | None:
    evidence = [Evidence(**e) for e in state["evidence"].values()] + extra
    user = (
        f"EVENT: {state['event']['name']} ({state['event_id']}); river "
        f"{state['event']['river']}\nQUESTION: {state['request']['question']}\n"
        f"ANOMALIES: {state.get('anomalies')}\n{thread_block(state.get('thread'))}"
        f"{memory_block(state.get('memories'))}"
        f"\nEVIDENCE:\n{rows_block(evidence)}"
    )
    text, model_id = deps.llm.complete(
        "fast", INVESTIGATOR.replace("{lang}", state["request"].get("lang", "en")), user
    )
    js = parse_json(text)
    if not js.get("claims"):
        return None
    known = {e.query_id: e for e in evidence}
    prov = state.get("provenance", [])
    claims = []
    for c in js["claims"]:
        evs = [known[q] for q in c.get("query_ids", []) if q in known]
        cid = str(c["claim_id"])
        claims.append(
            Claim(
                claim_id=cid,
                text=str(c["text"]),
                kind=c.get("kind") if c.get("kind") in ("fact", "number", "cause") else "fact",
                numbers=[float(x) for x in c.get("numbers", []) if isinstance(x, (int, float))]
                or numbers_in(str(c["text"])),
                citations=[x for i, e in enumerate(evs, 1) for x in cite(cid, e, prov, i)],
                hypothesis_id=c.get("hypothesis_id"),
            )
        )
    ids = {c.claim_id for c in claims}
    hyps = [
        Hypothesis(
            id=str(h["id"]),
            link=h["link"],
            statement=str(h["statement"]),
            citations=[i for i in h.get("claim_ids", []) if i in ids],
        )
        for h in js.get("hypotheses", [])
        if h.get("link") in LINKS
    ]
    return hyps, claims, str(js.get("summary", "")), model_id


_DOC_SQL = (
    "SELECT chunk_id, text, text_sha256, title, source_url, publisher, licence, "
    "attribution, page, paragraph, lines, section FROM PGVECTOR_RAG.chunks"
)


def _text(raw: dict, key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) else None


def _doc_locator(raw: dict) -> Locator | None:
    locator = raw.get("locator")
    if not isinstance(locator, dict):
        return None
    page = locator.get("page")
    paragraph = locator.get("paragraph")
    lines = locator.get("lines")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        return None
    if isinstance(paragraph, bool) or not isinstance(paragraph, int) or paragraph < 1:
        return None
    if not isinstance(lines, str) or not lines:
        return None
    section = locator.get("section")
    return Locator(
        page=page,
        paragraph=paragraph,
        lines=lines,
        section=section if isinstance(section, str) and section else None,
    )


def _attach_documents(claims, raws, request, query):
    """Append layer (c) citations to the named claim, or to a new fact claim C-doc."""
    target_id = request.get("doc_claim_id")
    target = next(
        (item for item in claims if isinstance(target_id, str) and item.claim_id == target_id),
        None,
    )
    if target is None:
        target = Claim(claim_id="C-doc", text=query, kind="fact")
        claims = [*claims, target]
    start = 1 + sum(1 for item in target.citations if item.layer == "c")
    rows_for_q: dict[str, list[dict]] = {}
    for offset, raw in enumerate(raws, start=start):
        qid = raw.get("query_id") if isinstance(raw.get("query_id"), str) else None
        chunk_id = raw.get("chunk_id") if isinstance(raw.get("chunk_id"), str) else None
        target.citations.append(
            Citation(
                citation_id=f"{target.claim_id}-c{offset}",
                claim_id=target.claim_id,
                layer="c",
                source_url=_text(raw, "source_url"),
                title=_text(raw, "title"),
                publisher=_text(raw, "publisher"),
                licence=_text(raw, "licence"),
                attribution=_text(raw, "attribution"),
                locator=_doc_locator(raw),
                quote=_text(raw, "quote"),
                content_sha256=_text(raw, "content_sha256"),
                storage="full_text",
                query_id=qid,
                chunk_id=chunk_id if chunk_id and len(chunk_id) <= 128 else None,
                accessed_at=now_utc(),
            )
        )
        text = raw.get("text")
        digest = raw.get("text_sha256")
        if qid and isinstance(text, str) and isinstance(digest, str):
            sample = {"text": text, "text_sha256": digest}
            if chunk_id and len(chunk_id) <= 128:
                sample["chunk_id"] = chunk_id
            rows_for_q.setdefault(qid, []).append(sample)
    evidence = [
        Evidence(
            query_id=qid,
            view="PGVECTOR_RAG.chunks",
            sql=_DOC_SQL,
            rows_sample=rows[:20],
            row_count=len(rows),
            executed_at_utc=now_utc(),
        )
        for qid, rows in rows_for_q.items()
    ]
    return claims, evidence


def make(deps: Deps):
    def investigator(state: FloodState) -> dict:
        t = time.time()
        if (
            state.get("hypotheses") and state.get("revise_rounds", 0) > 0
        ):  # revise edge: drop what the Skeptic broke
            bad = {h["id"] for h in state["hypotheses"] if h.get("status") == "not_supported"}
            hyps = [h for h in state["hypotheses"] if h["id"] not in bad]
            claims = [c for c in state["claims"] if c.get("hypothesis_id") not in bad]
            kept = " ".join(
                f"{h['statement']} [{', '.join(h['citations'])}]." for h in hyps if h["citations"]
            )
            # Nothing left is a result, not a missing value. Repeating the summary the
            # first pass wrote would state a case the Skeptic has just broken, and an
            # empty one loses the run: the desk refuses a recorded run with no summary
            # and shows its fixture instead, reporting nothing.
            summary = kept or "No hypothesis survived the Skeptic's counter-checks."
            return {
                "hypotheses": hyps,
                "claims": claims,
                "summary": summary,
                "trace": trace(
                    state,
                    "investigator",
                    f"revised chain: removed {len(bad)} hypothesis/es the Skeptic did not support "
                    f"({', '.join(sorted(bad)) or '-'})",
                    started=t,
                ),
            }

        hyps, claims, summary, extra = _deterministic(state, deps)
        model_id = "deterministic"
        lane = "sql"
        try:
            got = _model(state, deps, extra)
            if got:
                m_hyps, m_claims, m_summary, model_id = got
                if m_hyps and m_claims:
                    hyps, claims, summary, lane = m_hyps, m_claims, m_summary or summary, "fast"
        except Exception as e:  # the deterministic chain is complete; the model only refines it
            log.warning("investigator: model step skipped (%s)", str(e)[:140])
        doc_note = ""
        if deps.retrieve_docs is not None:
            request = state.get("request") or {}
            doc_query = request.get("doc_query")
            if isinstance(doc_query, str) and doc_query.strip():
                try:
                    result = deps.retrieve_docs(
                        doc_query,
                        request.get("doc_k", 4),
                        {"event_id": state.get("event_id")},
                    )
                except Exception as exc:
                    doc_note = f" retrieve_docs error: {str(exc)[:200]}"
                else:
                    if result.error:
                        doc_note = f" retrieve_docs error: {result.error}"
                    elif result.citations:
                        claims, doc_evidence = _attach_documents(
                            claims, result.citations, request, doc_query
                        )
                        extra = [*extra, *doc_evidence]
        return {
            "hypotheses": [h.model_dump() for h in hyps],
            "claims": [c.model_dump() for c in claims],
            "summary": summary,
            "evidence": add_evidence(state, *extra),
            "revise_rounds": state.get("revise_rounds", 0),
            "model_ids": [*state.get("model_ids", []), model_id],
            "trace": trace(
                state,
                "investigator",
                f"{len(hyps)} hypotheses, {len(claims)} cited claims{doc_note}",
                lane=lane,
                model_id=model_id,
                started=t,
                evidence_ids=[e.query_id for e in extra],
            ),
        }

    return investigator
