from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codeatlas import analyze_project


class AnalyzerTests(unittest.TestCase):
    def test_reports_python_structure(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "example.py").write_text(
                "class Greeter:\n    def hello(self):\n        return 'hi'\n# TODO: add goodbye\n",
                encoding="utf-8",
            )
            report = analyze_project(root)
            self.assertEqual(len(report.files), 1)
            self.assertEqual(report.files[0].classes, ["Greeter"])
            self.assertEqual(report.files[0].functions, ["hello"])
            self.assertEqual(report.files[0].todos, [4])


if __name__ == "__main__":
    unittest.main()
