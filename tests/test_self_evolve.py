from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from typing import Any

from forgemind.self_evolve import SelfEvolver


class FakeEngine:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)

    def generate_json(self, _system: str, _prompt: str, **_kwargs: Any) -> dict[str, Any]:
        return self.responses.pop(0)


def make_project(root: Path) -> None:
    (root / "forgemind").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app.py").write_text("from forgemind.feature import value\nprint(value())\n", encoding="utf-8")
    (root / "forgemind" / "__init__.py").write_text("", encoding="utf-8")
    (root / "forgemind" / "feature.py").write_text(
        "def value() -> int:\n    return 1\n", encoding="utf-8"
    )
    (root / "tests" / "test_feature.py").write_text(
        "import unittest\nfrom forgemind.feature import value\n\n"
        "class T(unittest.TestCase):\n    def test_value(self):\n        self.assertGreaterEqual(value(), 1)\n",
        encoding="utf-8",
    )


class SelfEvolverTests(unittest.TestCase):
    def test_owner_workspace_can_create_move_and_delete_owned_files(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            (source / "README.md").write_text("Original docs", encoding="utf-8")
            (source / "VERSION.txt").write_text("old", encoding="utf-8")
            evolver = SelfEvolver(source, base / "state")
            candidate = base / "candidate"
            evolver._copy_candidate(candidate)
            changed = evolver._apply_proposal(
                candidate,
                {
                    "edits": [],
                    "new_files": [{"path": "tools/helper.py", "content": "VALUE = 1\n"}],
                    "moves": [{"source": "README.md", "destination": "docs/README.md"}],
                    "deletes": [{"path": "VERSION.txt"}],
                },
            )
            self.assertIn("tools/helper.py", changed)
            self.assertTrue((candidate / "tools" / "helper.py").is_file())
            self.assertTrue((candidate / "docs" / "README.md").is_file())
            self.assertFalse((candidate / "VERSION.txt").exists())

    def test_baseline_verifier_tests_remain_external(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            evolver = SelfEvolver(source, base / "state")
            candidate = base / "candidate"
            evolver._copy_candidate(candidate)
            with self.assertRaises(ValueError):
                evolver._apply_proposal(
                    candidate,
                    {
                        "edits": [{"path": "tests/test_feature.py", "find": "value", "replace": "fake"}],
                        "new_files": [],
                    },
                )

    def test_owner_can_stop_unlimited_campaign(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_until_verified(
                "Keep improving", FakeEngine([]), use_research=False, max_attempts=0,
                should_stop=lambda: True,
            )
            self.assertEqual(result.status, "stopped")

    def test_unlimited_campaign_requests_input_for_repeated_identical_blocker(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            responses: list[dict[str, Any]] = []
            for _ in range(3):
                responses.extend(
                    [
                        {"target_files": ["forgemind/feature.py"], "rationale": "Try again."},
                        *[
                            {
                                "summary": "Same impossible edit.",
                                "edits": [
                                    {"path": "forgemind/feature.py", "find": "never present", "replace": "x"}
                                ],
                                "new_files": [],
                                "moves": [],
                                "deletes": [],
                            }
                            for _repair_attempt in range(3)
                        ],
                    ]
                )
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_until_verified(
                "Apply an impossible anchor", FakeEngine(responses), use_research=False, max_attempts=0
            )
            self.assertEqual(result.status, "needs_input")
            self.assertEqual(result.attempts, 3)

    def test_interrupted_campaign_goal_can_resume(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            evolver = SelfEvolver(source, base / "state")
            (evolver.campaigns_root / "20260101.json").write_text(
                json.dumps({"status": "retrying", "goal": "Add durable repository analysis"}),
                encoding="utf-8",
            )
            self.assertEqual(evolver.pending_goal(), "Add durable repository analysis")

    def test_campaign_retries_with_a_different_build_until_verified(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            engine = FakeEngine(
                [
                    {"target_files": ["forgemind/feature.py"], "rationale": "First approach."},
                    {
                        "summary": "Invalid first edit.",
                        "edits": [{"path": "forgemind/feature.py", "find": "not present", "replace": "x"}],
                        "new_files": [],
                    },
                    {
                        "summary": "Still invalid after seeing the error.",
                        "edits": [{"path": "forgemind/feature.py", "find": "also absent", "replace": "x"}],
                        "new_files": [],
                        "moves": [],
                        "deletes": [],
                    },
                    {
                        "summary": "Third invalid proposal.",
                        "edits": [{"path": "forgemind/feature.py", "find": "never present", "replace": "x"}],
                        "new_files": [],
                        "moves": [],
                        "deletes": [],
                    },
                    {"target_files": ["forgemind/feature.py"], "rationale": "Second approach."},
                    {
                        "summary": "Valid second edit.",
                        "edits": [{"path": "forgemind/feature.py", "find": "return 1", "replace": "return 3"}],
                        "new_files": [],
                    },
                    {"score": 94, "summary": "Goal verified.", "concerns": []},
                ]
            )
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_until_verified(
                "Return a larger value", engine, use_research=False, max_attempts=0
            )
            self.assertTrue(result.applied)
            self.assertEqual(result.attempts, 2)
            self.assertTrue(Path(result.campaign_path).is_file())
            self.assertIn("return 3", (source / "forgemind" / "feature.py").read_text(encoding="utf-8"))

    def test_invalid_anchor_is_repaired_before_verification(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            engine = FakeEngine(
                [
                    {"target_files": ["forgemind/feature.py"], "rationale": "Feature owns the value."},
                    {
                        "summary": "Initial anchor is wrong.",
                        "edits": [{"path": "forgemind/feature.py", "find": "missing", "replace": "x"}],
                        "new_files": [],
                    },
                    {
                        "summary": "Use an exact anchor from the refreshed source.",
                        "edits": [{"path": "forgemind/feature.py", "find": "return 1", "replace": "return 4"}],
                        "new_files": [],
                        "moves": [],
                        "deletes": [],
                    },
                    {"score": 95, "summary": "Corrected proposal verified.", "concerns": []},
                ]
            )
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_cycle("Return four", engine, use_research=False)
            self.assertTrue(result.applied)
            self.assertTrue(result.tests_passed)
            self.assertIn("return 4", (source / "forgemind" / "feature.py").read_text(encoding="utf-8"))

    def test_duplicate_anchor_is_repaired_with_a_unique_anchor(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            feature = source / "forgemind" / "feature.py"
            feature.write_text(
                "def value() -> int:\n    marker = 1\n    marker = 1\n    return marker\n",
                encoding="utf-8",
            )
            engine = FakeEngine(
                [
                    {"target_files": ["forgemind/feature.py"], "rationale": "Feature owns the marker."},
                    {
                        "summary": "Ambiguous anchor.",
                        "edits": [{"path": "forgemind/feature.py", "find": "marker = 1", "replace": "marker = 2"}],
                        "new_files": [],
                    },
                    {
                        "summary": "Use surrounding lines to identify one occurrence.",
                        "edits": [
                            {
                                "path": "forgemind/feature.py",
                                "find": "    marker = 1\n    return marker",
                                "replace": "    marker = 2\n    return marker",
                            }
                        ],
                        "new_files": [],
                        "moves": [],
                        "deletes": [],
                    },
                    {"score": 91, "summary": "Unique edit verified.", "concerns": []},
                ]
            )
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_cycle("Change the final marker", engine, use_research=False)
            self.assertTrue(result.applied)
            self.assertEqual(feature.read_text(encoding="utf-8").count("marker = 2"), 1)

    def test_generated_test_must_use_evolver_test_folder(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            evolver = SelfEvolver(source, base / "state")
            candidate = base / "candidate"
            evolver._copy_candidate(candidate)
            with self.assertRaisesRegex(ValueError, "New file is not allowed"):
                evolver._apply_proposal(
                    candidate,
                    {
                        "edits": [],
                        "new_files": [{"path": "tests/test_generated.py", "content": "pass\n"}],
                    },
                )
            changed = evolver._apply_proposal(
                candidate,
                {
                    "edits": [],
                    "new_files": [{"path": "evolver_tests/test_generated.py", "content": "pass\n"}],
                },
            )
            self.assertEqual(changed, ["evolver_tests/test_generated.py"])

    def test_blocker_signature_ignores_run_paths_and_timing_noise(self) -> None:
        first = (
            "Traceback at C:\\ForgeMind\\runs\\20261008-200355-309146\\candidate\\web.py, line 12\n"
            "ModuleNotFoundError: No module named 'requests'\nRan 15 tests in 0.215s"
        )
        second = (
            "Traceback at C:\\ForgeMind\\runs\\20261008-201122-998877\\candidate\\web.py, line 44\n"
            "ModuleNotFoundError: No module named 'requests'\nRan 15 tests in 1.913s"
        )
        self.assertEqual(
            SelfEvolver._normalize_blocker_text(first),
            SelfEvolver._normalize_blocker_text(second),
        )

    def test_failed_candidate_gets_one_repair_attempt(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            engine = FakeEngine(
                [
                    {"target_files": ["forgemind/feature.py"], "rationale": "Feature owns the value."},
                    {
                        "summary": "Introduce a capability, but with an accidental syntax error.",
                        "edits": [
                            {
                                "path": "forgemind/feature.py",
                                "find": "    return 1",
                                "replace": "    return (",
                            }
                        ],
                        "new_files": [],
                    },
                    {
                        "summary": "Repair the syntax error.",
                        "edits": [
                            {
                                "path": "forgemind/feature.py",
                                "find": "    return (",
                                "replace": "    return 2",
                            }
                        ],
                        "new_files": [],
                    },
                    {"score": 95, "summary": "Repaired goal met.", "concerns": []},
                ]
            )
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_cycle("Return a larger value", engine, use_research=False)
            self.assertTrue(result.applied)
            self.assertTrue(result.tests_passed)
            self.assertIn("return 2", (source / "forgemind" / "feature.py").read_text(encoding="utf-8"))

    def test_verified_change_applies_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            engine = FakeEngine(
                [
                    {"target_files": ["forgemind/feature.py"], "rationale": "Feature owns the value."},
                    {
                        "summary": "Increase the demonstrated capability.",
                        "edits": [
                            {
                                "path": "forgemind/feature.py",
                                "find": "    return 1",
                                "replace": "    return 2",
                            }
                        ],
                        "new_files": [],
                    },
                    {"score": 92, "summary": "Goal met with passing tests.", "concerns": []},
                ]
            )
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_cycle("Return a larger value", engine, use_research=False, auto_apply=True)
            self.assertTrue(result.applied)
            self.assertEqual(result.review_score, 92)
            self.assertIn("return 2", (source / "forgemind" / "feature.py").read_text(encoding="utf-8"))
            evolver.rollback_last()
            self.assertIn("return 1", (source / "forgemind" / "feature.py").read_text(encoding="utf-8"))

    def test_invalid_edit_is_rejected_without_touching_live_source(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            source = base / "source"
            source.mkdir()
            make_project(source)
            engine = FakeEngine(
                [
                    {"target_files": ["forgemind/feature.py"], "rationale": "Relevant file."},
                    {
                        "summary": "Broken anchor.",
                        "edits": [
                            {"path": "forgemind/feature.py", "find": "missing text", "replace": "new text"}
                        ],
                        "new_files": [],
                    },
                ]
            )
            evolver = SelfEvolver(source, base / "state")
            result = evolver.run_cycle("Make a change", engine, use_research=False, auto_apply=True)
            self.assertFalse(result.applied)
            self.assertEqual(result.status, "rejected")
            self.assertIn("return 1", (source / "forgemind" / "feature.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
