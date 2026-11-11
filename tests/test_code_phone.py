"""1.18.0: Code mode from the phone, follow-ups in the same Codex / Claude Code chat, plans instead of API keys,
"ask codex to …" phrasing, and the live screen view."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from forgemind import code_mode
from forgemind.code_mode import CodeRunner, code_request
from forgemind.phone_bridge import PhoneAccess, PhoneServer
from forgemind.phone_delegate import AppPhoneDelegate
from test_code_mode import CLAUDE_LINES, CODEX_LINES, FakeProcess
from test_phone_access import FakeDelegate


class AskPhrasingTests(unittest.TestCase):
    def test_ask_codex_and_claude(self):
        self.assertEqual(code_request("ask codex to fix the login bug"), ("codex", "fix the login bug"))
        self.assertEqual(code_request("Hey Doxa, ask Codex to fix a bug in C:\\proj"), ("codex", "fix a bug in C:\\proj"))
        self.assertEqual(code_request("tell claude code to add dark mode"), ("claude", "add dark mode"))
        self.assertEqual(code_request("ask Claude desktop to fix this"), ("claude", "fix this"))
        self.assertEqual(code_request("have claude build me a landing page"), ("claude", "build me a landing page"))
        self.assertEqual(code_request("use code mode to rename my photos"), ("auto", "rename my photos"))

    def test_plain_claude_questions_stay_chat(self):
        for text in ("ask claude what the capital of Peru is", "ask Claude about my schedule", "tell claude hi"):
            self.assertIsNone(code_request(text), text)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.calls = []
        self.patch = mock.patch.object(code_mode, "WORK_ROOT", self.root / "Doxa Code")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def runner(self, lines_by_call, signed_in=False, budget=None):
        def popen(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return FakeProcess(lines_by_call[min(len(self.calls), len(lines_by_call)) - 1])
        runner = CodeRunner(self.root, claude_key=lambda: "sk-ant-test", budget=budget, popen=popen,
                            finders={"codex": lambda: "C:/codex.exe", "claude": lambda: "C:/claude.exe"})
        runner.claude_signed_in = lambda exe: signed_in
        return runner

    def run_job(self, runner, task, **kwargs):
        done = threading.Event()
        job = runner.start(task, on_done=lambda j: done.set(), **kwargs)
        self.assertTrue(done.wait(5))
        return job

    def test_codex_follow_up_resumes_same_thread_and_folder(self):
        first = [json.dumps({"type": "thread.started", "thread_id": "thread-123"})] + CODEX_LINES[1:]
        runner = self.runner([first, CODEX_LINES])
        job = self.run_job(runner, "build a todo app", engine="codex")
        self.assertEqual(job.session_id, "thread-123")
        again = self.run_job(runner, "also add dark mode")  # automatic: same agent, same chat
        argv, kwargs = self.calls[1]
        self.assertEqual(argv[1:3], ["exec", "resume"])
        self.assertIn("thread-123", argv)
        self.assertEqual(kwargs["cwd"], str(job.folder))
        self.assertTrue(again.continued)
        self.assertIn("continued your Codex chat", again.report())

    def test_new_chat_and_other_folder_start_fresh(self):
        first = [json.dumps({"type": "thread.started", "thread_id": "t1"})] + CODEX_LINES[1:]
        runner = self.runner([first])
        self.run_job(runner, "build a todo app", engine="codex")
        self.run_job(runner, "new chat: make a game", engine="codex")
        self.assertNotIn("resume", self.calls[1][0])
        self.run_job(runner, "fix it", engine="codex", follow_up=False)
        self.assertNotIn("resume", self.calls[2][0])

    def test_claude_plan_is_used_when_signed_in(self):
        from forgemind.cloud_brain import CloudBudget
        budget = CloudBudget(self.root / "c.sqlite3", 2000)
        init = json.dumps({"type": "system", "subtype": "init", "session_id": "sess-9"})
        runner = self.runner([[init] + CLAUDE_LINES[1:], CLAUDE_LINES], signed_in=True, budget=budget)
        job = self.run_job(runner, "fix the bug", engine="claude")
        argv, kwargs = self.calls[0]
        self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
        self.assertNotIn("--max-budget-usd", argv)
        self.assertTrue(job.subscription)
        self.assertEqual(budget.summary()["reserved_cents"], 0)  # the plan, not Doxa's API budget
        self.assertNotIn("of Claude's budget", job.report())
        self.run_job(runner, "now add tests")
        self.assertEqual(self.calls[1][0][-2:], ["--resume", "sess-9"])

    def test_state_for_phone(self):
        runner = self.runner([CODEX_LINES])
        self.assertEqual(runner.state()["job"], None)
        self.run_job(runner, "build it", engine="codex")
        state = runner.state()
        self.assertFalse(state["running"])
        self.assertEqual(state["job"]["status"], "done")
        self.assertIn("Codex: Built app.py", "\n".join(state["job"]["steps"]))
        self.assertIn("codex", state["engines"])


class PhoneRouteTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.access = PhoneAccess(Path(self.folder.name) / "phone.json")
        self.key = self.access.new_key()
        self.delegate = FakeDelegate()
        self.delegate.code_state = lambda: {"running": True, "job": {"status": "running"}, "engines": {"codex": "Codex"}}
        self.delegate.code_start = lambda task, engine, fresh: {"ok": True, "note": f"{task}|{engine}|{fresh}"}
        self.delegate.code_stop = lambda: {"ok": True}
        self.delegate.screen_jpeg = lambda width: b"\xff\xd8JPEG" + str(width).encode()
        self.server = PhoneServer(self.delegate, self.access)
        self.base = f"http://127.0.0.1:{self.server.start(port=0)}"

    def tearDown(self):
        self.server.stop()
        self.folder.cleanup()

    def call(self, path, body=None, key=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET",
                                         headers={"Authorization": f"Bearer {self.key if key is None else key}",
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_code_routes(self):
        self.assertTrue(json.loads(self.call("/api/code")[2])["running"])
        status, _, body = self.call("/api/code/start", {"task": "fix it", "engine": "codex", "fresh": True})
        self.assertEqual((status, json.loads(body)["note"]), (200, "fix it|codex|True"))
        self.assertEqual(self.call("/api/code/stop", {})[0], 200)

    def test_screen_needs_key_and_returns_jpeg(self):
        self.assertEqual(self.call("/api/screen?w=800", key="wrong")[0], 401)
        status, headers, body = self.call("/api/screen?w=800")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(body, b"\xff\xd8JPEG800")
        self.assertIn("blob:", headers.get("Content-Security-Policy", "") or
                      self.call("/api/status")[1]["Content-Security-Policy"])


class DelegateTests(unittest.TestCase):
    def test_code_start_runs_on_window_thread_and_reports_errors(self):
        calls = []

        class Events:
            def put(self, item):
                item[1]()

        def start(text, task, folder, engine, source="", follow_up=None):
            calls.append((task, engine, follow_up, source))
            if task == "bad":
                raise ValueError("Code mode is already working")
            return "Code mode started with Codex"
        app = SimpleNamespace(events=Events(), start_code_job=start, code_runner=None)
        delegate = AppPhoneDelegate(app)
        self.assertEqual(delegate.code_start("fix it", "codex", fresh=True)["note"], "Code mode started with Codex")
        self.assertEqual(calls[0], ("fix it", "codex", False, "YOU · PHONE"))
        from forgemind.phone_bridge import PhoneError
        with self.assertRaises(PhoneError):
            delegate.code_start("bad")
        with self.assertRaises(PhoneError):
            delegate.code_start("x", "gpt")
        self.assertEqual(delegate.code_state()["job"], None)

    def test_screen_picture_is_resized_jpeg(self):
        from PIL import Image
        with mock.patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (2560, 1440), "navy")):
            data = AppPhoneDelegate(SimpleNamespace()).screen_jpeg(800)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        import io
        self.assertEqual(Image.open(io.BytesIO(data)).size, (800, 450))


if __name__ == "__main__":
    unittest.main()
