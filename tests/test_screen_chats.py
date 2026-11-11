"""1.20.0: Claude drives screen control, follow-ups stay with Claude, chats (new/past), phone voice endpoints."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from forgemind.agent import needs_tools
from forgemind.brain import Brain
from forgemind.config import Settings
from forgemind.database import MemoryDB as Database
from forgemind.phone_bridge import PhoneAccess, PhoneServer
from forgemind.screen_agent import ClaudeScreenEngine, ScreenJob
from test_phone_access import FakeDelegate


class FakeClaude:
    loaded = True

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    @staticmethod
    def vision_message(text, image_b64, media_type="image/jpeg"):
        return {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                                          "data": image_b64}}, {"type": "text", "text": text}]}

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000):
        self.prompts.append(messages[0]["content"][1]["text"])
        yield self.replies.pop(0)


class FakeBackend:
    def __init__(self, controls, rect=None):
        self.controls, self.done = controls, []

    def capture(self, path):
        Path(path).write_bytes(b"\x89PNG fake")
        return (1280, 720)

    def fingerprint(self, path, size):
        return str(len(self.done))

    def execute(self, action, size):
        self.done.append(action)

    def release(self):
        pass


class NoLease:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ScreenTests(unittest.TestCase):
    def test_claude_drives_the_screen_task_to_done(self):
        claude = FakeClaude([
            'Sure: {"action":"click","x":400,"y":300,"reason":"focus the ChatGPT box"}',
            '{"action":"type","text":"Higgsfield connected, but no subscription.","reason":"write"}',
            '{"action":"press","key":"enter","reason":"send"}',
            '{"action":"done","evidence":"message visible"}',
            '{"completed":true,"evidence":"The reply shows in the ChatGPT thread"}',
        ])
        done = threading.Event()
        backends = []

        def backend(controls, rect):
            backends.append(FakeBackend(controls, rect))
            return backends[-1]
        job = ScreenJob(claude, on_done=lambda j: done.set(), backend_factory=backend, lease_factory=NoLease, listen=False)
        job.start("In ChatGPT, reply that Higgsfield is connected but no subscription, and send it")
        self.assertTrue(done.wait(10))
        self.assertEqual(job.result["status"], "completed")
        self.assertEqual([a["action"] for a in backends[0].done], ["click", "type", "press"])
        self.assertIn("Done on your laptop screen", job.report())
        self.assertIn("Owner task:", claude.prompts[0])

    def test_engine_rejects_non_json_and_needs_claude(self):
        engine = ClaudeScreenEngine(FakeClaude(["I can't help with that."]))
        with tempfile.TemporaryDirectory() as folder:
            shot = Path(folder) / "s.png"
            shot.write_bytes(b"png")
            with self.assertRaises(ValueError):
                engine.ask(shot, "next action")
        job = ScreenJob(SimpleNamespace(loaded=False))
        with self.assertRaises(ValueError):
            job.start("click it")


class FollowUpRoutingTests(unittest.TestCase):
    def test_follow_up_stays_with_claude_after_a_tool_answer(self):
        local = SimpleNamespace(loaded=True)
        claude = SimpleNamespace(loaded=True, provider_id="claude", display_name="Claude")
        brain = Brain(local, SimpleNamespace(loaded=False), claude)
        brain.tools = object()
        settings = Settings()
        self.assertIs(brain.pick("ya no im not home", settings)[0], local)
        brain._agent_at = time.monotonic()
        chosen, _text, why = brain.pick("ya no im not home", settings)
        self.assertIs(chosen, claude)
        self.assertIn("follow-up", why)
        self.assertTrue(needs_tools("click the button in chatgpt"))


class ChatTests(unittest.TestCase):
    def test_new_chat_past_chats_and_context(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "m.sqlite3")
            self.assertFalse(db.new_chat())  # nothing to close yet
            db.add_message("user", "find winning products")
            db.add_message("assistant", "Here are 6")
            self.assertTrue(db.new_chat())
            self.assertFalse(db.new_chat())  # no empty chats
            self.assertEqual(db.recent_messages(10), [])
            db.add_message("user", "contest my ticket")
            self.assertEqual([m["content"] for m in db.recent_messages(10)], ["contest my ticket"])
            chats = db.chats()
            self.assertEqual([c["title"] for c in chats], ["contest my ticket", "find winning products"])
            old = chats[1]
            self.assertEqual([m["content"] for m in db.chat_messages(old["id"])], ["find winning products", "Here are 6"])
            self.assertEqual([m["content"] for m in db.chat_messages(chats[0]["id"])], ["contest my ticket"])


class PhoneVoiceChatRoutes(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.access = PhoneAccess(Path(self.folder.name) / "phone.json")
        self.key = self.access.new_key()
        d = FakeDelegate()
        d.transcribe = lambda audio, mime: {"text": f"{len(audio)}:{mime}"}
        d.speak = lambda text: {"id": "abc"}
        d.speech = lambda key: b"ID3mp3" if key == "abc" else (_ for _ in ()).throw(KeyError(key))
        d.new_chat = lambda: {"ok": True, "started": True}
        d.chats = lambda: {"chats": [{"id": 3, "title": "hi", "updated": "", "count": 2}]}
        d.chat_history = lambda chat_id: {"messages": [{"role": "user", "content": f"chat {chat_id}"}]}
        self.server = PhoneServer(d, self.access)
        self.base = f"http://127.0.0.1:{self.server.start(port=0)}"

    def tearDown(self):
        self.server.stop()
        self.folder.cleanup()

    def call(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET",
                                         headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_routes(self):
        big = "A" * 200_000  # a recording is far bigger than a chat message
        status, _, body = self.call("/api/transcribe", {"audio": big, "mime": "audio/mp4"})
        self.assertEqual((status, json.loads(body)["text"]), (200, "200000:audio/mp4"))
        self.assertEqual(json.loads(self.call("/api/speak", {"text": "hola"})[2])["id"], "abc")
        status, headers, body = self.call("/api/speak/abc")
        self.assertEqual((status, headers["Content-Type"], body), (200, "audio/mpeg", b"ID3mp3"))
        self.assertTrue(json.loads(self.call("/api/chats/new", {})[2])["started"])
        self.assertEqual(json.loads(self.call("/api/chats")[2])["chats"][0]["title"], "hi")
        self.assertEqual(json.loads(self.call("/api/chats/3")[2])["messages"][0]["content"], "chat 3")
        self.assertEqual(self.call("/api/chat", {"message": "x" * 40_000})[0], 413)  # chat keeps its small limit


if __name__ == "__main__":
    unittest.main()
