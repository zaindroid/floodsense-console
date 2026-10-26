"""Graph state and the dependency bundle the nodes close over.

Plain dicts cross node boundaries so the checkpointer can serialise them;
the pydantic models in models.py type them at the edges.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict

from floodsense_agents.engines import NoWorld, WorldModel
from floodsense_agents.models import Evidence, TraceEvent
from floodsense_agents.nightshift import LLM
from floodsense_agents.zetaris import Zetaris, now_utc


class Memory(Protocol):
    """Memory behind FF_HMEM. recall() feeds the Investigator; store() runs on approval only."""

    def recall(self, request: dict[str, Any]) -> list[dict[str, Any]]: ...
    def store(
        self,
        run_id: str,
        request: dict[str, Any],
        claims: list[dict[str, Any]],
        approval: dict[str, Any],
    ) -> None: ...


class NoMemory:
    """No memory plugged in. The graph treats plain NoMemory as memory off."""

    def recall(self, request):
        return []

    def store(self, run_id, request, claims, approval):
        return None


@dataclass
class Deps:
    zetaris: Zetaris
    llm: LLM
    memory: Memory
    world: WorldModel = field(default_factory=NoWorld)  # engines sidecar; NoWorld = off
    retrieve_docs: Callable[..., Any] | None = None


class FloodState(TypedDict, total=False):
    # contract fields
    run_id: str
    thread_id: str
    event_id: str
    customer_id: str
    replay_ts: str | None
    anomalies: list[dict[str, Any]]  # Anomaly[]
    hypotheses: list[dict[str, Any]]  # Hypothesis[]
    exposure: dict[str, Any]  # Exposure
    playbook: list[dict[str, Any]]  # PlaybookAction[]
    judge: list[dict[str, Any]]  # JudgeScore[]
    approval: dict[str, Any]  # Approval
    trace: list[dict[str, Any]]  # TraceEvent[]
    # extra
    request: dict[str, Any]  # RunRequest
    event: dict[str, Any]  # EventSpec
    evidence: dict[str, dict[str, Any]]  # query_id -> Evidence
    provenance: list[dict[str, Any]]  # rows of the provenance view (layer b)
    claims: list[dict[str, Any]]  # Claim[]
    memories: list[dict[str, Any]]  # H-MEM recall for this run: context, never evidence
    thread: list[dict[str, Any]]  # earlier turns of this conversation: short-term memory
    summary: str
    judge_summary: dict[str, Any]  # JudgeSummary
    revise_rounds: int
    repair_rounds: int
    scope: dict[str, Any]  # the gate's verdict: can this run honestly answer
    status: str  # running | awaiting_approval | approved | rejected | failed
    served_from: str  # live | cache | replay. live only for a fresh live-schema read
    cached_at: str | None
    model_ids: list[str]
    error: str


def trace(
    state: FloodState,
    node: str,
    summary: str,
    *,
    lane: str | None = None,
    model_id: str | None = None,
    started: float | None = None,
    evidence_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    prev = state.get("trace", [])
    ev = TraceEvent(
        run_id=state.get("run_id", ""),
        seq=len(prev) + 1,
        ts=now_utc(),
        node=node,
        lane=lane,
        model_id=model_id,
        latency_ms=int((time.time() - started) * 1000) if started else None,
        summary=summary,
        evidence_ids=evidence_ids or [],
    )
    return [*prev, ev.model_dump()]


def answered(*items: Evidence) -> bool:
    """True when every query came back. An errored query answered nothing.

    Empty rows and a failed call look identical downstream unless someone
    asks. Nodes ask here before stating anything.
    """
    return all(e.error is None for e in items)


def failures(state: FloodState) -> list[str]:
    """Query ids in this run that errored. Empty is the healthy case."""
    return sorted(q for q, e in (state.get("evidence") or {}).items() if e.get("error"))


def add_evidence(state: FloodState, *items: Evidence) -> dict[str, dict[str, Any]]:
    ev = dict(state.get("evidence", {}))
    for e in items:
        ev[e.query_id] = e.model_dump()
    return ev
