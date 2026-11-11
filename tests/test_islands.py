"""Doxa HQ islands (business lines) and the Research Lab (upgrade prompts that wait for the owner's OK)."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from forgemind import hq_data
from forgemind.products import HuntStore
from forgemind.team import TeamRunner, TeamStore
from forgemind.upgrades import RESEARCH_EVERY, UpgradeLab, UpgradeStore

IDEAS = json.dumps([
    {"title": "Etsy listing writer", "island": "stores", "why": "Listings for each winner.", "sources": ["https://a.test", "ftp://x"],
     "prompt": "Add an Etsy listing writer to the Store Builder: title, 13 tags, description; tests for length limits."},
    {"title": "Too short", "prompt": "do it"},
    {"title": "Backtest paper trades", "island": "trading", "why": "Replay rules on past prices.",
     "prompt": "Add a backtester to the paper trading journal using saved prices; tests with a fixed price series."},
])


class FakeBrain:
    provider_id, display_name = "gemini", "Gemini"

    def __init__(self, reply):
        self.reply, self.kw = reply, None

    def chat_stream(self, system, messages, **kw):
        self.kw = kw
        yield self.reply


class LabTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = UpgradeStore(Path(self.dir.name) / "upgrades.json")
        self.built = []
        self.done = threading.Event()
        self.brain = FakeBrain("Here:\n" + IDEAS)
        self.lab = UpgradeLab(self.store, lambda: {"gemini": self.brain},
                              build=lambda task: (self.built.append(task), "Code mode started: building a copy of Doxa.")[1],
                              on_change=lambda: None if self.lab.busy else self.done.set())

    def tearDown(self):
        self.dir.cleanup()

    def test_research_makes_prompts_that_wait_and_build_only_on_approval(self):
        self.assertTrue(self.lab.due())
        self.lab.start(focus="Etsy stores")
        self.assertTrue(self.done.wait(5))
        self.assertEqual(self.brain.kw.get("search"), True)  # Gemini researches with Google Search
        waiting = self.store.waiting()
        self.assertEqual([p["title"] for p in waiting], ["Etsy listing writer", "Backtest paper trades"])
        self.assertEqual(waiting[0]["sources"], ["https://a.test"])
        self.assertFalse(self.lab.due())
        self.assertEqual(self.built, [])  # nothing is built without the owner's OK
        rejected = self.lab.decide(waiting[1]["id"], False)
        self.assertEqual(rejected["status"], "rejected")
        built = self.lab.decide(waiting[0]["id"], True)
        self.assertEqual(built["status"], "building")
        self.assertIn("Etsy listing writer", self.built[0])
        with self.assertRaises(ValueError):
            self.lab.decide(waiting[0]["id"], True)  # already decided
        # a repeat idea isn't added twice; the file survives a restart
        self.assertEqual(self.store.add(json.loads(IDEAS), "x"), [])
        again = UpgradeStore(self.store.path)
        self.assertEqual(again.counts()["building"], 1)
        self.assertFalse(again.data["busy"])

    def test_no_brain_and_weekly_cadence(self):
        lab = UpgradeLab(self.store, lambda: {}, build=lambda t: "")
        with self.assertRaises(ValueError):
            lab.start()
        clock = [time.time()]
        timed = UpgradeLab(self.store, lambda: {"gemini": self.brain}, build=lambda t: "", clock=lambda: clock[0],
                           on_change=lambda: None if timed.busy else self.done.set())
        timed.start()
        self.assertTrue(self.done.wait(5))
        self.assertFalse(timed.due())
        clock[0] += RESEARCH_EVERY + 1
        self.assertTrue(timed.due())

    def test_a_failed_research_run_says_why(self):
        class Broken(FakeBrain):
            def chat_stream(self, *a, **k):
                raise ValueError("Gemini is rate-limiting")
                yield ""
        lab = UpgradeLab(self.store, lambda: {"gemini": Broken("")}, build=lambda t: "",
                         on_change=lambda: None if lab.busy else self.done.set())
        lab.start()
        self.assertTrue(self.done.wait(5))
        self.assertIn("rate-limiting", self.store.data["status"])
        self.assertFalse(lab.busy)


class DepartmentTests(unittest.TestCase):
    def test_every_island_reports_real_numbers_and_never_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            team = TeamStore(root / "team.json", work_root=root / "Doxa Team")
            team.create_campaign("Song", "1,000 saves")
            products = HuntStore(root)
            products.add_hunt({"date": "2026-11-09", "niche": "", "report": "", "brain": "x",
                               "products": [{"id": "a", "name": "Paw cup", "score": 81}, {"id": "b", "name": "Bidet", "score": 85}]})
            products.mark("b", "winner")
            lab = UpgradeLab(UpgradeStore(root / "u.json"), lambda: {}, build=lambda t: "")
            lab.store.add(json.loads(IDEAS), "x")
            app = SimpleNamespace(team=team, team_runner=TeamRunner(team, lambda: {}), products=products, _hunting=False,
                                  brain=SimpleNamespace(tools=SimpleNamespace(notes_dir=root)), upgrades=lab,
                                  code_runner=SimpleNamespace(state=lambda: {"job": {"status": "running", "task": "fix x", "name": "Codex"}}),
                                  settings_data=SimpleNamespace(pacifica_url="https://crm.example.com"), events=None)
            lessons = root / "lessons.md"
            lessons.write_text("### 2026-11-08 · `marketing` · Hooks first\nx\n### 2026-11-09 · `ai-tools` · Spread the work\n", "utf-8")
            with mock.patch("forgemind.knowledge.LESSONS", lessons):
                d = hq_data.departments(app)
            self.assertEqual({k for k, *_ in hq_data.ISLANDS}, set(d))
            self.assertEqual((d["stores"]["count"], d["stores"]["winners"]), (2, 1))
            self.assertEqual(d["stores"]["top"][0]["name"], "Bidet")  # winners first
            self.assertEqual(d["trading"]["cash"], 10000.0)  # no paper trades yet
            self.assertEqual(d["lab"]["count"], 2)
            self.assertNotIn("desk", d)  # the owner 2026-11-09: no "Your Desk"; Doxa approves
            self.assertTrue(d["code"]["busy"])
            self.assertEqual(d["knowledge"]["latest"], ["Spread the work", "Hooks first"])
            self.assertTrue(d["pacifica"]["connected"])
            app.products = None  # a broken source shows as unavailable, the rest still works
            self.assertEqual(hq_data.departments(app)["stores"]["count"], 0)

    def test_island_buttons(self):
        events = []
        app = SimpleNamespace(_hunting=False, events=SimpleNamespace(put=events.append),
                              upgrades=SimpleNamespace(start=lambda focus="": "researching", decide=lambda i, a: {"status": "rejected", "note": ""}))
        self.assertIn("started", hq_data.action(app, "hunt", {})["message"])
        self.assertEqual(events[0][0], "ui")
        self.assertEqual(hq_data.action(app, "lab_research", {})["message"], "researching")
        self.assertEqual(hq_data.action(app, "lab_decide", {"id": "x", "approve": False})["status"], "rejected")
        with self.assertRaises(ValueError):
            hq_data.action(app, "rm -rf", {})


if __name__ == "__main__":
    unittest.main()
