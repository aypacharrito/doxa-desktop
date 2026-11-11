import json
import tempfile
import threading
import unittest
from pathlib import Path

from forgemind.team import TeamRunner, TeamStore

SCRIPTS = json.dumps([
    {"angle": "Pain", "hook": "Your paper towel bill is lying to you", "script": "Show roll... ", "cta": "Link in bio",
     "caption": "Stop buying paper towels", "hashtags": ["cleaning"], "film_notes": "Kitchen, daylight", "why": "brief #2"},
    {"angle": "Demo", "hook": "One sheet. Whole counter.", "script": "Spill, wipe...", "cta": "Shop", "caption": "c",
     "hashtags": [], "film_notes": "Close-up", "why": "brief #1"},
])


class FakeBrain:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000):
        self.calls.append(("chat", messages[0]["content"][:60]))
        yield self.replies.pop(0)

    def agent_stream(self, system, messages, tools, stop_event=None, effort="medium", on_status=None, **kw):
        self.calls.append(("agent", messages[0]["content"][:60]))
        assert tools.specs == []  # the research desk gets web search only, no PC tools
        yield self.replies.pop(0)


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.store = TeamStore(root / "team.json", work_root=root / "Doxa Team")
        self.lessons = []

    def tearDown(self):
        self.dir.cleanup()

    def runner(self, brain, agentic=True):
        self.done = threading.Event()
        return TeamRunner(self.store, lambda: {"claude": brain} if brain else {}, on_change=lambda: None,
                          notify=lambda text: self.done.set() if "problem" in text or ":" in text else None,
                          knowledge_add=lambda *a: self.lessons.append(a), rules=lambda: "1. Distribution beats product.")

    def run_room(self, runner, room):
        finished = threading.Event()
        runner.on_change = lambda: finished.set() if room not in runner.busy else None
        runner.start(room)
        self.assertTrue(finished.wait(5))

    def test_whole_line_research_to_lessons(self):
        with self.assertRaises(ValueError):
            self.store.create_campaign("", "x")
        campaign = self.store.create_campaign("Cloth roll test", "20 orders in 14 days", "renters 25-40", offer="https://x.test")
        brain = FakeBrain([
            "Teardown https://tiktok.com/a and https://youtube.com/b ... Brief: lead with the bill.",
            "Here you go:\n" + SCRIPTS,
            "Pain hook won.\nLESSONS: [{\"title\": \"Bill hooks beat demos\", \"lesson\": \"Lead with cost\", \"tags\": [\"marketing\"]}]",
        ])
        runner = self.runner(brain)
        with self.assertRaises(ValueError):  # writers need a brief first
            runner._writers(campaign)
        self.run_room(runner, "research")
        self.assertEqual(self.store.campaign()["sources"], 2)
        self.assertTrue(Path(self.store.campaign()["brief_path"]).is_file())
        self.run_room(runner, "writers")
        waiting = self.store.items(stage="waiting")
        self.assertEqual(len(waiting), 2)
        self.assertEqual(self.store.counts()["approval"], 2)
        # the human gate
        self.store.decide(waiting[0]["id"], True)
        self.store.decide(waiting[1]["id"], False)
        with self.assertRaises(ValueError):
            self.store.decide(waiting[1]["id"], True)
        with self.assertRaises(ValueError):
            self.store.mark_posted(waiting[0]["id"], "TikTok", "https://tiktok.com/v/1")  # not filmed yet
        self.store.mark_filmed(waiting[0]["id"])
        with self.assertRaises(ValueError):
            self.store.mark_posted(waiting[0]["id"], "TikTok", "posted it")  # no link = no receipt
        self.store.mark_posted(waiting[0]["id"], "TikTok", "https://tiktok.com/v/1")
        self.store.record_results(waiting[0]["id"], 0, {"views": "1200", "saves": 40, "bogus": 9})
        counts = self.store.counts()
        self.assertEqual((counts["shipping"], counts["analyst"], counts["film"]), (1, 1, 0))
        self.run_room(runner, "analyst")
        self.assertEqual(self.lessons[0][0], "Bill hooks beat demos")
        self.assertIn("Pain hook won", self.store.campaign()["analysis"])
        self.assertEqual([kind for kind, _ in brain.calls], ["agent", "chat", "chat"])
        # survives a restart
        again = TeamStore(self.store.path, work_root=self.store.work_root)
        self.assertEqual(again.campaign()["name"], "Cloth roll test")

    def test_rooms_that_are_not_automated_and_no_brain(self):
        self.store.create_campaign("Song", "1,000 saves")
        runner = self.runner(None)
        with self.assertRaises(ValueError):
            runner.start("mailroom")
        runner.brain_for = lambda: {}
        self.run_room(runner, "research")
        self.assertEqual(self.store.data["workers"]["research"]["status"], "problem")


if __name__ == "__main__":
    unittest.main()
