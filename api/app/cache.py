"""Semantic cache and labelled replay, in front of the proxy.

GAMEPLAN "Caching and the honest demo". Both are off unless their flag is on.

Cache (FF_SEMANTIC_CACHE). A run is cached when it finished well: the analyst
approved or edited it and the Judge passed it. The key is the question
(case, spacing and punctuation folded) plus the event, the customer, the
replay clock, the language and the agents' flags, lanes and schema, so a
change of flags is a miss. The replay clock is normalised to
YYYY-MM-DDTHH:MM:SSZ on lookup and on remember, the same rule as the agents'
RunRequest, so a zone-less or short form of that instant hits. A repeat of
that question is answered with the original run, labelled as cache ("Cached
answer from HH:MM · not live · original run R"), including when the stored
run was a clocked replay. The historical clock stays: replay_ts and cached_at
are that UTC instant, never "now", and the answer is not called live. Live
data expires sooner than a historical replay. A follow-up in a thread is
never cached or served from the cache, because it depends on its conversation.
"Similar" means the same after folding for now; embedding similarity needs
the embed lane.

Replay (FF_CACHED_REPLAY). When a live run fails (the agents answer 5xx, are
unreachable, or return a failed run), the API serves the newest recorded run
for the same question, event, customer, replay clock and language that a
person approved or edited. An event alias (valencia_2024) matches the
canonical id (EMSR773). A different question is not served. The replay block
names the original question and clock, so a console cannot show one question's
answer as another's. Follow-ups (a request that carries thread_id) are not
replayed. Lookups use CACHE_LOOKUP_TIMEOUT_S, not the long run timeout, and
an unreachable agents service is answered from the recording kept here.

The cache lives in this process. REDIS_URL is not read yet; a restart empties
the cache but not the recordings in the agents' checkpointer.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# Mirrors RunRequest's defaults in agents/floodsense_agents/models.py, so a
# request that leaves them out keys the same as one that spells them out.
DEFAULT_EVENT = "EMSR773"
DEFAULT_CUSTOMER = "demo-insurer"
DEFAULT_LANG = "en"
REMEMBERED = ("approved", "edited")
FLAGS_MEMO_S = 30.0

# Same aliases as agents/floodsense_agents/events.py. The agents store the
# canonical id on the run; a client may still post the alias.
_EVENT_ALIASES = {"valencia_2024": "EMSR773", "ahr_2021": "EMSR517"}

# A replay clock is a UTC instant. Callers compare it, so it is normalised to
# YYYY-MM-DDTHH:MM:SSZ. This is the agents' normalize_utc; an unparseable
# value is kept as text so a lookup does not fail the request.
_UTC_LOOSE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?Z?$")
_UTC_CANON = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v in (None, "") else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class CacheSettings:
    semantic_cache: bool = field(default_factory=lambda: _flag("FF_SEMANTIC_CACHE", False))
    cached_replay: bool = field(default_factory=lambda: _flag("FF_CACHED_REPLAY", False))
    ttl_live_s: float = field(
        default_factory=lambda: float(os.environ.get("CACHE_TTL_LIVE_S") or 900)
    )
    ttl_replay_s: float = field(
        default_factory=lambda: float(os.environ.get("CACHE_TTL_REPLAY_S") or 86400)
    )
    max_entries: int = field(
        default_factory=lambda: int(os.environ.get("CACHE_MAX_ENTRIES") or 256)
    )
    max_recordings: int = field(
        default_factory=lambda: int(os.environ.get("REPLAY_MAX_RECORDINGS") or 8)
    )
    # Cache and replay lookups. Not the 600s budget a live run is allowed.
    lookup_timeout_s: float = field(
        default_factory=lambda: float(os.environ.get("CACHE_LOOKUP_TIMEOUT_S") or 3)
    )


def fold(question: str) -> str:
    """The question as the cache compares it: casefolded, punctuation and spacing folded."""
    return " ".join(re.sub(r"[^\w\s]", " ", (question or "").casefold()).split())


def normalize_utc(value: Any) -> str | None:
    """Canonical UTC instant, or None when there is no clock.

    Zone-less and short forms (2024-10-29T16:00Z, 2024-10-29 16:00:00) become
    YYYY-MM-DDTHH:MM:SSZ. Anything else is returned unchanged so two identical
    raw values still share a key.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _UTC_LOOSE.fullmatch(text)
    if not match:
        return text
    date, hour, minute, second = match.groups()
    return f"{date}T{hour}:{minute}:{second or '00'}Z"


def canonical_event(event_id: str | None) -> str:
    """EMSR id. valencia_2024 and ahr_2021 map to the id the agents store."""
    raw = (str(event_id).strip() if event_id else "") or DEFAULT_EVENT
    return _EVENT_ALIASES.get(raw, raw)


