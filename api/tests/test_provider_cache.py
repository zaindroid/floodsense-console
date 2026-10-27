"""A run answered by one LLM provider is never served for another (test-only switch)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import ask_of, key_of, same_ask  # noqa: E402

Q = {"question": "Why are our Valencia sites at risk?", "event_id": "EMSR773"}


class ProviderCacheKeyTest(unittest.TestCase):
    def test_default_is_nightshift(self) -> None:
        self.assertEqual(key_of(Q, "f"), key_of({**Q, "llm_provider": "nightshift"}, "f"))
        self.assertEqual(ask_of(Q), ask_of({**Q, "llm_provider": "Nightshift"}))

    def test_providers_get_separate_cache_keys(self) -> None:
        self.assertNotEqual(key_of(Q, "f"), key_of({**Q, "llm_provider": "anthropic"}, "f"))

    def test_replay_does_not_cross_providers(self) -> None:
        anthropic_run = {"request": {**Q, "llm_provider": "anthropic"}, "event_id": "EMSR773"}
        nightshift_run = {"request": dict(Q), "event_id": "EMSR773"}
        self.assertFalse(same_ask(Q, anthropic_run))
        self.assertTrue(same_ask(Q, nightshift_run))
        self.assertTrue(same_ask({**Q, "llm_provider": "anthropic"}, anthropic_run))


if __name__ == "__main__":
    unittest.main()
