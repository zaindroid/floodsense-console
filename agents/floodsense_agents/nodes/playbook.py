"""Playbook. Actions for the next 6 / 24 / 72 hours, citing the claims they rest on.

Outbound actions (anything that contacts a person or an authority) are marked
and wait for the human. The deterministic path writes a standard set from the
exposure; the fast lane, when available, writes richer ones and is validated
against the claim ids. A model action that cites no claim of this run is
dropped: every action has to rest on cited evidence (GAMEPLAN v0.6.0). A repair
round, after the Judge flags a claim, stays on the deep lane.

It also owns the repair round: when the Judge flags a claim, the Playbook
rewrites or shortens it to what its evidence shows. Nothing is deleted.
"""

from __future__ import annotations

import logging
import time

from floodsense_agents.models import Claim, Evidence, PlaybookAction
from floodsense_agents.nightshift import parse_json
from floodsense_agents.nodes.investigator import numbers_in
from floodsense_agents.prompts import PLAYBOOK, REPAIR, rows_block
from floodsense_agents.settings import settings
from floodsense_agents.state import Deps, FloodState, trace

log = logging.getLogger("floodsense.playbook")


def _deterministic(state: FloodState) -> list[PlaybookAction]:
    claims = state["claims"]
    h4 = [c["claim_id"] for c in claims if c.get("hypothesis_id") == "H4"]
    chain = [c["claim_id"] for c in claims if c.get("hypothesis_id") in ("H1", "H2", "H3")][:3]
    if not h4:
        return [
            PlaybookAction(
                action_id="A1",
                horizon_h=24,
                claim_ids=chain,
                text="No insured site is inside the mapped footprint; keep watching the gauges and "
                "the "
                "footprint updates.",
            )
        ]
    return [
        PlaybookAction(
            action_id="A1",
            horizon_h=6,
            outbound=True,
            claim_ids=h4,
            text="Send a safety and claims-readiness message to policyholders at the exposed sites "
            "(largest sum insured first): move stock and vehicles above ground level, document "
            "damage, do not enter flooded basements.",
        ),
        PlaybookAction(
            action_id="A2",
            horizon_h=6,
            claim_ids=h4 + chain,
            text="Open an event file with the exposed policy list and reserve capacity for the sum "
            "insured at risk.",
        ),
        PlaybookAction(
            action_id="A3",
            horizon_h=24,
            outbound=True,
            claim_ids=h4,
            text="Pre-assign loss adjusters to the footprint municipalities and book site access "
            "once "
            "the authority lifts the alert.",
        ),
        PlaybookAction(
            action_id="A4",
            horizon_h=72,
            claim_ids=chain,
            text="Re-run the exposure join when the Copernicus footprint is updated and the gauges "
            "report again; revise reserves.",
        ),
    ]


def make(deps: Deps):
    def playbook(state: FloodState) -> dict:
        t = time.time()
        js_sum = state.get("judge_summary") or {}
        # S6: this used to stop at 1 while the Judge routed back while
        # repair_rounds < JUDGE_REPAIR_ROUNDS. With the knob at 2 the two
        # disagreed and the graph hit its recursion limit. One bound, read
        # from the same setting.
        if js_sum.get("flagged_claim_ids") and (
            state.get("repair_rounds", 0) < settings.judge_repair_rounds
        ):
            return _repair(state, deps, t)
        actions = _deterministic(state)
        model_id = "deterministic"
        lane = "none"
        uncited = 0
        try:
            user = (
                f"CHAIN: {state.get('summary')}\nHYPOTHESES: "
                f"{[(h['id'], h['link'], h['status'], h['statement']) for h in state['hypotheses']]}\n"
                f"CLAIMS:\n"
                + "\n".join(f"{c['claim_id']}: {c['text']}" for c in state["claims"])
                + f"\nEXPOSURE: {state.get('exposure')}"
            )
            text, model_id = deps.llm.complete(
                "fast", PLAYBOOK.replace("{lang}", state["request"].get("lang", "en")), user
            )
            js = parse_json(text)
            ids = {c["claim_id"] for c in state["claims"]}
            drafted = [
                PlaybookAction(
                    action_id=str(a["action_id"]),
                    horizon_h=a["horizon_h"] if a.get("horizon_h") in (6, 24, 72) else 24,
                    text=str(a["text"]),
                    claim_ids=[i for i in a.get("claim_ids", []) if i in ids],
                    outbound=bool(a.get("outbound", False)),
                )
                for a in js.get("actions", [])
            ]
            # An action that cites nothing (or only claim ids this run does not
            # have) rests on no evidence. It is dropped rather than shown.
            got = [a for a in drafted if a.claim_ids]
            uncited = len(drafted) - len(got)
            if got:
                actions, lane = got, "fast"
        except Exception as e:
            log.warning("playbook: model step skipped (%s)", str(e)[:120])
        return {
            "playbook": [a.model_dump() for a in actions],
            "model_ids": [*state.get("model_ids", []), model_id],
            "trace": trace(
                state,
                "playbook",
                f"{len(actions)} actions, {sum(a.outbound for a in actions)} outbound (await "
                f"approval)" + (f"; {uncited} uncited draft(s) dropped" if uncited else ""),
                lane=lane,
                model_id=model_id,
                started=t,
            ),
        }

    return playbook


def _repair(state: FloodState, deps: Deps, t: float) -> dict:
    flagged = set(state["judge_summary"]["flagged_claim_ids"])
    claims = [Claim(**c) for c in state["claims"]]
    ev = {q: Evidence(**e) for q, e in state["evidence"].items()}
    fixed: dict[str, dict] = {}
    model_id = "deterministic"
    try:
        user = (
            "FLAGGED CLAIMS:\n"
            + "\n".join(f"{c.claim_id}: {c.text}" for c in claims if c.claim_id in flagged)
            + "\n\nEVIDENCE THEY CITE:\n"
            + rows_block(
                [
                    ev[x.query_id]
                    for c in claims
                    if c.claim_id in flagged
                    for x in c.citations
                    if x.layer == "a" and x.query_id in ev
                ]
            )
        )
        text, model_id = deps.llm.complete("deep", REPAIR, user)
        for c in parse_json(text).get("claims", []):
            if c.get("claim_id") in flagged and c.get("text"):
                fixed[c["claim_id"]] = c
    except Exception as e:
        log.warning("repair: model step skipped (%s)", str(e)[:120])
    for c in claims:
        if c.claim_id not in flagged:
            continue
        if c.claim_id in fixed:
            c.text = str(fixed[c.claim_id]["text"])
            c.numbers = [float(x) for x in fixed[c.claim_id].get("numbers", [])] or numbers_in(
                c.text
            )
        else:  # deterministic: shorten to the cited evidence, keep it visible
            src = next(
                (ev[x.query_id] for x in c.citations if x.layer == "a" and x.query_id in ev), None
            )
            c.text = (
                f"[repaired] The cited query ({src.view}, {src.row_count} rows) does not support "
                f"the earlier wording; see evidence {src.query_id[:8]}."
                if src
                else "[repaired] This claim cited no evidence with rows and is withdrawn pending data."
            )
            c.numbers = []
    return {
        "claims": [c.model_dump() for c in claims],
        "repair_rounds": state.get("repair_rounds", 0) + 1,
        "trace": trace(
            state,
            "playbook",
            f"repair round 1: {len(flagged)} flagged claim(s) rewritten to their evidence",
            lane="deep" if fixed else "none",
            model_id=model_id,
            started=t,
        ),
    }
