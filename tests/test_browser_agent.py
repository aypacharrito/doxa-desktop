"""Browser agent: action validation, safety gates, and a full mock-DMV booking in a real browser.

The browser tests need Playwright and a Chromium-based browser. They are skipped otherwise.
Set FORGEMIND_TEST_BROWSER to a browser executable to use a specific one.
"""
import os
import re
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from forgemind.browser_agent import BrowserSession, BrowserTask, Element, OwnerFacts, Snapshot, validate

try:
    import playwright  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

def _windows_browser():
    """Edge (or Chrome) in its standard install location, since neither is on PATH on Windows."""
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for rel in (("Microsoft", "Edge", "Application", "msedge.exe"),
                    ("Google", "Chrome", "Application", "chrome.exe")):
            if base and Path(base, *rel).is_file():
                return str(Path(base, *rel))
    return None


BROWSER = (os.environ.get("FORGEMIND_TEST_BROWSER") or shutil.which("google-chrome") or shutil.which("chromium")
           or (_windows_browser() if os.name == "nt" else None))

PAGES = {
    "/": """<html><head><title>Mock DMV</title></head><body><h1>Mock DMV</h1>
        <a href="/appointment">Make an Appointment</a> <a href="/about">About us</a></body></html>""",
    "/appointment": """<html><head><title>Office Appointment</title></head><body>
        <form method="post" action="/book">
          <label for="office">Office</label><select id="office" name="office"><option>Choose</option><option>Reseda</option><option>Van Nuys</option></select>
          <fieldset><legend>Service</legend>
            <label><input type="radio" name="service" value="dl">Driver license</label>
            <label><input type="radio" name="service" value="title">Vehicle title transfer</label></fieldset>
          <label for="first">First name</label><input id="first" name="first">
          <label for="last">Last name</label><input id="last" name="last">
          <label for="phone">Phone number</label><input id="phone" name="phone" type="tel">
          <label for="date">Date</label><select id="date" name="date"><option>Choose</option><option>Nov 12, 9:00 AM</option><option>Nov 13, 2:30 PM</option></select>
          <button type="submit">Book appointment</button>
        </form></body></html>""",
    "/login": """<html><head><title>Sign in</title></head><body><label for="u">Email</label><input id="u">
        <label for="p">Password</label><input id="p" type="password"><button>Sign in</button></body></html>""",
    "/captcha": """<html><head><title>Check</title></head><body><p>Please verify you are human.</p>
        <button onclick="document.body.innerHTML='<p>Thanks</p><a href=/appointment>Continue to appointments</a>'">I'm done</button></body></html>""",
}


