from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from forgemind.clips import ClipStudio, captions, timestamp
from forgemind.media import MediaLibrary
from forgemind.youtube import YouTubePublisher


class ClipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.library = MediaLibrary(self.root / "media")
        source = self.root / "obs.mp4"
        source.write_bytes(b"original-video")
        self.record = self.library.add(source)
        self.record["metadata"]["duration_seconds"] = 100
        self.library._save(self.record)
        self.studio = ClipStudio(self.library, self.root / "clips")

    def tearDown(self):
        self.temp.cleanup()

    def test_timestamps_and_invalid_nonfinite_values(self):
        self.assertEqual(timestamp("1:02:03.5"), 3723.5)
        for value in ("nan", "inf", "-1", "1:2:3:4"):
            with self.assertRaises(ValueError):
                timestamp(value)

    def test_captions_are_shifted_and_clamped_to_clip(self):
        text = "[1.00–4.00] hello\n[5.00–8.00] world\n[20.00–21.00] excluded"
        result = captions(text, 2, 6)
        self.assertIn("00:00:00,000 --> 00:00:02,000", result)
        self.assertIn("00:00:03,000 --> 00:00:04,000", result)
        self.assertNotIn("excluded", result)

    def test_plan_rejects_invalid_ranges_and_keeps_source(self):
        for a, b in ((-1, 30), (30, 20), (0, 181), (90, 110), (float("nan"), 20)):
            with self.assertRaises(ValueError):
                self.studio.plan(self.record["id"], a, b, "Highlight")
        job = self.studio.plan(self.record["id"], 5, 35, "Highlight")
        self.assertEqual(self.studio.jobs()[0]["id"], job["id"])
        self.assertEqual(Path(self.record["source"]).read_bytes(), b"original-video")

    def test_suggestions_reject_hallucinated_times_and_overlap(self):
        transcript = self.root / "transcript.md"
        transcript.write_text("[0.00–30.00] opening\n[30.00–60.00] ending", encoding="utf-8")
        self.record["transcript"] = str(transcript)
        self.library._save(self.record)
        response = {"clips": [{"start": 0, "end": 30, "title": "Good"},
                              {"start": 10, "end": 40, "title": "Duplicate"},
                              {"start": 70, "end": 90, "title": "Invented"}]}
        result = self.studio.suggest(self.record["id"], lambda *_a, **_k: response)
        self.assertEqual([item["title"] for item in result], ["Good"])

    def test_stale_queue_action_cannot_requeue_or_cancel_an_upload(self):
        job = self.studio.plan(self.record["id"], 5, 35, "Highlight")
        job["status"] = "rendered"
        self.studio.save(job)
        self.studio.transition(job["id"], "rendered", "upload_queued", youtube_visibility="private")
        self.studio.transition(job["id"], "upload_queued", "uploading")
        for expected, target in (("rendered", "upload_queued"), ("upload_queued", "rendered")):
            with self.assertRaises(ValueError):
                self.studio.transition(job["id"], expected, target)

    def test_upload_uses_requested_visibility_and_records_real_id(self):
        service = MagicMock()
        request = service.videos.return_value.insert.return_value
        request.next_chunk.return_value = (None, {"id": "real-video", "status": {"privacyStatus": "unlisted"}})
        with patch.dict("sys.modules", {
            "googleapiclient.discovery": SimpleNamespace(build=MagicMock(return_value=service)),
            "googleapiclient.http": SimpleNamespace(MediaFileUpload=MagicMock()),
        }), patch.object(YouTubePublisher, "_credentials", return_value=object()):
            result = YouTubePublisher().upload(Path(self.record["source"]), "Highlight", privacy="unlisted")
        payload = service.videos.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(payload["status"]["privacyStatus"], "unlisted")
        self.assertEqual(result["video_id"], "real-video")
        service.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
