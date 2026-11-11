import os
import queue
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from forgemind import reels, whisper_listen
from forgemind.config import Settings
from forgemind.phone_delegate import AppPhoneDelegate

REEL = "https://www.instagram.com/reel/C9xYz12AbCd/?igsh=abc123"


class LinkTests(unittest.TestCase):
    def test_finds_short_video_links(self):
        text = (f"check these {REEL} and https://instagram.com/p/AbC-12_x/ plus "
                "https://www.tiktok.com/@chef.ana/video/7311111111111111111 https://youtube.com/shorts/dQw4w9WgXcQ.")
        self.assertEqual(reels.reel_links(text), [REEL, "https://instagram.com/p/AbC-12_x/",
                                                  "https://www.tiktok.com/@chef.ana/video/7311111111111111111",
                                                  "https://youtube.com/shorts/dQw4w9WgXcQ"])

    def test_no_cap_on_how_many_links(self):
        many = " ".join(f"https://www.instagram.com/reel/Reel{n:03d}/" for n in range(25))
        self.assertEqual(len(reels.reel_links(many)), 25)
        self.assertEqual(reels.reel_links("https://vm.tiktok.com/ZMabc123/"), ["https://vm.tiktok.com/ZMabc123/"])
        self.assertEqual(reels.reel_links(f"{REEL} {REEL}"), [REEL])

    def test_other_links_are_not_reels(self):
        for text in ["https://www.instagram.com/davidsinsurance/", "https://youtube.com/watch?v=abc",
                     "https://crm.example.com/dashboard", "what's a reel?", ""]:
            self.assertEqual(reels.reel_links(text), [], text)

    def test_question_besides_the_link(self):
        self.assertEqual(reels.question_about(f"convert this reel to mp4 {REEL}"), "")
        self.assertEqual(reels.question_about(f"can you transcribe these {REEL} please"), "")
        self.assertEqual(reels.question_about(f"{REEL} what recipe is she making and how long does it bake?"),
                         "what recipe is she making and how long does it bake?")


class DownloadTests(unittest.TestCase):
    def fake_ydl(self, info=None, error=None, folder=None):
        class FakeYDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download):
                if error:
                    raise Exception(error)
                path = Path(folder) / "instagram-C9xYz12AbCd.mp4"
                path.write_bytes(b"video")
                return {**(info or {}), "requested_downloads": [{"filepath": str(path)}]}
        return FakeYDL

    def test_download_saves_mp4_without_cookies(self):
        with tempfile.TemporaryDirectory() as folder:
            seen = {}

            class Spy(self.fake_ydl(folder=folder)):
                def __init__(inner, options):
                    seen.update(options)
                    super().__init__(options)
            path, info = reels.download(REEL, Path(folder), ydl_factory=Spy)
            self.assertTrue(path.is_file())
            self.assertEqual(seen["merge_output_format"], "mp4")
            self.assertNotIn("cookiefile", seen)
            self.assertNotIn("cookiesfrombrowser", seen)
            self.assertTrue(seen["noplaylist"])

    def test_errors_become_plain_messages(self):
        cases = {"ERROR: [Instagram] C9x: Requested content is not available, rate-limit reached or login required":
                 "signed-in account", "ERROR: Unsupported URL: https://x": "no video",
                 "ERROR: HTTP Error 404: Not Found": "404"}
        with tempfile.TemporaryDirectory() as folder:
            for raw, words in cases.items():
                with self.assertRaises(reels.ReelError) as caught:
                    reels.download(REEL, Path(folder), ydl_factory=self.fake_ydl(error=raw, folder=folder))
                self.assertIn(words, str(caught.exception))


def model_cached():
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return any(hub.glob("models--Systran--faster-whisper-base.en*"))


@unittest.skipUnless(os.name == "nt" and whisper_listen.available() and model_cached(),
                     "needs Windows speech, faster-whisper and the cached base.en model")
