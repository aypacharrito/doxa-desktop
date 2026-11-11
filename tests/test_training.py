from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forgemind.training import TrainingLab


class TrainingLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.lab = TrainingLab(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_add_load_and_reject_duplicate(self) -> None:
        first = self.lab.add_reviewed_example("Write a test", "Use unittest.", tags=["python", "python"])
        self.assertEqual(first["tags"], ["python"])
        self.assertEqual(len(self.lab.load_examples()), 1)
        with self.assertRaises(ValueError):
            self.lab.add_reviewed_example("Write a test", "Use unittest.")

    def test_validation_requires_a_minimum(self) -> None:
        self.lab.add_reviewed_example("Question", "Reviewed answer")
        self.assertFalse(self.lab.validate_dataset(minimum_examples=2)["ready_for_trial"])
        self.lab.add_reviewed_example("Another question", "Another reviewed answer")
        self.assertTrue(self.lab.validate_dataset(minimum_examples=2)["ready_for_trial"])

    def test_export_uses_chat_messages(self) -> None:
        item = self.lab.add_reviewed_example("Fix this", "Here is the fix", source="owner")
        target = self.lab.export_chat_jsonl(Path(self.temp.name) / "data.jsonl")
        record = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(record["messages"][0], {"role": "user", "content": "Fix this"})
        self.assertEqual(record["messages"][1]["role"], "assistant")
        self.assertEqual(record["metadata"]["id"], item["id"])

    def test_plan_is_hardware_aware_and_does_not_claim_training_started(self) -> None:
        path = self.lab.create_lora_plan("qwen-7b-q4.gguf", vram_mb=8188, context_size=8192)
        plan = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(plan["status"], "plan_only_not_started")
        self.assertEqual(plan["recommended_recipe"]["method"], "QLoRA")
        self.assertEqual(plan["recommended_recipe"]["sequence_length"], 2048)
        self.assertIn("GGUF", plan["important_limit"])

    def test_adapter_registry_records_verification_state(self) -> None:
        self.lab.register_adapter("adapter-a", "qwen-7b", 0.82, status="verified")
        adapters = self.lab.list_adapters()
        self.assertEqual(adapters[0]["status"], "verified")
        self.assertEqual(adapters[0]["benchmark_score"], 0.82)


if __name__ == "__main__":
    unittest.main()