def fingerprint(config: dict[str, Any]) -> str:
    """The agents' flags, lanes and schema, from their GET /config."""
    flags = config.get("flags") or {}
    lanes = config.get("lanes") or {}
    parts = [f"{k}={flags[k]}" for k in sorted(flags)]
    parts += [f"lane.{k}={lanes[k]}" for k in sorted(lanes)]
    parts.append(f"schema={config.get('schema')}")
    return ";".join(parts)


def key_of(request: dict[str, Any], flags: str) -> tuple:
    return (
        fold(str(request.get("question") or "")),
        request.get("event_id") or DEFAULT_EVENT,
        request.get("customer_id") or DEFAULT_CUSTOMER,
        normalize_utc(request.get("replay_ts")),
        request.get("lang") or DEFAULT_LANG,
        fold(str(request.get("doc_query") or "")),
        flags,
    )


def _hhmm(ts: str | None) -> str | None:
    """14:32 out of 2026-10-24T14:32:51Z. None when there is no usable stamp."""
    if not ts or len(ts) < 16 or ts[10] not in ("T", " "):
        return None
    return ts[11:16]


def describe(served_from: str | None, cached_at: str | None, run_id: str | None) -> dict[str, Any]:
    """The banner. Wording matches agents/floodsense_agents/labelling.py."""
    kind = served_from if served_from in ("live", "cache", "replay") else None
    if kind == "live":
        return {"live": True, "kind": "live", "text": None, "at": None}
    at = _hhmm(cached_at if isinstance(cached_at, str) else None)
    if kind == "cache":
        head = f"Cached answer from {at}" if at else "Cached answer"
    elif kind == "replay":
        head = f"Replay of a recorded run from {at}" if at else "Replay of a recorded run"
    else:
        head = "Provenance not recorded"
    parts = [head, "not live"]
    if run_id:
        parts.append(f"original run {run_id}")
    return {"live": False, "kind": kind or "unknown", "text": " · ".join(parts), "at": at}


def _request_of(source: dict[str, Any]) -> dict[str, Any]:
    request = source.get("request")
    return request if isinstance(request, dict) else {}


def question_text(source: dict[str, Any]) -> str:
    return str(source.get("question") or _request_of(source).get("question") or "")


def clock_from(source: dict[str, Any]) -> str | None:
    """The scenario clock, from the run or from its request. Not 'now'."""
    request = _request_of(source)
    if source.get("replay_ts") not in (None, ""):
        return normalize_utc(source.get("replay_ts"))
    return normalize_utc(request.get("replay_ts"))


def mark_cached(run: dict[str, Any]) -> dict[str, Any]:
    """A semantic-cache hit is cache, even when the stored run was a clocked replay.

    replay_ts and an existing cached_at stay that UTC instant. They are not
    rewritten to the time of the hit, and served_from is not left as replay.
    """
    if not run.get("cached_at"):
        clock = clock_from(run)
        if clock and _UTC_CANON.fullmatch(clock):
            run["cached_at"] = clock
    run["served_from"] = "cache"
    run["label"] = describe("cache", run.get("cached_at"), run.get("run_id"))
    return run


def annotate_replay(
    run: dict[str, Any], reason: str, failed_run_id: str | None = None
) -> dict[str, Any]:
    """Label a failover replay and name the question it actually answered."""
    question = question_text(run)
    clock = clock_from(run)
    if not run.get("cached_at") and clock and _UTC_CANON.fullmatch(clock):
        run["cached_at"] = clock
    run["served_from"] = "replay"
    label = describe("replay", run.get("cached_at"), run.get("run_id"))
    if question:
        label["text"] = f"{label['text']} · {question}"
    run["label"] = label
    block: dict[str, Any] = {
        "original_run_id": run.get("run_id"),
        "reason": reason,
        "question": question,
        "replay_ts": clock,
    }
    if failed_run_id:
        block["failed_run_id"] = failed_run_id
    run["replay"] = block
    return run


def _lang_of(source: dict[str, Any]) -> str:
    return str(source.get("lang") or _request_of(source).get("lang") or DEFAULT_LANG)


def _customer_of(source: dict[str, Any]) -> str:
    return str(
        source.get("customer_id") or _request_of(source).get("customer_id") or DEFAULT_CUSTOMER
    )


def _event_of(source: dict[str, Any]) -> str:
    return canonical_event(source.get("event_id") or _request_of(source).get("event_id"))


def ask_of(source: dict[str, Any]) -> tuple:
    """Question, event, customer, clock, language and doc_query, as replay compares them."""
    return (
        fold(question_text(source)),
        _event_of(source),
        _customer_of(source),
        clock_from(source),
        _lang_of(source),
        fold(str(source.get("doc_query") or _request_of(source).get("doc_query") or "")),
    )


def same_ask(request: dict[str, Any], run: dict[str, Any]) -> bool:
    """True when the run answered this question, event, customer, clock and language."""
    return ask_of(request) == ask_of(run)


