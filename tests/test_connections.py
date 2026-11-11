from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from forgemind.connections import _extract_repository, parse_github_repository


class ConnectionTests(unittest.TestCase):
    def test_github_repository_url_is_parsed(self) -> None:
        self.assertEqual(
            parse_github_repository("https://github.com/openai/openai-python.git"),
            ("openai", "openai-python"),
        )
        with self.assertRaises(ValueError):
            parse_github_repository("https://example.com/not-github")

    def test_repository_archive_is_extracted_without_wrapper_folder(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            archive = root / "repo.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("project-main/src/app.py", "print('hello')\n")
            destination = root / "snapshot"
            _extract_repository(archive, destination)
            self.assertTrue((destination / "src" / "app.py").is_file())

    def test_repository_archive_cannot_escape_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("project-main/../../outside.txt", "no")
            with self.assertRaises(ValueError):
                _extract_repository(archive, root / "snapshot")


if __name__ == "__main__":
    unittest.main()