class Site(BaseHTTPRequestHandler):
    bookings = []

    def log_message(self, *_):
        pass

    def _send(self, body, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        page = PAGES.get(self.path.split("?")[0])
        self._send(page or "<title>Not found</title>missing", 200 if page else 404)

    def do_POST(self):
        data = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        Site.bookings.append({k: v[0] for k, v in data.items()})
        self._send("<html><head><title>Booked</title></head><body><h1>Appointment confirmed</h1>"
                   f"<p>Confirmation number DMV-4821 for {data.get('date', ['?'])[0]}</p></body></html>")


def find(prompt, pattern):
    """Element number whose line matches pattern, the way the model would read it."""
    for line in prompt.splitlines():
        if re.search(pattern, line, re.I):
            m = re.match(r"\[(\d+)\]", line)
            if m:
                return int(m.group(1))
    raise AssertionError(f"no element matching {pattern}\n{prompt}")


class ScriptedPlanner:
    """Stands in for the local model: reads the same prompt, follows the DMV script."""

    def __init__(self, base):
        self.base, self.calls = base, 0

    def __call__(self, prompt):
        self.calls += 1
        page = re.search(r"URL: (\S+)", prompt).group(1)
        known = prompt.split("DETAILS THE OWNER HAS GIVEN:")[1].split("RECENT STEPS:")[0]
        recent = prompt.split("RECENT STEPS:")[1].split("CURRENT PAGE:")[0]
        if "Appointment confirmed" in prompt:
            return {"action": "done", "summary": re.search(r"Confirmation number \S+ for [^\n]+", prompt).group(0)}
        if "/appointment" not in page:
            if page.rstrip("/").endswith(self.base.split("//")[1].rstrip("/")) or page.endswith("/"):
                return {"action": "click", "id": find(prompt, r'link "Make an Appointment"|a "Make an Appointment"')}
            return {"action": "goto", "url": self.base + "/"}
        if "full name" not in known:
            return {"action": "ask_owner", "question": "What is your full name?"}
        if "phone" not in known:
            return {"action": "ask_owner", "question": "What phone number should DMV use?"}
        name = re.search(r"full name\?: (.+)", known).group(1).split()
        phone = re.search(r"phone number should DMV use\?: (.+)", known).group(1)
        steps = [
            ("Office", lambda: {"action": "select", "id": find(prompt, r'"Office"'), "option": "Van Nuys"}),
            ("title transfer", lambda: {"action": "check", "id": find(prompt, r"title transfer"), "value": True}),
            ("First name", lambda: {"action": "fill", "id": find(prompt, r'"First name"'), "text": name[0]}),
            ("Last name", lambda: {"action": "fill", "id": find(prompt, r'"Last name"'), "text": name[-1]}),
            ("Phone number", lambda: {"action": "fill", "id": find(prompt, r'"Phone number"'), "text": phone}),
            ("Date", lambda: {"action": "select", "id": find(prompt, r'"Date"'), "option": "Nov 12, 9:00 AM"}),
        ]
        for label, make in steps:
            if label not in recent and f"in '{label}" not in recent and f"'{label}" not in recent:
                return make()
        return {"action": "click", "id": find(prompt, r'"Book appointment"'), "thought": "All fields are filled."}


class ValidationTests(unittest.TestCase):
    def test_rejects_bad_actions(self):
        for bad in [{"action": "rm"}, {"action": "click"}, {"action": "goto", "url": "file:///etc/passwd"},
                    {"action": "goto", "url": "javascript:alert(1)"}, {"action": "press", "key": "F5"},
                    {"action": "fill", "id": 3}, {"action": "ask_owner", "question": ""}, "click 3"]:
            with self.assertRaises(ValueError, msg=bad):
                validate(bad)
        self.assertEqual(validate({"action": "click", "id": "4"})["id"], 4)
        self.assertEqual(validate({"action": "wait", "seconds": 99})["seconds"], 10)

    def test_commit_buttons_are_gated_but_links_are_not(self):
        self.assertTrue(Element(1, "button", "", "submit", "Book appointment").commits)
        self.assertTrue(Element(2, "input", "", "submit", "Confirm").commits)
        self.assertFalse(Element(3, "a", "", "", "Make an Appointment").commits)
        self.assertFalse(Element(4, "button", "", "", "Next").commits)

    def test_owner_facts_never_store_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            facts = OwnerFacts(Path(folder) / "facts.json")
            facts.remember("What is your phone number?", "818-555-0100")
            facts.remember("What is your password?", "hunter2")
            self.assertEqual(facts.load(), {"What is your phone number?": "818-555-0100"})


class FakeSession:
    """Lets the loop be tested without a browser."""

    def __init__(self, snapshots):
        self.snapshots, self.clicked, self.filled = list(snapshots), [], []

    def snapshot(self):
        return self.snapshots[0] if len(self.snapshots) == 1 else self.snapshots.pop(0)

    def fill(self, element, text):
        self.filled.append((element.id, text))

    def click(self, element):
        self.clicked.append(element.id)

    def screenshot(self, path):
        pass


class LoopTests(unittest.TestCase):
    def make(self, snapshots, actions, **kw):
        actions = list(actions)
        callbacks = dict(ask=lambda q: ("x", False), confirm=lambda t, b: True, hand_off=lambda r: True)
        callbacks.update(kw)
        session = FakeSession(snapshots)
        task = BrowserTask("test", lambda prompt: actions.pop(0) if actions else {"action": "done", "summary": "ok"}, session, **callbacks)
        return task, session

    def test_password_is_handed_to_owner_not_typed(self):
        snap = Snapshot("https://x.test", "Sign in", "", [Element(1, "input", "", "password", "Password", sensitive=True)])
        handed = []
        task, session = self.make([snap], [{"action": "fill", "id": 1, "text": "guess"}], hand_off=lambda r: handed.append(r) or True)
        self.assertEqual(task.run()["status"], "completed")
        self.assertEqual(session.filled, [])
        self.assertIn("Password", handed[0])

    def test_declined_confirmation_submits_nothing(self):
        snap = Snapshot("https://x.test", "Form", "", [Element(1, "button", "", "submit", "Submit request")])
        task, session = self.make([snap], [{"action": "click", "id": 1}], confirm=lambda t, b: False)
        result = task.run()
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(session.clicked, [])

    def test_captcha_goes_to_owner_and_stop_is_respected(self):
        snap = Snapshot("https://x.test", "Check", "", [], captcha=True)
        task, _ = self.make([snap], [], hand_off=lambda r: False)
        self.assertEqual(task.run()["status"], "stopped")

    def test_repeating_without_progress_stops(self):
        snap = Snapshot("https://x.test", "Page", "", [Element(1, "a", "", "", "Next page")])
        task, _ = self.make([snap], [{"action": "click", "id": 1}] * 10)
        self.assertEqual(task.run()["status"], "needs_input")

    def test_stop_event(self):
        snap = Snapshot("https://x.test", "Page", "", [])
        task, _ = self.make([snap], [{"action": "wait", "seconds": 5}] * 5)
        task.stop.set()
        self.assertEqual(task.run()["status"], "stopped")


@unittest.skipUnless(HAVE_PLAYWRIGHT and BROWSER, "Playwright and a Chromium browser are required")
class RealBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Site.bookings.clear()
        self.folder = tempfile.TemporaryDirectory()
        self.session = BrowserSession(Path(self.folder.name) / "profile", headless=True, executable_path=BROWSER).open()

    def tearDown(self):
        self.session.close()
        self.folder.cleanup()

    def run_task(self, confirm=True):
        asked, confirmations = [], []

        def ask(question):
            asked.append(question)
            return ("Alex Rivera", True) if "name" in question else ("818-555-0100", False)

        facts = OwnerFacts(Path(self.folder.name) / "facts.json")
        task = BrowserTask("Make a DMV appointment in Van Nuys for a title transfer", ScriptedPlanner(self.base), self.session,
                           ask=ask, confirm=lambda t, b: confirmations.append((t, b)) or confirm, hand_off=lambda r: True,
                           facts=facts, root=Path(self.folder.name) / "runs")
        return task.run(), asked, confirmations, facts

    def test_books_mock_dmv_appointment_end_to_end(self):
        result, asked, confirmations, facts = self.run_task()
        self.assertEqual(result["status"], "completed", result)
        self.assertIn("DMV-4821", result["message"])
        self.assertEqual(len(Site.bookings), 1)
        booking = Site.bookings[0]
        self.assertEqual(booking, {"office": "Van Nuys", "service": "title", "first": "Alex", "last": "Rivera",
                                   "phone": "818-555-0100", "date": "Nov 12, 9:00 AM"})
        self.assertEqual(len(asked), 2)
        self.assertEqual(len(confirmations), 1)
        title, body = confirmations[0]
        self.assertIn("Book appointment", title)
        self.assertIn("Van Nuys", body)
        self.assertIn("818-555-0100", body)
        self.assertEqual(list(facts.load()), ["What is your full name?"])  # only what the owner chose to remember
        self.assertTrue(Path(result["screenshot"]).exists())

    def test_nothing_is_submitted_without_approval(self):
        result, _, confirmations, _ = self.run_task(confirm=False)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(len(confirmations), 1)
        self.assertEqual(Site.bookings, [])

    def test_snapshot_marks_password_fields_sensitive(self):
        self.session.goto(self.base + "/login")
        snap = self.session.snapshot()
        password = next(e for e in snap.elements if e.type == "password")
        self.assertTrue(password.sensitive)
        self.assertIn("Password", password.name)

    def test_snapshot_detects_human_check(self):
        self.session.goto(self.base + "/captcha")
        self.assertTrue(self.session.snapshot().captcha)


if __name__ == "__main__":
    unittest.main()
