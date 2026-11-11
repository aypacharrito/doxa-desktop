from pathlib import Path
import tempfile
import unittest
from forgemind.self_build import stage
from forgemind.self_build import maybe_build
from types import SimpleNamespace
from unittest.mock import Mock
import threading


class BuildTests(unittest.TestCase):
    def test_missing_edit_capability_is_handed_off_once(self):
        state = {'runs': 0, 'log': []}
        team = SimpleNamespace(campaign=lambda: {'id': 'c1'}, counts=lambda: {'edit': 1},
                               lock=threading.RLock(), save=Mock())
        tools = SimpleNamespace(execute=Mock(return_value='Build job started'))
        app = SimpleNamespace(settings_data=SimpleNamespace(team_autopilot=True), team=team,
                              team_runner=SimpleNamespace(busy=[]), code_runner=SimpleNamespace(job=None),
                              prime=SimpleNamespace(_state=lambda: state), brain=SimpleNamespace(tools=tools))
        self.assertEqual(maybe_build(app), 'Build job started')
        self.assertIsNone(maybe_build(app))
        self.assertEqual(state['runs'], 1)
        tools.execute.assert_called_once()

    def test_copy_contains_code_without_private_data_or_live_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            (root / 'forgemind').mkdir(parents=True)
            (root / 'app.py').write_text('original')
            (root / 'forgemind' / 'agent.py').write_text('tool code')
            (root / 'forgemind' / 'secret.dpapi').write_bytes(b'private')
            (root / 'settings.json').write_text('private')
            target, prompt = stage(root, Path(tmp) / 'builds', 'Add offline editing')
            self.assertTrue((target / 'forgemind' / 'agent.py').exists())
            self.assertFalse((target / 'settings.json').exists())
            self.assertFalse((target / 'forgemind' / 'secret.dpapi').exists())
            (target / 'app.py').write_text('new code')
            self.assertEqual((root / 'app.py').read_text(), 'original')
            self.assertIn('BUILD-RESULT.md', prompt)


class UpgradeToolTests(unittest.TestCase):
    """2026-11-09 bug: build_doxa_capability crashed with "'WindowsPath' object has no attribute 'strip'"."""

    def test_the_upgrade_tool_hands_code_mode_a_folder_it_can_use(self):
        from forgemind.agent import DoxaTools
        from forgemind.code_mode import job_folder
        seen = {}

        def start_code_job(text, task, folder=None, engine="auto", source="YOU", post=True, follow_up=None):
            seen["folder"] = job_folder(folder, task)  # what CodeRunner.start does first
            seen["task"] = task
            return "Code mode started."

        with tempfile.TemporaryDirectory() as tmp:
            app = SimpleNamespace(code_runner=SimpleNamespace(job=None), start_code_job=start_code_job)
            tools = DoxaTools(app)
            from unittest import mock
            with mock.patch("forgemind.agent.Path.home", return_value=Path(tmp)):
                note = tools.execute("build_doxa_capability", {"task": "Add a listing writer"})
            self.assertEqual(note, "Code mode started.")
            self.assertTrue(seen["folder"].is_dir())
            self.assertTrue((seen["folder"] / "BUILD-TASK.md").is_file())
            self.assertIn("Add a listing writer", seen["task"])
            self.assertEqual(job_folder(Path(tmp), "x"), Path(tmp))
