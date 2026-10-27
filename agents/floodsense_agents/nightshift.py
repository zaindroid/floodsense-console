"""Nightshift client. Every model call goes through here.

    complete(lane, system, user, *, json=True) -> (text, model_id)

``lane`` is "fast" or "deep" and picks ``MODEL_FAST`` / ``MODEL_DEEP``
(``meterless/fast`` and ``meterless/deep``). Nightshift chooses the model.
The model id that answered comes back so the trace and the Judge scores can
record it. FakeNightshift answers offline with deterministic JSON, so tests
and the UI need no credits.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from json import loads as _loads
from typing import Callable, Iterable, Protocol, TypeVar

import httpx

from floodsense_agents.settings import settings

log = logging.getLogger("floodsense.nightshift")


class LLM(Protocol):
    def complete(
        self, lane: str, system: str, user: str, *, json: bool = True
    ) -> tuple[str, str]: ...


def parse_json(text: str) -> dict:
    """First JSON object in a model reply; tolerates ``` fences and prose around it."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, depth = t.find("{"), 0
    for i in range(start, len(t)) if start >= 0 else []:
        depth += t[i] == "{"
        depth -= t[i] == "}"
        if depth == 0:
            return json.loads(t[start : i + 1])
    raise ValueError(f"no JSON object in reply: {text[:160]!r}")


T = TypeVar("T")
R = TypeVar("R")


def map_ordered(fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
    """``[fn(x) for x in items]`` on up to ``llm_max_parallel`` threads.

    Results come back in input order, so traces and scores stay deterministic.
    Each task runs in a copy of the caller's context: the per-run provider
    ContextVar must reach the worker threads. ``fn`` should not raise; if it
    does, the first exception (in input order) propagates.
    """
    xs = list(items)
    limit = max(1, int(settings.llm_max_parallel))
    if limit == 1 or len(xs) <= 1:
        return [fn(x) for x in xs]
    with ThreadPoolExecutor(max_workers=min(limit, len(xs))) as ex:
        futs = [ex.submit(copy_context().run, fn, x) for x in xs]
        return [f.result() for f in futs]


def stream_post(url: str, *, json: dict, headers: dict, timeout: float) -> httpx.Response:
    """``httpx.post`` for chat completions, sent as a stream (SSE).

    Returns an ``httpx.Response`` shaped like the non-streamed reply
    (``choices[0].message.content``, ``finish_reason``, ``model``, ``usage``),
    so the retry policy in ``_send`` is unchanged. A non-200 comes back as
    is; a stream that closes with no answer raises ValueError (transient).
    The gateway's ~45 s 502 cuts non-streamed requests only.
    """
    payload = {**json, "stream": True, "stream_options": {"include_usage": True}}
    req = httpx.Request("POST", url)
    with httpx.stream("POST", url, json=payload, headers=headers, timeout=timeout) as r:
        if r.status_code != 200:
            r.read()
            return httpx.Response(r.status_code, content=r.content, headers=r.headers, request=req)
        parts: list[str] = []
        finish = model = usage = None
        stray: list[str] = []  # error events or non-SSE lines, for the error message
        # httpx's timeout is per read: pings or trickled tokens would keep a
        # worker here far past llm_timeout_s. One deadline for the whole call;
        # a timeout is final in _send (not retried).
        deadline = time.monotonic() + timeout
        for line in r.iter_lines():
            if time.monotonic() > deadline:
                raise httpx.ReadTimeout(f"stream exceeded {timeout:.0f}s", request=req)
            if not line.startswith("data:"):
                if line.strip() and not line.startswith((":", "event:", "id:", "retry:")):
                    stray.append(line.strip()[:160])
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = _loads(data)
            if chunk.get("error"):
                # An error event, even after some content, is a failed reply:
                # never hand truncated text on as a success.
                raise ValueError(f"stream provider_error: {str(chunk['error'])[:400]}")
            model = chunk.get("model") or model
            usage = chunk.get("usage") or usage
            for ch in chunk.get("choices") or []:
                piece = (ch.get("delta") or {}).get("content")
                if piece:
                    parts.append(piece)
                finish = ch.get("finish_reason") or finish
    if not (parts or finish):
        # The stream closed before any answer (seen at ~45 s on Nightshift).
        # ValueError: _send's transient-error path decides on a retry.
        raise ValueError(
            f"stream ended without an answer: {' | '.join(stray[-2:])[:500] or 'no data'}"
        )
    out = {
        "model": model,
        "usage": usage,
        "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish}],
    }
    return httpx.Response(200, json=out, request=req)


class NightshiftClient:
    def __init__(
        self,
        post: Callable[..., httpx.Response] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = (settings.meterless_base_url or "").rstrip("/")
        self._post = post or (stream_post if settings.llm_stream else httpx.post)
        self._sleep = sleep

    def models(self) -> list[str]:
        r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return [m.get("id", "") for m in r.json().get("data", [])]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.meterless_runtime_token}",
            "meterless-app": settings.meterless_app,
            "meterless-scope": settings.meterless_scope,
        }

    def complete(self, lane: str, system: str, user: str, *, json: bool = True) -> tuple[str, str]:
        model = settings.lane(lane)
        body: dict = {
            "model": model,
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "chat_template_kwargs": {"enable_thinking": False},
        }  # Nemotron: no reasoning preamble
        if json:
            body["response_format"] = {"type": "json_object"}
        cap = settings.llm_max_tokens_fast if lane == "fast" else settings.llm_max_tokens_deep
        if cap > 0:
            body["max_tokens"] = cap
        return self._send(lane, model, body)

    def _send(self, lane: str, model: str, body: dict) -> tuple[str, str]:
        """POST with the retry policy.

        Up to ``llm_max_attempts`` tries for transient errors. A timeout is
        final at once: it already took ``llm_timeout_s`` and a second wait
        would double the worst case. The JSON-mode downgrade is not an attempt.
        """
        attempts = max(1, settings.llm_max_attempts)
        last: Exception | None = None
        attempt = 0
        while attempt < attempts:
            t0 = time.time()
            try:
                r = self._post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=self._headers(),
                    timeout=settings.llm_timeout_s,
                )
                if (
                    r.status_code == 400
                    and "response_format" in body
                    and "response_format" in r.text
                ):
                    body.pop("response_format")
                    continue  # runtime without JSON mode: prompt carries it
                r.raise_for_status()
                js = r.json()
                choice = js["choices"][0]
                text = choice["message"]["content"] or ""
                usage = js.get("usage") or {}
                log.info(
                    "nightshift lane=%s model=%s %.1fs prompt=%s completion=%s finish=%s",
                    lane,
                    js.get("model", model),
                    time.time() - t0,
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    choice.get("finish_reason"),
                )
                if choice.get("finish_reason") == "length":
                    # Truncated at max_tokens: never hand a cut reply to the
                    # parsers or the Judge. Not retried (same prompt, same cut).
                    raise RuntimeError("Nightshift reply cut off at max_tokens")
                return text, js.get("model", model)
            except httpx.TimeoutException as e:
                log.warning(
                    "nightshift lane=%s timed out after %.0fs; not retried", lane, time.time() - t0
                )
                raise RuntimeError(f"Nightshift timeout after {settings.llm_timeout_s:.0f}s") from e
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
                last = e
                attempt += 1
                took = time.time() - t0
                # A stream that ended in a provider error (empty_response) is
                # a failed upstream, not a long generation: one more try.
                provider_glitch = "provider_error" in str(e) or "empty_response" in str(e)
                if took >= settings.llm_slow_fail_s and not provider_glitch:
                    # A 502/504 after a long wait is the gateway cutting a long
                    # generation (measured ~45 s each): the same prompt will be
                    # cut again, so the node falls back instead of waiting 3x.
                    log.warning(
                        "nightshift lane=%s failed after %.0fs; not retried: %s",
                        lane,
                        took,
                        str(e)[:160],
                    )
                    break
                log.warning("nightshift attempt %d failed: %s", attempt, str(e)[:160])
                if attempt < attempts:
                    self._sleep(_retry_delay(e, attempt))
        raise RuntimeError(f"Nightshift unavailable: {last}")


RETRY_AFTER_CAP_S = 10.0


def _retry_delay(e: Exception, attempt: int) -> float:
    """Backoff before the next attempt; a 429's Retry-After (seconds), capped at 10 s."""
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
        raw = e.response.headers.get("retry-after", "")
        try:
            return min(max(float(raw), 0.0), RETRY_AFTER_CAP_S)
        except ValueError:
            pass  # an HTTP date or junk: fall back to the backoff
    return 1.5 * attempt


class FakeNightshift:
    """Deterministic stand-in for offline runs.

    `handlers[task](system, user) -> str`, keyed by the task tag in the first
    line of the system prompt (TASK: investigator | skeptic | playbook |
    judge | repair). An unknown task returns '{}' and the node falls back to
    its deterministic path.
    """

    def __init__(self, handlers: dict[str, Callable[[str, str], str]] | None = None) -> None:
        self.handlers = handlers or {}
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, lane: str, system: str, user: str, *, json: bool = True) -> tuple[str, str]:
        task = system.split("\n", 1)[0].replace("TASK:", "").strip().lower()
        self.calls.append((lane, task, user))
        h = self.handlers.get(task)
        return (h(system, user) if h else "{}"), f"fake-{lane}"


# --- Test-only provider switch -------------------------------------------
# Nightshift (NVIDIA Nemotron) is the default and the only provider the demo
# and the submission use. With LLM_PROVIDER_SWITCH=true and ANTHROPIC_API_KEY
# set, a run may ask for "anthropic" so the same pipeline can be benchmarked
# against the Anthropic API. The choice is per run: a ContextVar set around
# graph.invoke, so concurrent runs never share it and no deps are mutated.

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_DEFAULT_FAST = "claude-haiku-5-5"
ANTHROPIC_DEFAULT_DEEP = "claude-sonnet-5-5"

current_provider: ContextVar[str] = ContextVar("llm_provider", default="nightshift")


def _switch_on() -> bool:
    v = (os.environ.get("LLM_PROVIDER_SWITCH") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def available_providers() -> list[str]:
    """Providers a run may pick. Read live so tests and restarts see the env."""
    if _switch_on() and os.environ.get("ANTHROPIC_API_KEY"):
        return ["nightshift", "anthropic"]
    return ["nightshift"]


class AnthropicClient:
    """Same interface as NightshiftClient, over the Anthropic Messages API (raw HTTP).

    The answering model comes back as ``anthropic/<model>`` so the trace
    ``model_id`` can never be mistaken for a Nightshift lane.
    """

    def __init__(self, post: Callable[..., httpx.Response] | None = None) -> None:
        self._post = post or httpx.post

    @staticmethod
    def model_for(lane: str) -> str:
        if lane == "fast":
            return os.environ.get("ANTHROPIC_MODEL_FAST") or ANTHROPIC_DEFAULT_FAST
        if lane == "deep":
            return os.environ.get("ANTHROPIC_MODEL_DEEP") or ANTHROPIC_DEFAULT_DEEP
        raise KeyError(lane)

    def complete(self, lane: str, system: str, user: str, *, json: bool = True) -> tuple[str, str]:
        model = self.model_for(lane)
        if json:  # no prefill on current models; the system prompt carries it
            system = system + "\n\nReply with a single JSON object only, no prose, no code fences."
        body = {
            "model": model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            # Speed comparison: lowest effort on the fast lane.
            "output_config": {"effort": "low" if lane == "fast" else "medium"},
        }
        headers = {
            "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        last: Exception | None = None
        for attempt in range(3):
            try:
                t0 = time.time()
                r = self._post(
                    ANTHROPIC_URL, json=body, headers=headers, timeout=settings.llm_timeout_s
                )
                if r.status_code in (400, 401, 403, 404):
                    raise RuntimeError(f"Anthropic {r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                js = r.json()
                if js.get("stop_reason") == "refusal":
                    raise RuntimeError("Anthropic declined the request (refusal)")
                if js.get("stop_reason") == "max_tokens":
                    raise RuntimeError("Anthropic reply cut off at max_tokens")
                text = "".join(
                    b.get("text", "") for b in js.get("content", []) if b.get("type") == "text"
                )
                if not text.strip():
                    raise RuntimeError("Anthropic returned no text")
                answered = js.get("model") or model
                log.info("anthropic lane=%s model=%s %.1fs", lane, answered, time.time() - t0)
                return text, f"anthropic/{answered}"
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last = e
                log.warning("anthropic attempt %d failed: %s", attempt + 1, str(e)[:160])
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Anthropic unavailable: {last}")


class ProviderSwitch:
    """Routes each call to Nightshift or, when the run asked for it, Anthropic."""

    def __init__(self, nightshift: LLM, anthropic: LLM | None = None) -> None:
        self.nightshift = nightshift
        self.anthropic = anthropic or AnthropicClient()

    def complete(self, lane: str, system: str, user: str, *, json: bool = True) -> tuple[str, str]:
        if current_provider.get() == "anthropic":
            # Never answer an Anthropic run with Nightshift: the run is labelled
            # and cached as anthropic, so a silent fallback would mislead.
            if "anthropic" not in available_providers():
                raise RuntimeError(
                    "run asked for llm_provider=anthropic but the switch or key is gone"
                )
            return self.anthropic.complete(lane, system, user, json=json)
        return self.nightshift.complete(lane, system, user, json=json)


def build_llm() -> LLM:
    # Always wrapped: the gate is read per call, the same way the RunRequest
    # validator and GET /config read it, so the three can never disagree.
    # With the gate off every call goes to Nightshift.
    return ProviderSwitch(_build_nightshift())


def _build_nightshift() -> LLM:
    if settings.llm_mode == "fake" or (
        settings.llm_mode == "auto" and not settings.meterless_base_url
    ):
        log.warning("LLM: METERLESS_BASE_URL unset -> FakeNightshift (offline, deterministic)")
        return FakeNightshift()
    return NightshiftClient()
