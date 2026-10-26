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
from contextvars import ContextVar
from typing import Callable, Protocol

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


class NightshiftClient:
    def __init__(self) -> None:
        self.base_url = (settings.meterless_base_url or "").rstrip("/")

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
        last: Exception | None = None
        for attempt in range(3):
            try:
                t0 = time.time()
                r = httpx.post(
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
                text = js["choices"][0]["message"]["content"] or ""
                log.info(
                    "nightshift lane=%s model=%s %.1fs",
                    lane,
                    js.get("model", model),
                    time.time() - t0,
                )
                return text, js.get("model", model)
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last = e
                log.warning("nightshift attempt %d failed: %s", attempt + 1, str(e)[:160])
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Nightshift unavailable: {last}")


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
