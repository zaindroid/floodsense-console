"""Run lifecycle on top of the compiled graph.

start() runs until the HITL interrupt, snapshot() reads a run, resume()
applies a decision. Used by the service and the eval runner.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.types import Command

from floodsense_agents import labelling
from floodsense_agents.checkpoints import build_checkpointer
from floodsense_agents.events import spec
from floodsense_agents.graph import build_deps, build_graph
from floodsense_agents.hitl import approval_payload
from floodsense_agents.models import ApprovalDecision, RunRequest
from floodsense_agents.nightshift import current_provider
from floodsense_agents.zetaris import now_utc

log = logging.getLogger("floodsense.runtime")
# Short-term thread memory: how much of a conversation a follow-up carries.
THREAD_TURNS_MAX = 3
TURN_SUMMARY_MAX = 600
STATE_KEYS = (
    "run_id",
    "thread_id",
    "event_id",
    "customer_id",
    "replay_ts",
    "anomalies",
    "hypotheses",
    "exposure",
    "playbook",
    "judge",
    "approval",
    "trace",
    "request",
    "event",
    "claims",
    "memories",
    "thread",
    "summary",
    "judge_summary",
    "evidence",
    "provenance",
    "revise_rounds",
    "repair_rounds",
    "scope",
    "model_ids",
    "error",
)


class RunNotFound(KeyError):
    pass


class NotAwaitingApproval(RuntimeError):
    pass


class ThreadNotFound(KeyError):
    pass


def started_at(state: dict[str, Any]) -> str | None:
    """When a run started: its first trace event. Survives a restart, unlike a clock read."""
    trace = state.get("trace") or []
    return trace[0].get("ts") if trace else None


def turn_of(s: dict[str, Any]) -> dict[str, Any]:
    """One earlier turn of a thread, as a follow-up sees it."""
    approval = (s.get("approval") or {}).get("status")
    return {
        "run_id": s.get("run_id"),
        "question": (s.get("request") or {}).get("question"),
        "event_id": s.get("event_id"),
        "status": s.get("status"),
        "approval": approval,
        "summary": (s.get("summary") or "")[:TURN_SUMMARY_MAX],
        "at": started_at(s),
    }


class Runtime:
    def __init__(self, graph=None, deps=None) -> None:
        self.deps = deps if deps is not None else (None if graph is not None else build_deps())
        self.graph = graph if graph is not None else build_graph(self.deps, build_checkpointer())
        self.index: dict[
            str, dict[str, Any]
        ] = {}  # run_id -> row for /runs/past (this process; state lives in the checkpointer)

    @staticmethod
    def cfg(run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}}

    def snapshot(self, run_id: str) -> dict[str, Any]:
        snap = self.graph.get_state(self.cfg(run_id))
        if not snap or not snap.values:
            raise RunNotFound(run_id)
        v = dict(snap.values)
        paused = bool(snap.tasks and any(getattr(t, "interrupts", None) for t in snap.tasks))
        out = {k: v.get(k) for k in STATE_KEYS}
        for k, empty in (
            ("anomalies", []),
            ("hypotheses", []),
            ("playbook", []),
            ("judge", []),
            ("trace", []),
            ("claims", []),
            ("memories", []),
            ("thread", []),
            ("model_ids", []),
            ("evidence", {}),
            ("exposure", {}),
            ("provenance", []),
        ):
            out[k] = out[k] if out[k] is not None else empty
        out["approval"] = out["approval"] or {
            "status": "awaiting" if paused else "not_reached",
            "decision": None,
            "edits": None,
            "reviewer_note": None,
        }
        out["status"] = "awaiting_approval" if paused else v.get("status", "running")
        kind, at = labelling.computation_label(
            v.get("replay_ts"), live=self._answers_are_live()
        )
        # A clocked replay stays replay. A stored "cache" mark must not hide
        # the clock on the way out of the checkpointer.
        stored = v.get("served_from")
        if v.get("replay_ts"):
            pass
        elif stored == labelling.CACHE and v.get("cached_at"):
            kind, at = labelling.CACHE, v.get("cached_at")
        elif stored in labelling.KINDS and stored != labelling.LIVE:
            kind = stored
            at = v.get("cached_at") or at
        out["served_from"] = kind
        out["cached_at"] = at
        # Queries that errored. An answer resting on one of these is standing
        # on a hole, and the reviewer has to be told before deciding.
        out["failures"] = [
            {"query_id": q, "view": e.get("view"), "error": e.get("error")}
            for q, e in (out.get("evidence") or {}).items()
            if e.get("error")
        ]
        return out

    def approval(self, run_id: str) -> dict[str, Any]:
        s = self.snapshot(run_id)
        if s["status"] != "awaiting_approval":
            raise NotAwaitingApproval(f"run {run_id} is {s['status']}")
        return approval_payload(s)

    def citations(self, run_id: str) -> dict[str, Any]:
        s = self.snapshot(run_id)
        cits = [c for claim in s["claims"] for c in claim.get("citations", [])]
        return {
            "run_id": run_id,
            "citations": cits,
            "evidence": s["evidence"],
            "provenance": s["provenance"],
            "served_from": s["served_from"],
            "cached_at": s["cached_at"],
        }

    def _remember(self, run_id: str, snap: dict[str, Any]) -> dict[str, Any]:
        """Record one snapshot in the process index. Does not read the checkpointer."""
        now = now_utc()
        # created_at comes from the run's own trace, so a rebuilt index after a
        # restart keeps the real start time (cached_at labels read it).
        row = self.index.get(run_id, {"run_id": run_id, "created_at": started_at(snap) or now})
        row.update(
            status=snap["status"],
            thread_id=snap.get("thread_id") or run_id,
            question=(snap.get("request") or {}).get("question"),
            event_id=snap.get("event_id"),
            customer_id=snap.get("customer_id"),
            replay_ts=snap.get("replay_ts"),
            updated_at=now,
            judge_overall=(snap.get("judge_summary") or {}).get("overall"),
            approval=(snap.get("approval") or {}).get("status"),
            served_from=snap["served_from"],
            cached_at=snap["cached_at"],
        )
        self.index[run_id] = row
        return row

    def _index_row(self, run_id: str) -> None:
        self._remember(run_id, self.snapshot(run_id))

    def _answers_are_live(self) -> bool:
        """True only for the live schema read through live Zetaris."""
        zetaris = getattr(self.deps, "zetaris", None) if self.deps else None
        return labelling.data_plane_is_live(zetaris)

    def thread(self, thread_id: str) -> list[dict[str, Any]]:
        """The last THREAD_TURNS_MAX turns of a conversation, oldest first.

        A thread is the runs that share a thread_id; the first run's id names
        it. An unknown thread is an error rather than a silent new thread, so
        a client continuing a conversation hears when it is not.
        """
        self._rebuild_index()
        rows = [r for r in self.index.values() if r.get("thread_id") == thread_id]
        if not rows:
            raise ThreadNotFound(thread_id)
        rows.sort(key=lambda r: r.get("created_at") or "")
        return [turn_of(self.snapshot(r["run_id"])) for r in rows[-THREAD_TURNS_MAX:]]

    def start(self, req: RunRequest) -> dict[str, Any]:
        run_id = uuid.uuid4().hex[:12]
        ev = spec(req.event_id)
        thread_id = req.thread_id or run_id
        turns = self.thread(req.thread_id) if req.thread_id else []
        served_from, cached_at = labelling.computation_label(
            req.replay_ts, live=self._answers_are_live()
        )
        token = current_provider.set(req.llm_provider)
        try:
            self.graph.invoke(
                {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "thread": turns,
                    "event_id": ev.event_id,
                    "customer_id": req.customer_id,
                    "replay_ts": req.replay_ts,
                    "request": req.model_dump(),
                    "event": ev.as_dict(),
                    "served_from": served_from,
                    "cached_at": cached_at,
                    "trace": [],
                    "revise_rounds": 0,
                    "repair_rounds": 0,
                    "model_ids": [],
                },
                self.cfg(run_id),
            )
        except Exception as e:
            log.exception("run %s failed", run_id)
            self.graph.update_state(self.cfg(run_id), {"status": "failed", "error": str(e)[:500]})
        finally:
            current_provider.reset(token)
        self._index_row(run_id)
        return self.snapshot(run_id)

    def resume(self, run_id: str, decision: ApprovalDecision) -> dict[str, Any]:
        s = self.snapshot(run_id)
        if s["status"] != "awaiting_approval":
            raise NotAwaitingApproval(f"run {run_id} is {s['status']}, not awaiting approval")
        provider = (s.get("request") or {}).get("llm_provider") or "nightshift"
        token = current_provider.set(provider)
        try:
            self.graph.invoke(Command(resume=decision.model_dump()), self.cfg(run_id))
        finally:
            current_provider.reset(token)
        out = self.snapshot(run_id)
        # N1: store used to run here on every approval, FF_HMEM or not. It now
        # runs in the graph's Learn node (nodes/memory.py), behind FF_HMEM, so
        # the write shows on the trace and a resumed graph stores exactly once.
        self._index_row(run_id)
        return out

    def _rebuild_index(self) -> bool:
        """Re-read the checkpointer so a restart does not lose the run list.

        S10: the index is process memory while the state is not. After a
        restart a run stayed reachable by id and vanished from /runs/past.
        Returns False when the checkpointer cannot be listed, so the caller
        can say the list is this process only rather than imply it is whole.
        """
        saver = getattr(self.graph, "checkpointer", None)
        if saver is None or not hasattr(saver, "list"):
            return False
        try:
            # Copy the ids out first. SqliteSaver.list holds its lock until
            # this generator is closed, and _index_row reads the same saver.
            pending: list[str] = []
            seen = set()
            for item in saver.list(None):
                thread = (getattr(item, "config", None) or {}).get("configurable", {})
                run_id = thread.get("thread_id")
                if not run_id or run_id in seen or run_id in self.index:
                    continue
                seen.add(run_id)
                pending.append(run_id)
            for run_id in pending:
                try:
                    self._index_row(run_id)
                except Exception:  # noqa: BLE001 - a partial checkpoint is not fatal
                    continue
            return True
        except Exception as e:  # noqa: BLE001 - listing is best effort
            log.warning("could not read past runs from the checkpointer: %s", str(e)[:120])
            return False

    def past(self, limit: int = 50, thread_id: str | None = None) -> list[dict[str, Any]]:
        whole = self._rebuild_index()
        rows = [r for r in self.index.values() if not thread_id or r.get("thread_id") == thread_id]
        rows = sorted(rows, key=lambda r: r["updated_at"], reverse=True)[:limit]
        for r in rows:
            r["scope"] = "all runs on this checkpointer" if whole else "this process only"
        return rows
