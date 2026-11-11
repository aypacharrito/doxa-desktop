"""Response-speed changes in 1.11: shorter chat prompt, bigger GPU batches with fallback, parallel web reads."""
from __future__ import annotations

import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from forgemind.config import SYSTEM_PROMPT, Settings, system_prompt_for
from forgemind.engine import LocalEngine
from forgemind.web import research_web


class PromptTests(unittest.TestCase):
    def test_plain_chat_sends_only_the_core(self):
        prompt = system_prompt_for("hey jarvis, how was your day")
        self.assertLess(len(prompt), len(SYSTEM_PROMPT) // 2)
        self.assertIn("You are Doxa", prompt)
        self.assertIn("Browser task", prompt)  # browser guidance must survive the trim
        self.assertNotIn("Neural Research Lab", prompt)

    def test_topics_bring_back_their_sections(self):
        self.assertIn("Neural Research Lab", system_prompt_for("can you improve yourself?"))
        self.assertIn("Computer tasks", system_prompt_for("can you control my desktop"))
        self.assertIn("For coding work", system_prompt_for("fix this python error"))
        self.assertIn("CURRENT WEB SEARCH RESULTS", system_prompt_for("who won", has_web=True))
        self.assertEqual(system_prompt_for("improve your code and research this link https://x.y"), SYSTEM_PROMPT)

    def test_engine_uses_the_trimmed_prompt(self):
        class Tokenizer:
            def tokenize(self, text, **_):
                return list(text)

            def detokenize(self, tokens):
                return bytes(tokens)

        engine = LocalEngine()
        engine._model = Tokenizer()
        messages, _ = engine._prepare_messages([], "hello there", Settings(), [], [])
        self.assertNotIn("Neural Research Lab", messages[0]["content"])
        self.assertIn("You are Doxa", messages[0]["content"])


class BatchFallbackTests(unittest.TestCase):
    def load_with(self, fail_large):
        attempts = []

        class FakeLlama:
            def __init__(self, **kwargs):
                attempts.append((kwargs["n_batch"], kwargs["n_ubatch"]))
                if fail_large and kwargs["n_batch"] == 1024:
                    raise ValueError("Failed to create llama_context (out of GPU memory)")
                self.metadata = {"general.architecture": "llama"}

            def close(self):
                pass

        fake = types.ModuleType("llama_cpp")
        fake.Llama = FakeLlama
        with tempfile.NamedTemporaryFile(suffix=".gguf") as model, patch.dict(sys.modules, {"llama_cpp": fake}):
            engine = LocalEngine()
            engine.load(model.name)
        return engine, attempts

    def test_uses_large_batches_when_they_fit(self):
        engine, attempts = self.load_with(fail_large=False)
        self.assertEqual(attempts, [(1024, 512)])
        self.assertEqual(engine.batch_sizes, (1024, 512))
        self.assertTrue(engine.loaded)

    def test_falls_back_to_previous_sizes_when_vram_is_short(self):
        engine, attempts = self.load_with(fail_large=True)
        self.assertEqual(attempts, [(1024, 512), (256, 128)])
        self.assertEqual(engine.batch_sizes, (256, 128))
        self.assertTrue(engine.loaded)


class SlowDDGS:
    delays = {}

    def __init__(self, **_):
        pass

    def text(self, query, **_):
        return [{"title": f"Page {n}", "href": f"https://example.com/{n}", "body": f"snippet {n}"} for n in range(3)]

    def extract(self, url, **_):
        time.sleep(self.delays.get(url, 0.5))
        return {"title": url, "content": f"full text of {url}"}


class ParallelWebTests(unittest.TestCase):
    def test_pages_are_read_in_parallel(self):
        SlowDDGS.delays = {}
        with patch.dict(sys.modules, {"ddgs": types.SimpleNamespace(DDGS=SlowDDGS)}):
            started = time.monotonic()
            results = research_web("what is the weather", max_results=3, extract_results=3)
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.2)  # three 0.5 s pages; sequential would take 1.5 s+
        self.assertTrue(all(r.evidence.startswith("full text") for r in results))

    def test_a_slow_page_cannot_hold_up_the_answer(self):
        SlowDDGS.delays = {"https://example.com/1": 5}
        with patch.dict(sys.modules, {"ddgs": types.SimpleNamespace(DDGS=SlowDDGS)}):
            started = time.monotonic()
            results = research_web("what is the weather", max_results=3, extract_results=3, deadline_seconds=1)
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.8)
        self.assertEqual(results[1].evidence, "snippet 1")
        self.assertTrue(results[0].evidence.startswith("full text"))


if __name__ == "__main__":
    unittest.main()
