from __future__ import annotations

import unittest

from forgemind.config import Settings
from forgemind.engine import LocalEngine


class ByteTokenizer:
    def __init__(self) -> None:
        self.last_messages = []
        self.last_max_tokens = 0

    def tokenize(self, text: bytes, **_kwargs) -> list[int]:
        return list(text)

    def detokenize(self, tokens: list[int]) -> bytes:
        return bytes(tokens)

    def create_chat_completion(self, *, messages, max_tokens, **_kwargs):
        self.last_messages = messages
        self.last_max_tokens = max_tokens
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}


class ContextTests(unittest.TestCase):
    def test_large_history_and_prompt_are_fitted_to_context(self) -> None:
        engine = LocalEngine()
        engine._model = ByteTokenizer()
        settings = Settings(context_size=8192, max_tokens=1400)
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": "history " + "h" * 5000}
            for index in range(12)
        ]
        user = "BEGIN-" + "u" * 20000 + "-END"
        memories = [{"source": "large note", "content": "m" * 20000}]
        messages, output_limit = engine._prepare_messages(history, user, settings, memories, [])
        content_size = sum(len(item["content"].encode("utf-8")) for item in messages)
        self.assertLessEqual(content_size, 6400)
        self.assertEqual(output_limit, 1400)
        self.assertTrue(messages[-1]["content"].startswith("BEGIN-"))
        self.assertTrue(messages[-1]["content"].endswith("-END"))

    def test_json_generation_fits_large_agent_prompt_to_context(self) -> None:
        engine = LocalEngine()
        model = ByteTokenizer()
        engine._model = model
        engine._context_size = 8192
        result = engine.generate_json("system " + "s" * 10000, "BEGIN-" + "p" * 50000 + "-END")
        content_size = sum(len(item["content"].encode("utf-8")) for item in model.last_messages)
        self.assertEqual(result, {"ok": True})
        self.assertLessEqual(content_size + model.last_max_tokens, 8192)
        self.assertTrue(model.last_messages[-1]["content"].startswith("BEGIN-"))
        self.assertTrue(model.last_messages[-1]["content"].endswith("-END"))

    def test_patch_budget_is_not_silently_capped_at_2048(self):
        engine = LocalEngine()
        engine._model = ByteTokenizer()
        engine.generate_json("system", "small patch", max_tokens=3500)
        self.assertEqual(engine._model.last_max_tokens, 3500)

    def test_truncated_json_is_not_accepted_as_a_partial_patch(self):
        class Truncated(ByteTokenizer):
            def create_chat_completion(self, **_kwargs):
                return {"choices": [{"finish_reason": "length", "message": {"content": '{"ok": true}'}}]}
        engine = LocalEngine()
        engine._model = Truncated()
        with self.assertRaisesRegex(ValueError, "truncated"):
            engine.generate_json("system", "patch")


if __name__ == "__main__":
    unittest.main()