class ProcessTests(unittest.TestCase):
    """Real media library + Whisper + frames on a locally made MP4 (only the download is faked)."""

    def test_video_is_transcribed_and_framed(self):
        import imageio_ffmpeg
        from forgemind.media import MediaLibrary
        from tests.test_whisper_voice import synthesize
        with tempfile.TemporaryDirectory() as folder:
            wav, mp4 = Path(folder) / "voice.wav", Path(folder) / "instagram-C9xYz12AbCd.mp4"
            synthesize("Preheat the oven to three hundred and fifty degrees and bake for twenty minutes", wav)
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
                            "color=c=orange:s=320x568:d=6", "-i", str(wav), "-shortest", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(mp4)], check=True, timeout=120)
            library = MediaLibrary(root=Path(folder) / "media")
            steps = []
            result = reels.process(REEL, library, progress=steps.append,
                                   downloader=lambda url: (mp4, {"uploader": "chef.ana", "duration": 6.0,
                                                                 "description": "Easy weeknight bake"}))
            self.assertIn("oven", result["transcript"].lower())
            self.assertIn("20", result["transcript"].replace("twenty", "20"))
            self.assertGreaterEqual(len(result["frames"]), 1)
            summary = reels.chat_summary(result)
            self.assertIn("by chef.ana, 6 s", summary)
            self.assertIn("Caption: Easy weeknight bake", summary)
            self.assertIn(str(mp4), summary)
            self.assertEqual(steps[:2], ["Downloading the video…", "Transcribing it on this PC…"])


class RoutingTests(unittest.TestCase):
    def test_phone_link_is_handled_on_the_pc_without_the_model(self):
        class Inference:
            def stream(self, *args, **kwargs):
                raise AssertionError("reel links must not go to the model")
        app = SimpleNamespace(db=SimpleNamespace(recent_messages=lambda n: [], add_message=lambda *a: None),
                              engine=SimpleNamespace(loaded=True), inference=Inference(), events=queue.Queue(),
                              settings_data=Settings(auto_research=False))
        result = AppPhoneDelegate(app).chat(f"transcribe this {REEL}")
        self.assertIn("transcript", result["reply"])
        kind, callback = app.events.get_nowait()
        self.assertEqual(kind, "ui")

    def test_desktop_posts_each_transcript_and_then_answers_the_question(self):
        from app import ForgeMindApp
        posted, events = [], queue.Queue()
        fake = SimpleNamespace(
            db=SimpleNamespace(add_message=lambda role, text: posted.append((role, text))),
            events=events, media_library=object(), _append=lambda *a: None, refresh_all=lambda: None,
            _set_status=lambda *a: None)
        fake._post_reel = lambda reply: ForgeMindApp._post_reel(fake, reply)
        asked = []
        fake._ask_about_reels = lambda question: asked.append(question)
        results = {REEL: {"path": "C:/x.mp4", "transcript": "bake for twenty minutes", "uploader": "chef.ana"}}

        def fake_process(url, library, progress=None):
            if url in results:
                return {"caption": "", "frames": [], "duration": 6, **results[url]}
            raise reels.ReelError("That video needs a signed-in account to watch")
        original = reels.process
        reels.process = fake_process
        try:
            ForgeMindApp.start_reels(fake, f"{REEL} https://instagram.com/reel/PRIVATE1/ how long does it bake?",
                                     reels.reel_links(f"{REEL} https://instagram.com/reel/PRIVATE1/"))
            callbacks = [events.get(timeout=5) for _ in range(3)]
        finally:
            reels.process = original
        for kind, callback in callbacks:
            self.assertEqual(kind, "ui")
            callback()
        texts = [text for role, text in posted if role == "assistant"]
        self.assertIn("Getting 2 videos now", texts[0])
        self.assertIn("Transcript: bake for twenty minutes", texts[1])
        self.assertIn("signed-in account", texts[2])
        self.assertEqual(asked, ["how long does it bake?"])


if __name__ == "__main__":
    unittest.main()


