from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from forgemind.growth import GrowthStore
from forgemind.self_evolve import SelfEvolver
from forgemind.source_context import source_excerpt


class FakeEngine:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_json(self, *_args, **_kwargs):
        return self.responses.pop(0)


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.store = GrowthStore(self.root / "growth", seed=False)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, title="Useful upgrade", goal="Implement a useful tested upgrade to ForgeMind"):
        return self.store.add(title, goal, "Tests prove the new behavior and preserve prior behavior")

    def test_one_active_task_and_pause_survive_restart(self):
        self.add()
        self.add("Second", "Implement a second useful tested upgrade to ForgeMind")
        first = self.store.claim()
        self.assertIsNotNone(first)
        reopened = GrowthStore(self.root / "growth", seed=False)
        self.assertIsNone(reopened.claim())
        self.store.finish(first["id"], {"status": "stopped", "applied": False, "tests_passed": False})
        self.store.configure(enabled=False)
        self.assertIsNone(reopened.claim())
        self.assertFalse(reopened.preference("enabled"))

    def test_failure_remains_visible_while_next_goal_can_run(self):
        identifier = self.add()
        self.add("Next", "Implement another distinct useful tested ForgeMind upgrade")
        self.store.claim()
        self.assertEqual(self.store.finish(identifier, {"status": "needs_input", "summary": "Missing dependency",
                         "applied": False, "tests_passed": False}), "needs_attention")
        self.assertNotEqual(self.store.claim()["id"], identifier)
        self.assertIn("Missing dependency", self.store.tasks()[0]["result"])

    def test_failed_verification_cannot_be_recorded_as_installed(self):
        identifier = self.add()
        self.store.claim()
        with self.assertRaises(ValueError):
            self.store.finish(identifier, {"applied": True, "tests_passed": False})
        self.assertEqual(self.store.active()["id"], identifier)

    def test_planner_deduplicates_goals(self):
        proposal = {"tasks": [{"title": "Feature", "goal": "Implement a useful tested upgrade to ForgeMind",
                                "acceptance": "Tests pass"}]}
        self.assertEqual(self.store.propose(FakeEngine([proposal]), "forgemind/example.py"), 1)
        self.assertEqual(self.store.propose(FakeEngine([proposal]), "forgemind/example.py"), 0)

    def test_interrupted_task_recovers_when_its_process_exited(self):
        self.add()
        self.store.claim()
        source = self.root / "source"
        source.mkdir()
        evolver = SelfEvolver(source, self.root / "evolution")
        with patch("forgemind.growth._alive", return_value=False):
            self.store.recover(evolver)
        self.assertEqual(self.store.tasks()[0]["status"], "pending")

    def test_source_excerpt_finds_function_after_large_header(self):
        text = "\n".join(f"def unrelated_{i}():\n    return '{'x' * 80}'\n" for i in range(100))
        text += "\ndef fetch_web_page(url):\n    return 'target behavior'\n"
        excerpt = source_excerpt(text, "Fix internet web fetching", 1200)
        self.assertIn("def fetch_web_page(url):", excerpt)
        self.assertIn("target behavior", excerpt)
        self.assertLessEqual(len(excerpt), 1200)

    def test_idle_scheduler_starts_real_queue_task_but_preserves_drafts(self):
        from app import ForgeMindApp
        self.add()
        app = SimpleNamespace(
            _last_activity=time.monotonic() - 61, _growth_restart_pending=False,
            growth=self.store, busy=False, engine=SimpleNamespace(loaded=True),
            growth_label=Mock(), voice=SimpleNamespace(enabled=False),
            _creator_operations=0, _upload_running=False, _next_growth_plan=0,
            input=Mock(), start_evolution=Mock(), after=Mock(), _plan_growth=Mock())
        app.input.get.return_value = "unfinished user message"
        app._growth_tick = lambda: ForgeMindApp._growth_tick(app)
        ForgeMindApp._growth_tick(app)
        app.start_evolution.assert_not_called()
        app.input.get.return_value = ""
        app.voice.enabled = True
        ForgeMindApp._growth_tick(app)
        app.start_evolution.assert_not_called()
        app.voice.enabled = False
        ForgeMindApp._growth_tick(app)
        app.start_evolution.assert_called_once()
        self.assertEqual(app.start_evolution.call_args.kwargs["growth_task_id"], self.store.active()["id"])

    def test_automatic_restart_waits_for_media_operations(self):
        from app import ForgeMindApp
        app = SimpleNamespace(_last_activity=time.monotonic() - 61, _growth_restart_pending=True,
                              busy=False, _upload_running=False, _creator_operations=1,
                              _restart_app=Mock(), after=Mock(), _growth_tick=Mock(), growth_label=Mock(), growth=self.store)
        ForgeMindApp._growth_tick(app)
        app._restart_app.assert_not_called()
        app._creator_operations = 0
        ForgeMindApp._growth_tick(app)
        app._restart_app.assert_called_once()

    def test_real_candidate_pipeline_installs_and_records_upgrade_without_web(self):
        source = self.root / "source"
        (source / "forgemind").mkdir(parents=True)
        (source / "tests").mkdir()
        (source / "app.py").write_text("from forgemind.feature import value\n", encoding="utf-8")
        (source / "forgemind" / "__init__.py").write_text("", encoding="utf-8")
        feature = source / "forgemind" / "feature.py"
        feature.write_text("def value():\n    return 1\n", encoding="utf-8")
        (source / "tests" / "test_feature.py").write_text(
            "import unittest\nfrom forgemind.feature import value\nclass T(unittest.TestCase):\n"
            "    def test_baseline(self):\n        self.assertGreaterEqual(value(), 1)\n", encoding="utf-8")
        identifier = self.add("Actual source update", "Change the feature value from 1 to 2 with a test")
        task = self.store.claim()
        engine = FakeEngine([
            {"target_files": ["forgemind/feature.py"], "rationale": "Owns the feature"},
            {"summary": "Upgrade the value", "edits": [{"path": "forgemind/feature.py", "find": "return 1", "replace": "return 2"}],
             "new_files": [{"path": "evolver_tests/test_value.py", "content":
                 "import unittest\nfrom forgemind.feature import value\nclass T(unittest.TestCase):\n"
                 "    def test_upgrade(self):\n        self.assertEqual(value(), 2)\n"}]},
            {"score": 90, "summary": "Tests prove the value changed", "concerns": []},
        ])
        evolver = SelfEvolver(source, self.root / "evolution")
        with patch("forgemind.self_evolve.research_web", side_effect=RuntimeError("No results found")):
            result = evolver.run_until_verified(task["goal"], engine, use_research=True)
        self.assertEqual(self.store.finish(identifier, result), "installed")
        self.assertIn("return 2", feature.read_text(encoding="utf-8"))
        self.assertTrue(result.tests_passed)
        self.assertIn("Web research unavailable", Path(result.report_path).read_text(encoding="utf-8"))
        self.assertTrue(json.loads(self.store.tasks()[0]["result"])["applied"])


if __name__ == "__main__":
    unittest.main()