def past_row_matches(request: dict[str, Any], row: dict[str, Any]) -> bool:
    """A /runs/past row that may be replayed for this request.

    Language is compared only when the row carries it. The agents' past list
    does not, so the full run is checked afterwards.
    """
    if not isinstance(row, dict):
        return False
    run_id = row.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return False
    if row.get("status") != "approved" or row.get("approval") not in REMEMBERED:
        return False
    if (row.get("thread_id") or run_id) != run_id:
        return False
    if canonical_event(row.get("event_id")) != canonical_event(request.get("event_id")):
        return False
    if (row.get("customer_id") or DEFAULT_CUSTOMER) != (
        request.get("customer_id") or DEFAULT_CUSTOMER
    ):
        return False
    if fold(str(row.get("question") or "")) != fold(str(request.get("question") or "")):
        return False
    if normalize_utc(row.get("replay_ts")) != normalize_utc(request.get("replay_ts")):
        return False
    row_lang = row.get("lang")
    if row_lang not in (None, "") and str(row_lang) != (request.get("lang") or DEFAULT_LANG):
        return False
    return True


def approved_by_a_person(run: dict[str, Any]) -> bool:
    """Approved or edited by a reviewer. Enough for a recording to replay."""
    approval = (run.get("approval") or {}).get("status")
    return run.get("status") == "approved" and approval in REMEMBERED


def finished_well(run: dict[str, Any]) -> bool:
    """Approved or edited by a person, and passed by the Judge. Nothing else is cached."""
    return approved_by_a_person(run) and (run.get("judge_summary") or {}).get("passes") is True


def is_follow_up(run: dict[str, Any]) -> bool:
    request = run.get("request") or {}
    return bool(request.get("thread_id")) or (run.get("thread_id") or run.get("run_id")) != run.get(
        "run_id"
    )


@dataclass
class Entry:
    run_id: str
    stored_at: float  # time.time() when cached
    ttl_s: float


class AnswerCache:
    """Process-local cache of finished runs, plus the last few recordings for replay."""

    def __init__(self, settings: CacheSettings | None = None) -> None:
        self.settings = settings or CacheSettings()
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple, Entry] = OrderedDict()
        self._recordings: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
        self._flags: tuple[float, str] | None = None

    # ---------------------------------------------------------------- flags

    def cached_flags(self) -> str | None:
        """The memoised flag fingerprint, or None when it is missing or stale."""
        now = time.monotonic()
        if self._flags is not None and now - self._flags[0] < FLAGS_MEMO_S:
            return self._flags[1]
        return None

    def flags(self, fetch) -> str | None:
        """The agents' flag fingerprint, memoised briefly. None when /config fails.

        ``fetch`` returns an already loaded config dict, or None. It is not
        asked to do I/O: the caller awaits that first.
        """
        memo = self.cached_flags()
        if memo is not None:
            return memo
        config = fetch()
        if config is None:
            return None
        fp = fingerprint(config)
        self._flags = (time.monotonic(), fp)
        return fp

    def forget_flags(self) -> None:
        self._flags = None

    # ---------------------------------------------------------------- cache

    def ttl_for(self, request: dict[str, Any], flags: str) -> float:
        live_data = "FF_LIVE_DATA=True" in flags.split(";") and not request.get("replay_ts")
        return self.settings.ttl_live_s if live_data else self.settings.ttl_replay_s

    def remember(self, run: dict[str, Any], flags: str) -> bool:
        """Cache a finished run. False when it does not qualify."""
        if not finished_well(run) or is_follow_up(run):
            return False
        request = run.get("request") or {}
        key = key_of(request, flags)
        entry = Entry(run["run_id"], time.time(), self.ttl_for(request, flags))
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self.settings.max_entries:
                self._entries.popitem(last=False)
        return True

    def lookup(self, request: dict[str, Any], flags: str) -> Entry | None:
        if request.get("thread_id"):
            return None
        key = key_of(request, flags)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if time.time() - entry.stored_at > entry.ttl_s:
                del self._entries[key]
                return None
            return entry

    def drop(self, run_id: str) -> None:
        with self._lock:
            for key in [k for k, e in self._entries.items() if e.run_id == run_id]:
                del self._entries[key]

    # ------------------------------------------------------------ recordings

    def record(self, replay_body: dict[str, Any]) -> None:
        """Keep a replay-labelled run, keyed by the question it answered."""
        stored = dict(replay_body)
        slot = ask_of(stored)
        with self._lock:
            self._recordings[slot] = stored
            self._recordings.move_to_end(slot)
            while len(self._recordings) > self.settings.max_recordings:
                self._recordings.popitem(last=False)

    def recording_for(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """The recording of this question, event, customer, clock and language."""
        with self._lock:
            body = self._recordings.get(ask_of(request))
            return dict(body) if body else None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "FF_SEMANTIC_CACHE": self.settings.semantic_cache,
                "FF_CACHED_REPLAY": self.settings.cached_replay,
                "entries": len(self._entries),
                "recordings": len(self._recordings),
                "ttl_live_s": self.settings.ttl_live_s,
                "ttl_replay_s": self.settings.ttl_replay_s,
                "lookup_timeout_s": self.settings.lookup_timeout_s,
            }
