"""Test-only LLM provider switch: Nightshift by default, Anthropic behind a gate.

Fake HTTP only. No real Anthropic or Nightshift call is made.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHECKPOINTER", "memory")
os.environ.setdefault("ZETARIS_MODE", "fake")
os.environ.setdefault("LLM_MODE", "fake")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from floodsense_agents import __main__ as service  # noqa: E402
from floodsense_agents.graph import build_graph  # noqa: E402
from floodsense_agents.nightshift import (  # noqa: E402
    AnthropicClient,
    FakeNightshift,
    ProviderSwitch,
    available_providers,
    build_llm,
    current_provider,
)
from floodsense_agents.runtime import Runtime  # noqa: E402
from floodsense_agents.state import Deps, NoMemory  # noqa: E402
from floodsense_agents.zetaris import FakeZetaris  # noqa: E402

ON = {"LLM_PROVIDER_SWITCH": "true", "ANTHROPIC_API_KEY": "test-not-a-key"}
OFF = {"LLM_PROVIDER_SWITCH": "", "ANTHROPIC_API_KEY": ""}


class FakeAnthropicHTTP:
    """Stands in for httpx.post against the Messages API."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        body = {
            "model": json["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "{}"}],
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))


class LabelledFake(FakeNightshift):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def complete(self, lane, system, user, *, json=True):
        text, _ = super().complete(lane, system, user, json=json)
        return text, f"{self.label}/{lane}"


class GateTest(unittest.TestCase):
    def test_gate_off_lists_nightshift_only(self) -> None:
        with patch.dict(os.environ, OFF):
            self.assertEqual(available_providers(), ["nightshift"])
        with patch.dict(os.environ, {"LLM_PROVIDER_SWITCH": "true", "ANTHROPIC_API_KEY": ""}):
            self.assertEqual(available_providers(), ["nightshift"])
        with patch.dict(os.environ, {"LLM_PROVIDER_SWITCH": "false", "ANTHROPIC_API_KEY": "k"}):
            self.assertEqual(available_providers(), ["nightshift"])

    def test_gate_on_lists_both(self) -> None:
        with patch.dict(os.environ, ON):
            self.assertEqual(available_providers(), ["nightshift", "anthropic"])

    def test_build_llm_always_wraps_so_gate_is_read_per_call(self) -> None:
        with patch.dict(os.environ, OFF):
            llm = build_llm()  # built while the gate is off...
        self.assertIsInstance(llm, ProviderSwitch)
        fake = LabelledFake("anthropic")
        llm.anthropic = fake
        token = current_provider.set("anthropic")
        try:
            with patch.dict(os.environ, ON):  # ...turned on later: still routes
                _, mid = llm.complete("fast", "TASK: skeptic", "u")
        finally:
            current_provider.reset(token)
        self.assertEqual(mid, "anthropic/fast")

    def test_anthropic_run_without_gate_raises(self) -> None:
        night = LabelledFake("nightshift")
        llm = ProviderSwitch(night, LabelledFake("anthropic"))
        token = current_provider.set("anthropic")
        try:
            with patch.dict(os.environ, OFF):
                with self.assertRaises(RuntimeError):
                    llm.complete("fast", "TASK: skeptic", "u")
        finally:
            current_provider.reset(token)
        self.assertFalse(night.calls)


class AnthropicClientTest(unittest.TestCase):
    def test_model_id_is_labelled_and_lanes_map(self) -> None:
        http = FakeAnthropicHTTP()
        with patch.dict(os.environ, {**ON, "ANTHROPIC_MODEL_FAST": "", "ANTHROPIC_MODEL_DEEP": ""}):
            c = AnthropicClient(post=http)
            _, fast = c.complete("fast", "TASK: skeptic", "u")
            _, deep = c.complete("deep", "TASK: judge", "u")
        self.assertEqual(fast, "anthropic/claude-haiku-5-5")
        self.assertEqual(deep, "anthropic/claude-sonnet-5-5")
        sent = http.calls[0]
        self.assertEqual(sent["headers"]["x-api-key"], "test-not-a-key")
        self.assertNotIn("temperature", sent["json"])
        self.assertIn("JSON", sent["json"]["system"])

    def _reply(self, body: dict):
        def post(url, json=None, headers=None, timeout=None):
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

        return post

    def test_max_tokens_and_empty_text_raise(self) -> None:
        cut = {
            "model": "m",
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "{"}],
        }
        empty = {"model": "m", "stop_reason": "end_turn", "content": [{"type": "thinking"}]}
        with patch.dict(os.environ, ON), patch("floodsense_agents.nightshift.time.sleep"):
            for body in (cut, empty):
                with self.assertRaises(RuntimeError):
                    AnthropicClient(post=self._reply(body)).complete("fast", "TASK: x", "u")

    def test_model_override(self) -> None:
        http = FakeAnthropicHTTP()
        with patch.dict(os.environ, {**ON, "ANTHROPIC_MODEL_FAST": "claude-opus-5-5"}):
            _, mid = AnthropicClient(post=http).complete("fast", "TASK: x", "u")
        self.assertEqual(mid, "anthropic/claude-opus-5-5")


class ServiceSwitchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.anthropic = LabelledFake("anthropic")
        self.nightshift = LabelledFake("nightshift")
        llm = ProviderSwitch(self.nightshift, self.anthropic)
        deps = Deps(zetaris=FakeZetaris(), llm=llm, memory=NoMemory())
        service.set_runtime(
            Runtime(graph=build_graph(deps, MemorySaver(), ff_judge=True), deps=deps)
        )
        self.c = TestClient(service.app)
        self.body = {"question": "Why are our Valencia sites at risk?", "event_id": "EMSR773"}

    def _models(self, run: dict) -> set[str]:
        # "deterministic" marks a node that answered without a model call.
        return {
            t["model_id"]
            for t in run["trace"]
            if t.get("model_id") and t["model_id"] != "deterministic"
        }

    def test_gate_off_rejects_anthropic_and_config_hides_it(self) -> None:
        with patch.dict(os.environ, OFF):
            self.assertEqual(self.c.get("/config").json()["llm_providers"], ["nightshift"])
            r = self.c.post("/runs", json={**self.body, "llm_provider": "anthropic"})
            self.assertEqual(r.status_code, 422)
            r = self.c.post("/runs", json=self.body)
            self.assertEqual(r.status_code, 201)
        self.assertFalse(self.anthropic.calls)
        models = self._models(r.json())
        self.assertTrue(models)
        self.assertTrue(all(m.startswith("nightshift/") for m in models), models)

    def test_unknown_provider_rejected_even_when_on(self) -> None:
        with patch.dict(os.environ, ON):
            r = self.c.post("/runs", json={**self.body, "llm_provider": "openai"})
        self.assertEqual(r.status_code, 422)

    def test_gate_on_routes_per_run(self) -> None:
        with patch.dict(os.environ, ON):
            self.assertEqual(
                self.c.get("/config").json()["llm_providers"], ["nightshift", "anthropic"]
            )
            a = self.c.post("/runs", json={**self.body, "llm_provider": "anthropic"}).json()
            n = self.c.post("/runs", json=self.body).json()
        self.assertTrue(self._models(a))
        self.assertTrue(all(m.startswith("anthropic/") for m in self._models(a)))
        self.assertTrue(all(m.startswith("nightshift/") for m in self._models(n)))
        self.assertEqual(a["request"]["llm_provider"], "anthropic")
        self.assertEqual(n["request"]["llm_provider"], "nightshift")


if __name__ == "__main__":
    unittest.main()
