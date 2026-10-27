"""Human-in-the-loop approval gate.

The ``hitl`` node pauses the run with LangGraph ``interrupt()``. The
checkpointer persists the whole state, so the pause survives a restart.
``POST /runs/{id}/approval`` resumes it with an ApprovalDecision: approve,
edit (the reviewer's text replaces the summary), or reject.

No outbound action is released without a decision: PlaybookAction.released
stays False until approve or edit. FF_HITL=false auto-approves and records
``approval.status = "auto"`` for local development.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from floodsense_agents.models import Approval, ApprovalDecision
from floodsense_agents.settings import settings
from floodsense_agents.state import FloodState, run_model_ids, trace
from floodsense_agents.zetaris import now_utc


def approval_payload(state: FloodState) -> dict[str, Any]:
    """What the reviewer sees while the graph is paused (also served by GET /runs/{id}/approval)."""
    return {
        "run_id": state["run_id"],
        "thread_id": state.get("thread_id", state["run_id"]),
        "event_id": state.get("event_id"),
        "customer_id": state.get("customer_id"),
        "replay_ts": state.get("replay_ts"),
        "request": state.get("request"),
        "summary": state.get("summary", ""),
        "anomalies": state.get("anomalies", []),
        "hypotheses": state.get("hypotheses", []),
        "claims": state.get("claims", []),
        # What H-MEM recalled for the Investigator. Context, not evidence.
        "memories": state.get("memories", []),
        # Earlier turns this follow-up builds on (short-term thread memory).
        "thread": state.get("thread", []),
        "exposure": state.get("exposure", {}),
        "playbook": state.get("playbook", []),
        "judge": state.get("judge", []),
        "judge_summary": state.get("judge_summary"),
        "flagged_claim_ids": (state.get("judge_summary") or {}).get("flagged_claim_ids", []),
        # Queries that failed. The reviewer decides knowing what is missing.
        "failures": state.get("failures", []),
        "served_from": state.get("served_from"),
        "cached_at": state.get("cached_at"),
        "model_ids": run_model_ids(state.get("trace"), state.get("model_ids")),
    }


def hitl(state: FloodState) -> dict:
    if not settings.ff_hitl:
        decision = ApprovalDecision(
            action="approve",
            reviewer="auto (FF_HITL=off)",
            reviewer_note="auto-approved: FF_HITL is off",
        )
        auto = True
    else:
        raw = interrupt(approval_payload(state))  # pauses here; resumes with the decision
        decision = (
            ApprovalDecision(**raw) if isinstance(raw, dict) else ApprovalDecision(action=str(raw))
        )
        auto = False
    outbound = [a["action_id"] for a in state.get("playbook", []) if a.get("outbound")]
    if decision.action == "reject":
        approval = Approval(
            status="rejected",
            decision="reject",
            reviewer_note=decision.reviewer_note,
            reviewer=decision.reviewer,
            decided_at_utc=now_utc(),
        )
        return {
            "approval": approval.model_dump(),
            "status": "rejected",
            "trace": trace(
                state,
                "hitl",
                f"REJECTED by {decision.reviewer or 'reviewer'}: nothing released "
                f"({decision.reviewer_note or 'no note'})",
            ),
        }
    # N2: an edit with no text used to fall through to "approved". The API
    # rejects it at 422, but a graph resumed directly reached here.
    if decision.action == "edit" and not (decision.edits or "").strip():
        raise ValueError("an edit needs replacement text; send reject to hold instead")
    edited = decision.action == "edit"
    approval = Approval(
        status="auto" if auto else ("edited" if edited else "approved"),
        decision=decision.action,
        edits=decision.edits if edited else None,
        reviewer_note=decision.reviewer_note,
        reviewer=decision.reviewer,
        decided_at_utc=now_utc(),
    )
    return {
        "approval": approval.model_dump(),
        "summary": decision.edits.strip() if edited else state.get("summary", ""),
        "playbook": [{**a, "released": True} for a in state.get("playbook", [])],
        "status": "approved",
        "trace": trace(
            state,
            "hitl",
            f"{approval.status.upper()} by {decision.reviewer or 'reviewer'}; {len(outbound)} "
            f"outbound action(s) released: {', '.join(outbound) or '-'}",
        ),
    }


def approval_status(state: dict[str, Any]) -> dict[str, Any]:
    """Approval record of a run state (kept from the skeleton's import surface)."""
    a = state.get("approval") or {}
    return {
        "node": "hitl",
        "status": state.get("status", "running"),
        "decision": a.get("decision"),
        "approval": a,
        "thread_id": state.get("thread_id") or state.get("run_id"),
    }
