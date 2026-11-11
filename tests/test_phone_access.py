"""Phone access: shared browser controller, phone server security, delegate routing, tunnel URL detection."""
from __future__ import annotations

import json
import queue
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from forgemind.browser_agent import Element, Snapshot
from forgemind.browser_control import BrowserController
from forgemind.phone_bridge import PhoneAccess, PhoneError, PhoneServer, Tunnel, phone_link
from forgemind.phone_delegate import AppPhoneDelegate


def wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeSession:
    def __init__(self, snapshot):
        self.snap, self.clicked, self.opened, self.closed = snapshot, [], False, False
        self.thread = None

    def open(self):
        self.opened, self.thread = True, threading.current_thread()

    def snapshot(self):
        return self.snap

    def click(self, element):
        self.clicked.append(element.id)

    def fill(self, *_):
        pass

    def screenshot(self, _):
        pass

    def close(self):
        self.closed = threading.current_thread() is self.thread


def scripted(actions):
    actions = list(actions)
    return lambda prompt: actions.pop(0) if actions else {"action": "done", "summary": "finished"}


class ControllerTests(unittest.TestCase):
    def make(self, actions, snap=None):
        snap = snap or Snapshot("https://x.test", "Form", "", [Element(1, "button", "", "submit", "Book appointment")])
        session = FakeSession(snap)
        results = []
        controller = BrowserController(lambda: session, lambda: scripted(actions), on_finish=results.append)
        return controller, session, results

    def test_question_answered_from_either_screen(self):
        controller, session, results = self.make([{"action": "ask_owner", "question": "Your phone number?"}])
        controller.start("book it")
        self.assertTrue(wait_until(lambda: controller.state()["pending"]))
        pending = controller.state()["pending"]
        self.assertEqual(pending["kind"], "ask")
        self.assertFalse(controller.respond("wrong-id", "x"))
        self.assertTrue(controller.respond(pending["id"], ["818-555-0100", False]))
        self.assertFalse(controller.respond(pending["id"], "again"))  # first answer wins
        controller.join(5)
        self.assertEqual(results[0]["status"], "completed")
        self.assertTrue(session.opened and session.closed)  # closed on the same thread that opened it

    def test_declined_approval_submits_nothing(self):
        controller, session, results = self.make([{"action": "click", "id": 1}])
        controller.start("book it")
        self.assertTrue(wait_until(lambda: controller.state()["pending"]))
        pending = controller.state()["pending"]
        self.assertEqual(pending["kind"], "confirm")
        self.assertIn("Book appointment", pending["title"])
        controller.respond(pending["id"], False)
        controller.join(5)
        self.assertEqual(session.clicked, [])
        self.assertEqual(results[0]["status"], "needs_input")

    def test_approval_then_click(self):
        controller, session, results = self.make([{"action": "click", "id": 1}])
        controller.start("book it")
        self.assertTrue(wait_until(lambda: controller.state()["pending"]))
        controller.respond(controller.state()["pending"]["id"], True)
        controller.join(5)
        self.assertEqual(session.clicked, [1])

    def test_stop_while_waiting_and_single_task(self):
        controller, _, results = self.make([{"action": "ask_owner", "question": "Name?"}])
        controller.start("book it")
        with self.assertRaises(RuntimeError):
            controller.start("another")
        self.assertTrue(wait_until(lambda: controller.state()["pending"]))
        controller.stop()
        controller.join(5)
        self.assertFalse(controller.running)
        self.assertIn(results[0]["status"], {"stopped", "needs_input"})
        with self.assertRaises(ValueError):
            controller.start("   ")


