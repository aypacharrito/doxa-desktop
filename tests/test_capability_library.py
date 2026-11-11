from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from forgemind.capability_library import relevant_playbooks


class CapabilityLibraryTests(unittest.TestCase):
    def test_goal_relevant_playbook_is_selected(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            (root / "01_REASONING_PLAYBOOK.md").write_text("general reasoning", encoding="utf-8")
            (root / "VOICE.md").write_text(
                "voice transcription microphone audio whisper speech", encoding="utf-8"
            )
            (root / "DATABASE.md").write_text("postgres indexes transactions", encoding="utf-8")
            result = relevant_playbooks(root, "Add microphone voice transcription", max_files=2)
            self.assertIn("VOICE.md", result)
            self.assertNotIn("DATABASE.md", result)

    def test_playbook_output_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            (root / "LARGE.md").write_text("voice " * 5000, encoding="utf-8")
            result = relevant_playbooks(root, "voice", max_chars=500)
            self.assertLessEqual(len(result), 500)


if __name__ == "__main__":
    unittest.main()
