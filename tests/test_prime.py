"""Doxa Prime (the manager on the command island) and the in-Doxa HQ embed helper."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from forgemind import embed_web
from forgemind.team import MAX_RUNS_PER_DAY, RESEARCH_EVERY, WRITERS_EVERY, Prime, TeamRunner, TeamStore


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


class FakeRunner(TeamRunner):
    """Records starts instead of running AI jobs."""

    def __init__(self, store, connected=True):
        super().__init__(store, lambda: {"claude": object()} if connected else {})
        self.started = []

    def start(self, room, **options):
        campaign = self.store.campaign()
        if not campaign:
            raise ValueError("Start a campaign first.")
        self.started.append(room)
        with self.store.lock:
            self.store.data.setdefault("prime", {}).setdefault("last", {})[f"{campaign['id']}:{room}"] = self.clock()


class PrimeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.store = TeamStore(root / "team.json", work_root=root / "Doxa Team")
        self.clock = Clock()
        self.runner = FakeRunner(self.store)
        self.runner.clock = self.clock
        self.notes = []
        self.prime = Prime(self.store, self.runner, clock=self.clock, notify=self.notes.append)

    def tearDown(self):
        self.dir.cleanup()

    def test_waits_for_a_campaign_and_an_ai(self):
        self.assertIn("first campaign", self.prime.tick())
        self.store.create_campaign("Song", "1,000 saves")
        offline = Prime(self.store, FakeRunner(self.store, connected=False), clock=self.clock)
        self.assertIn("No AI connected", offline.tick())
        self.assertEqual(self.runner.started, [])

    def test_keeps_the_line_moving_in_order(self):
        campaign = self.store.create_campaign("Song", "1,000 saves")
        self.assertIn("Sent Nova to Research", self.prime.tick())
        self.assertEqual(self.runner.started, ["research"])
        campaign["brief"] = "what works"
        self.assertIn("Sent Quill to Writers' Room", self.prime.tick())
        # scripts are waiting for the owner: nothing more to do until time passes or he acts
        for i in range(3):
            self.store.data["items"].append({"id": f"s{i}", "campaign": campaign["id"], "stage": "waiting", "hook": "h"})
        self.assertIn("Waiting on you: 3 script(s) to approve", self.prime.tick())
        self.assertEqual(self.runner.started, ["research", "writers"])
        # new results arrive → the analyst runs once
        item = self.store.data["items"][0]
        item.update(stage="filmed", posts=[{"platform": "TikTok", "link": "https://tiktok.com/x", "results": {"views": 900, "revenue": 42.5}}])
        self.assertIn("Ledger", self.prime.tick())
        campaign["analysed_posts"] = 1
        self.assertNotIn("Sent", self.prime.tick())
        self.assertEqual(self.prime.view()["earned"], 42.5)
        self.assertEqual(self.prime.view()["mission"], 1_000_000_000_000)
        # 3 days later the research is stale again
        self.clock.now += RESEARCH_EVERY + 1
        self.assertIn("Research", self.prime.tick())
        self.assertTrue(self.notes and self.notes[0].startswith("Doxa: Sent Nova"))

    def test_daily_brake_pause_and_busy(self):
        campaign = self.store.create_campaign("Song", "1,000 saves")
        campaign["brief"] = "x"
        self.runner.busy.add("research")
        self.assertIn("The team is working", self.prime.tick())
        self.runner.busy.clear()
        self.store.data["prime"]["runs"] = MAX_RUNS_PER_DAY
        self.assertIn("Done for today", self.prime.tick())
        self.store.data["prime"]["day"] = "2000-01-01"  # a new day resets the brake
        self.clock.now += WRITERS_EVERY + 1
        self.assertIn("Sent", self.prime.tick())
        paused = Prime(self.store, self.runner, enabled=lambda: False, clock=self.clock)
        self.assertIn("Paused", paused.tick())
        self.assertFalse(paused.view()["on"])
        self.assertLessEqual(len(self.prime.view()["log"]), 8)

    def test_real_runner_records_manual_starts_for_prime(self):
        self.store.create_campaign("Song", "1,000 saves")
        done = threading.Event()
        runner = TeamRunner(self.store, lambda: {}, on_change=lambda: done.set() if not runner.busy else None)
        runner.start("research")  # fails later (no AI) but the start still counts
        self.assertTrue(done.wait(5))
        last = self.store.data["prime"]["last"]
        self.assertTrue(any(k.endswith(":research") for k in last))


class CharacterArtTests(unittest.TestCase):
    def test_pictures_in_the_characters_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TeamStore(Path(folder) / "team.json", work_root=Path(folder) / "Doxa Team")
            self.assertEqual(store.characters(), {})
            art = store.ensure_art_folder()
            self.assertTrue((art / "HIGGSFIELD PROMPTS.md").is_file())
            (art / "prime.png").write_bytes(b"png")
            (art / "Edit.JPG").write_bytes(b"jpg")
            (art / "notes.txt").write_text("x")
            (art / "villain.png").write_bytes(b"not a team member")
            self.assertEqual(sorted(store.characters()), ["edit", "prime"])
            self.assertEqual(store.character("prime"), (b"png", "image/png"))
            self.assertIsNone(store.character("../team"))
            self.assertIsNone(store.character("villain"))


class EmbedTests(unittest.TestCase):
    def test_missing_window_returns_none_quickly(self):
        started = time.monotonic()
        self.assertIsNone(embed_web.find_window("no window has this title 7f3a", timeout=0.6))
        self.assertLess(time.monotonic() - started, 3)

    def test_profile_is_doxas_own(self):
        self.assertEqual(embed_web.profile_dir(Path("C:/x")).name, "hq-browser")


if __name__ == "__main__":
    unittest.main()