class FakeDelegate:
    def __init__(self):
        self.chats, self.stopped = [], False

    def status(self):
        return {"model_loaded": True, "model": "Qwen", "pc": "PC online", "browser_running": False}

    def history(self, limit):
        return [{"role": "user", "content": "hi"}]

    def chat(self, text):
        if text == "boom":
            raise PhoneError(503, "Model loading")
        self.chats.append(text)
        return {"kind": "reply", "reply": "hello from Jarvis"}

    def chat_stream(self, text):
        if text == "boom":
            raise PhoneError(503, "Model loading")

        def gen():
            for word in ["Hel", "lo ", "there"]:
                time.sleep(0.4)
                yield {"type": "token", "text": word}
            yield {"type": "done", "reply": "Hello there", "note": "Qwen"}
        return gen()

    def push_register(self, token):
        self.pushed = token
        from forgemind.phone_bridge import PUSH_TOKEN
        if not PUSH_TOKEN.fullmatch(token):
            raise PhoneError(400, "Not a valid Expo push token.")
        return {"ok": True}

    def browser_start(self, task):
        return {"ok": True}

    def browser_state(self):
        return {"running": False, "task": "", "log": [], "pending": None, "result": None, "paused": False}

    def browser_respond(self, request_id, value):
        return request_id == "good"

    def stop(self):
        self.stopped = True


class PhoneServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.access = PhoneAccess(Path(self.folder.name) / "phone.json")
        self.key = self.access.new_key()
        self.delegate = FakeDelegate()
        self.server = PhoneServer(self.delegate, self.access)
        self.port = self.server.start(port=0)
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.stop()
        self.folder.cleanup()

    def call(self, path, body=None, key=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET",
                                         headers={"Authorization": f"Bearer {self.key if key is None else key}",
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_bundled_libraries_are_cached_and_app_files_are_not(self):
        status, headers, body = self.call("/vendor/three.module.min.js")
        self.assertEqual(status, 200)
        self.assertIn("immutable", headers["Cache-Control"])   # 700 KB: the phone keeps it instead of re-downloading
        self.assertIn("javascript", headers["Content-Type"])
        self.assertGreater(len(body), 100_000)
        status, headers, _ = self.call("/hq3d.js")
        self.assertEqual((status, headers["Cache-Control"]), (200, "no-store"))  # app code always fresh after updates

    def test_listens_on_localhost_only(self):
        self.assertEqual(self.server.httpd.server_address[0], "127.0.0.1")

    def test_key_is_stored_only_as_a_hash(self):
        stored = (Path(self.folder.name) / "phone.json").read_text()
        self.assertNotIn(self.key, stored)
        self.assertTrue(self.access.check(self.key))
        self.assertFalse(self.access.check("guess"))

    def test_api_requires_key_and_locks_out_guessing(self):
        status, _, body = self.call("/api/status", key="wrong")
        self.assertEqual(status, 401)
        for _ in range(9):
            self.call("/api/status", key="wrong")
        status, _, _ = self.call("/api/status")  # even the right key is refused during lockout
        self.assertEqual(status, 429)

    def test_chat_status_history_and_stop(self):
        status, headers, body = self.call("/api/chat", {"message": "hello"})
        self.assertEqual((status, json.loads(body)["reply"]), (200, "hello from Jarvis"))
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(json.loads(self.call("/api/status")[2])["model"], "Qwen")
        self.assertEqual(json.loads(self.call("/api/history")[2])["messages"][0]["content"], "hi")
        self.assertEqual(self.call("/api/stop", {})[0], 200)
        self.assertTrue(self.delegate.stopped)

    def test_errors_and_limits(self):
        self.assertEqual(self.call("/api/chat", {"message": ""})[0], 400)
        status, _, body = self.call("/api/chat", {"message": "boom"})
        self.assertEqual((status, json.loads(body)["error"]), (503, "Model loading"))
        self.assertEqual(self.call("/api/chat", raw=b"x" * 40000)[0], 413)
        self.assertEqual(self.call("/api/browser/respond", {"id": "stale", "value": True})[0], 409)
        self.assertEqual(self.call("/api/browser/respond", {"id": "good", "value": True})[0], 200)

    def test_static_files_cannot_escape_the_app_folder(self):
        status, headers, body = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(b"DOXA", body)
        status, _, body = self.call("/../../phone_bridge.py")
        self.assertNotIn(b"import", body)
        status, _, body = self.call("/%2e%2e/phone_bridge.py")
        self.assertNotIn(b"PhoneServer", body)

    def test_link_keeps_key_out_of_server_requests(self):
        self.assertEqual(phone_link("https://jarvis.example.com/", "abc"), "https://jarvis.example.com/#k=abc")


class StreamingTests(PhoneServerTests):
    def test_words_arrive_before_the_answer_finishes(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/chat/stream", body=json.dumps({"message": "hi"}),
                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        started = time.monotonic()
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/x-ndjson")
        first = json.loads(response.readline())
        first_at = time.monotonic() - started
        self.assertEqual(first, {"type": "token", "text": "Hel"})
        self.assertLess(first_at, 0.9)  # the whole answer takes 1.2 s; the first word must not wait for it
        rest = [json.loads(line) for line in response.read().splitlines() if line.strip()]
        self.assertEqual(rest[-1]["type"], "done")
        self.assertGreater(time.monotonic() - started, 1.1)
        conn.close()

    def test_stream_errors_are_normal_http_errors(self):
        status, _, body = self.call("/api/chat/stream", {"message": "boom"})
        self.assertEqual((status, json.loads(body)["error"]), (503, "Model loading"))
        self.assertEqual(self.call("/api/chat/stream", {"message": "x"}, key="wrong")[0], 401)

    def test_connection_survives_an_error_without_garbling_the_next_request(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/chat", body=json.dumps({"message": "hello"}), headers={"Authorization": "Bearer wrong"})
        self.assertEqual(conn.getresponse().read() and 401, 401)
        conn.close()
        status, _, body = self.call("/api/chat", {"message": "hello"})
        self.assertEqual(status, 200)

    def test_push_token_registration(self):
        self.assertEqual(self.call("/api/push/register", {"token": "ExponentPushToken[abcdefghij123]"})[0], 200)
        self.assertEqual(self.call("/api/push/register", {"token": "not-a-token"})[0], 400)


class NotifierTests(unittest.TestCase):
    def test_sends_to_registered_phones_and_drops_dead_tokens(self):
        from forgemind.phone_bridge import PushNotifier
        with tempfile.TemporaryDirectory() as folder:
            access = PhoneAccess(Path(folder) / "phone.json")
            access.add_push_token("ExponentPushToken[aaaaaaaaaaaa]")
            access.add_push_token("ExponentPushToken[bbbbbbbbbbbb]")
            sent = []

            def post(payload):
                sent.append(payload)
                return {"data": [{"status": "ok"}, {"status": "error", "details": {"error": "DeviceNotRegistered"}}]}

            PushNotifier(access, post=post).send("Doxa needs your OK", "Book the DMV appointment?", {"screen": "task"},
                                                 background=False)
            self.assertEqual([m["to"] for m in sent[0]], ["ExponentPushToken[aaaaaaaaaaaa]", "ExponentPushToken[bbbbbbbbbbbb]"])
            self.assertEqual(sent[0][0]["title"], "Doxa needs your OK")
            self.assertEqual(access.data["push_tokens"], ["ExponentPushToken[aaaaaaaaaaaa]"])
            self.assertTrue(PhoneAccess(Path(folder) / "phone.json").data["push_tokens"])  # saved

    def test_no_phones_no_network(self):
        from forgemind.phone_bridge import PushNotifier
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            PushNotifier(PhoneAccess(Path(folder) / "p.json"), post=calls.append).send("t", "b", background=False)
            self.assertEqual(calls, [])

    def test_controller_reports_requests_for_notifications(self):
        snap = Snapshot("https://x.test", "Form", "", [Element(1, "button", "", "submit", "Book appointment")])
        seen = []
        controller = BrowserController(lambda: FakeSession(snap), lambda: scripted([{"action": "click", "id": 1}]),
                                       on_request=seen.append)
        controller.start("book it")
        self.assertTrue(wait_until(lambda: seen))
        self.assertEqual(seen[0]["kind"], "confirm")
        controller.respond(seen[0]["id"], False)
        controller.join(5)


class TunnelTests(unittest.TestCase):
    def test_quick_tunnel_address_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            script = textwrap.dedent("""
                import os, time
                print("INF Requesting new quick Tunnel on trycloudflare.com...", flush=True)
                print("INF |  https://brave-orange-cat.trycloudflare.com  |", flush=True)
                for _ in range(300):  # exit early once the test's temp folder is gone
                    if not os.path.exists(__file__):
                        break
                    time.sleep(0.1)
            """)
            if sys.platform == "win32":
                # Windows can't run a "#!" script; launch the fake through a .cmd wrapper instead.
                (Path(folder) / "fake_cloudflared.py").write_text(script)
                fake = Path(folder) / "cloudflared.cmd"
                fake.write_text(f'@"{sys.executable}" "%~dp0fake_cloudflared.py" %*\r\n')
            else:
                fake = Path(folder) / "cloudflared"
                fake.write_text("#!" + sys.executable + "\n" + script)
                fake.chmod(0o755)
            tunnel = Tunnel(8790, exe=str(fake))
            tunnel.start_quick()
            try:
                self.assertEqual(tunnel.wait_for_url(5), "https://brave-orange-cat.trycloudflare.com")
                self.assertTrue(tunnel.running)
            finally:
                tunnel.stop()
            self.assertFalse(tunnel.running)

    def test_missing_cloudflared_is_explained(self):
        tunnel = Tunnel(8790, exe=None)
        import forgemind.phone_bridge as bridge
        original = bridge.find_cloudflared
        bridge.find_cloudflared = lambda: None
        try:
            with self.assertRaisesRegex(RuntimeError, "SETUP_PHONE_ACCESS"):
                tunnel.start_quick()
        finally:
            bridge.find_cloudflared = original


class DelegateTests(unittest.TestCase):
    def make_app(self, loaded=True):
        messages = []

        class DB:
            def recent_messages(self, limit):
                return messages[-limit:]

            def add_message(self, role, content):
                messages.append({"role": role, "content": content})

            def retrieve(self, text):
                return []

        class Inference:
            def stream(self, history, text, settings, memories, web, stop_event=None):
                yield "Sure, "
                yield "here you go."

        journal = SimpleNamespace(start=lambda t: "r1", first_response=lambda r: None, finish=lambda *a: None)
        from forgemind.config import Settings
        app = SimpleNamespace(db=DB(), engine=SimpleNamespace(loaded=loaded, model_name="Qwen3.5-9B"),
                              inference=Inference(), run_journal=journal, events=queue.Queue(), busy=False,
                              settings_data=Settings(auto_research=False),
                              browser_controller=SimpleNamespace(running=False, stop=lambda: None))
        return app, messages

    def test_website_requests_become_an_offer_not_an_action(self):
        app, messages = self.make_app()
        result = AppPhoneDelegate(app).chat("make a dmv appointment in Van Nuys for a title transfer")
        self.assertEqual(result["kind"], "browser_offer")
        self.assertIn("dmv appointment", result["task"])
        self.assertEqual(messages, [])

    def test_chat_uses_local_model_and_shows_on_pc(self):
        app, messages = self.make_app()
        result = AppPhoneDelegate(app).chat("tell me a fun fact about owls")
        self.assertEqual(result["reply"], "Sure, here you go.")
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertEqual(app.events.get_nowait()[0], "phone_chat")

    def test_stream_yields_tokens_then_done(self):
        app, messages = self.make_app()
        events = list(AppPhoneDelegate(app).chat_stream("tell me a fun fact about owls"))
        self.assertEqual([e["type"] for e in events], ["token", "token", "done"])
        self.assertEqual(events[-1]["reply"], "Sure, here you go.")
        self.assertEqual(len(messages), 2)

    def test_model_not_loaded(self):
        app, _ = self.make_app(loaded=False)
        with self.assertRaises(PhoneError):
            AppPhoneDelegate(app).chat("tell me a joke")

    def test_stop_reaches_the_desktop(self):
        app, _ = self.make_app()
        AppPhoneDelegate(app).stop()
        self.assertEqual(app.events.get_nowait(), ("phone_stop",))


if __name__ == "__main__":
    unittest.main()
