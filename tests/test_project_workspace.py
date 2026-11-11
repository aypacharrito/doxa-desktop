from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from forgemind.project_workspace import ProjectWorkspace


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.source / ".env").write_text("TOKEN=private\n", encoding="utf-8")
        tests = self.source / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text(
            "import unittest\nimport main\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_value(self): self.assertEqual(main.VALUE, 2)\n",
            encoding="utf-8",
        )
        self.workspace = ProjectWorkspace(self.root / "workspace")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_candidate_is_isolated_and_secrets_are_excluded(self) -> None:
        state = self.workspace.create_candidate(self.source)
        candidate = Path(state["candidate"])
        (candidate / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertEqual((self.source / "main.py").read_text(encoding="utf-8"), "VALUE = 1\n")
        self.assertFalse((candidate / ".env").exists())
        self.assertEqual(self.workspace.changed_files(), ["main.py"])

    def test_repository_map_counts_files_without_secret(self) -> None:
        result = self.workspace.repository_map(self.source)
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["test_files"], 1)

    def test_apply_requires_checks_and_explicit_approval(self) -> None:
        state = self.workspace.create_candidate(self.source)
        candidate = Path(state["candidate"])
        (candidate / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.workspace.apply_candidate(approved=False)
        with self.assertRaises(RuntimeError):
            self.workspace.apply_candidate(approved=True)
        result = self.workspace.run_checks()
        self.assertTrue(result["passed"])
        self.workspace.apply_candidate(approved=True)
        self.assertEqual((self.source / "main.py").read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_apply_refuses_when_source_changed_after_snapshot(self) -> None:
        state = self.workspace.create_candidate(self.source)
        candidate = Path(state["candidate"])
        (candidate / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.workspace.run_checks()
        (self.source / "main.py").write_text("VALUE = 3\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.workspace.apply_candidate(approved=True)

    def test_verified_apply_can_be_rolled_back(self) -> None:
        state = self.workspace.create_candidate(self.source)
        candidate = Path(state["candidate"])
        (candidate / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.workspace.run_checks()
        self.workspace.apply_candidate(approved=True)
        restored = self.workspace.rollback_last()
        self.assertEqual(restored, ["main.py"])
        self.assertEqual((self.source / "main.py").read_text(encoding="utf-8"), "VALUE = 1\n")


if __name__ == "__main__":
    unittest.main()
