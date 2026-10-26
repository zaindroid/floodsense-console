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
import re
import time
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


def build_llm() -> LLM:
    if settings.llm_mode == "fake" or (
        settings.llm_mode == "auto" and not settings.meterless_base_url
    ):
        log.warning("LLM: METERLESS_BASE_URL unset -> FakeNightshift (offline, deterministic)")
        return FakeNightshift()
    return NightshiftClient()