class LocalFileTests(unittest.TestCase):
    def test_finds_existing_media_files_in_a_message(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "SaveInta.com_AQN abc.mp4"
            b = Path(folder) / "WhatsApp Video 2026-11-03 at 11.04.11 PM.mp4"
            for path in (a, b):
                path.write_bytes(b"x")
            message = f'@"{a}" @"{b}"\nget all these transcripted and tell me which one is a scam'
            self.assertEqual(reels.local_media(message), [str(a), str(b)])
            self.assertEqual(reels.local_media(f"transcribe {b}"), [str(b)])
            self.assertEqual(reels.question_about(message),
                             "get all these transcripted and tell me which one is a scam")
            self.assertEqual(reels.question_about(f'transcribe "{a}" please'), "")
        self.assertEqual(reels.local_media(r"C:\nope\missing.mp4"), [])
        self.assertTrue(reels.is_local(r"C:\x.mp4"))
        self.assertFalse(reels.is_local(REEL))

    def test_local_file_is_not_downloaded(self):
        def never(url):
            raise AssertionError("local files must not be downloaded")

        class Library:
            def add(self, path):
                return {"id": "m1"}

            def transcribe(self, media_id, model_name):
                raise RuntimeError("no model in this test")

            def sample_video_frames(self, media_id, maximum):
                return []
        result = reels.process(r"C:\videos\clip.mp4", Library(), downloader=never)
        self.assertTrue(result["local"])
        self.assertTrue(reels.chat_summary(result).startswith("Video clip.mp4"))


class FollowUpTests(unittest.TestCase):
    """the owner pasted links, Doxa (then without reels) said it couldn't, and he replied without the links."""
    LINKS = ("https://www.instagram.com/reel/DdjPyXlxmk2/?srtk=MWV2bjVzcWtoY240Yw==\n"
             "https://www.instagram.com/p/DfC8E_pAZYw/?psln=MTk2Ymd6ZHpxbzdydQ==\n"
             "https://www.instagram.com/reel/DfVNFjGMDGf/?vrfl=YWs0MzJwMjFoa2t0")

    def history(self, *extra):
        return [{"role": "user", "content": self.LINKS},
                {"role": "assistant", "content": "I cannot open or view Instagram links directly."}, *extra]

    def test_follow_ups_use_the_earlier_links(self):
        for text in ["no download them noo download them", "can you convert those to mp4",
                     "transcribe them please", "download the reels", "convert it to mp4", "get me the transcripts"]:
            self.assertEqual(len(reels.links_from_history(text, self.history())), 3, text)

    def test_unrelated_or_negative_messages_do_not(self):
        for text in ["what time is it", "can you?", "open my calendar", "no, don't download them",
                     "get me a quote for Ana", ""]:
            self.assertEqual(reels.links_from_history(text, self.history()), [], text)
        self.assertEqual(reels.links_from_history("download them", []), [])
        self.assertEqual(reels.links_from_history("download them", [{"role": "assistant", "content": self.LINKS}]), [])

    def test_uses_the_most_recent_links(self):
        newer = {"role": "user", "content": "https://www.tiktok.com/@chef.ana/video/7311111111111111111"}
        self.assertEqual(reels.links_from_history("download it", self.history(newer)),
                         ["https://www.tiktok.com/@chef.ana/video/7311111111111111111"])

    def test_short_links_and_share_links_are_recognized(self):
        self.assertEqual(len(reels.reel_links("https://instagr.am/reel/AbC123/ and "
                                              "https://www.instagram.com/share/reel/BAxyz123/")), 2)

    def test_mp4s_go_where_the_owner_can_find_them(self):
        folder = reels.default_folder()
        if (Path.home() / "Downloads").is_dir():
            self.assertEqual(folder, Path.home() / "Downloads" / "Doxa reels")

    def test_desktop_routes_a_follow_up_to_the_reel_pipeline(self):
        from app import ForgeMindApp
        started = []
        text = "no download them noo download them"
        fake = SimpleNamespace(_voice_dispatch=False, _voice_turn=False, busy=False,
                               input=SimpleNamespace(get=lambda *a: text, delete=lambda *a: None),
                               db=SimpleNamespace(recent_messages=lambda n: self.history()),
                               start_reels=lambda t, links: started.append((t, links)))
        from unittest import mock
        with mock.patch("app.parse_command", return_value=None):
            ForgeMindApp.send(fake)
        self.assertEqual(len(started), 1)
        self.assertEqual(len(started[0][1]), 3)


class PromptTests(unittest.TestCase):
    def test_model_is_told_it_can_handle_reel_links(self):
        from forgemind.config import CHAT_CORE_PROMPT
        self.assertIn("Never say you cannot open, download, convert", CHAT_CORE_PROMPT)
        self.assertIn(r"Downloads\Doxa reels", CHAT_CORE_PROMPT)
