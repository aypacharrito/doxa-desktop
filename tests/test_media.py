from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from forgemind.media import MediaLibrary


class MediaLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.library = MediaLibrary(self.root / "media")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_media_types(self) -> None:
        self.assertEqual(self.library.media_type(Path("screen.png")), "image")
        self.assertEqual(self.library.media_type(Path("voice.wav")), "audio")
        self.assertEqual(self.library.media_type(Path("obs.mkv")), "video")
        with self.assertRaises(ValueError):
            self.library.media_type(Path("unknown.exe"))

    def test_add_keeps_source_read_only_and_deduplicates(self) -> None:
        source = self.root / "screen.png"
        source.write_bytes(b"not-a-real-png")
        before = source.read_bytes()
        first = self.library.add(source)
        second = self.library.add(source)
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(first["read_only_source"])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(len(self.library.list_records()), 1)

    def test_transcript_is_timestamped_and_searchable(self) -> None:
        source = self.root / "recording.wav"
        source.write_bytes(b"fake-wave")
        record = self.library.add(source)

        class FakeModel:
            def __init__(self, *_args, **_kwargs):
                pass

            def transcribe(self, *_args, **_kwargs):
                segment = types.SimpleNamespace(start=1.25, end=3.5, text=" Build the Roblox map.")
                return iter([segment]), types.SimpleNamespace(language="en")

        fake_module = types.SimpleNamespace(WhisperModel=FakeModel)
        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            transcript = self.library.transcribe(record["id"])
        text = transcript.read_text(encoding="utf-8")
        self.assertIn("[1.25–3.50] Build the Roblox map.", text)
        knowledge = self.library.knowledge_document(record["id"]).read_text(encoding="utf-8")
        self.assertIn("Build the Roblox map", knowledge)

    def test_transcription_recovers_from_pyav_metadata_incompatibility(self):
        import imageio_ffmpeg
        import numpy
        source = self.root / "recording.wav"
        source.write_bytes(b"fake-wave")
        record = self.library.add(source)
        calls = []
        class FakeModel:
            def __init__(self, *args, **kwargs): pass
            def transcribe(self, audio, **kwargs):
                calls.append(audio)
                if isinstance(audio, str):
                    raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
                return iter([types.SimpleNamespace(start=0,end=1,text="Recovered locally")]), types.SimpleNamespace(language="en")
        with patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg.exe"), patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=FakeModel)}), patch("forgemind.media.subprocess.check_output", return_value=b'\0'*16) as decode:
            result = self.library.transcribe(record["id"])
        self.assertIn("Recovered locally", result.read_text(encoding="utf-8"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(decode.call_args.kwargs['timeout'], 300)

    def test_ocr_result_is_saved_to_knowledge(self) -> None:
        source = self.root / "bug.png"
        source.write_bytes(b"fake-image")
        record = self.library.add(source)
        completed = types.SimpleNamespace(returncode=0, stdout="Error: missing module", stderr="")
        with patch("forgemind.media.shutil.which", return_value="tesseract.exe"), patch(
            "forgemind.media.subprocess.run", return_value=completed
        ):
            self.library.ocr_image(record["id"])
        knowledge = self.library.knowledge_document(record["id"]).read_text(encoding="utf-8")
        self.assertIn("Error: missing module", knowledge)


if __name__ == "__main__":
    unittest.main()

