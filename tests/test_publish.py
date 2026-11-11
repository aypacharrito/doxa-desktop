"""Doxa's own "Vercel": Doxa Sites → Cloudflare's free hosting, with the owner's one-time Cloudflare sign-in."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from forgemind.publish import Publisher, slug


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.sites = Path(self.dir.name) / "Doxa Sites"
        (self.sites / "Joe's Tacos").mkdir(parents=True)
        (self.sites / "Joe's Tacos" / "index.html").write_text("<h1>Tacos</h1>", "utf-8")
        (self.sites / "Draft").mkdir()
        self.calls = []

    def tearDown(self):
        self.dir.cleanup()

    def wait_idle(self, pub):
        for _ in range(100):
            if not pub.state["busy"]:
                return
            time.sleep(0.02)

    def test_publish_runs_wrangler_on_the_site_folder_and_saves_the_address(self):
        def runner(args, timeout=300, cwd=None):
            self.calls.append(args)
            return 0, "Uploaded doxa-joe-s-tacos\nhttps://doxa-joe-s-tacos.example.workers.dev\n"
        pub = Publisher(self.sites, runner=runner)
        self.assertIn("Publishing Joe's Tacos", pub.publish("Joe's Tacos"))
        self.wait_idle(pub)
        args = self.calls[-1]
        self.assertIn("deploy", args)
        self.assertEqual(args[args.index("--name") + 1], "doxa-joe-s-tacos")
        self.assertTrue(args[args.index("--assets") + 1].endswith("Joe's Tacos"))
        info = json.loads((self.sites / "Joe's Tacos" / "site.json").read_text("utf-8"))
        self.assertEqual(info["published_url"], "https://doxa-joe-s-tacos.example.workers.dev")
        self.assertIn("is live", pub.state["status"])
        listed = {s["name"]: s for s in pub.sites_list()}
        self.assertTrue(listed["Joe's Tacos"]["url"])
        self.assertFalse(listed["Draft"]["ready"])

    def test_only_doxa_sites_and_only_built_ones(self):
        pub = Publisher(self.sites, runner=lambda *a, **k: (0, ""))
        with self.assertRaises(ValueError):
            pub.publish("..\..\Windows")
        with self.assertRaisesRegex(ValueError, "no index.html"):
            pub.publish("Draft")

    def test_not_signed_in_says_connect_cloudflare(self):
        pub = Publisher(self.sites, runner=lambda *a, **k: (1, "You are not authenticated. Please run `wrangler login`."))
        pub.publish("Joe's Tacos")
        self.wait_idle(pub)
        self.assertIn("Connect Cloudflare first", pub.state["status"])
        self.assertFalse(pub.state["connected"])

    def test_sign_in_check_reads_wranglers_answer(self):
        done = threading.Event()
        answers = iter([(0, "You are not authenticated. Please run `wrangler login`."),
                        (0, "You are logged in with an OAuth Token, associated with the email x. Account ID: abc")])

        def runner(args, timeout=300, cwd=None):
            out = next(answers)
            threading.Timer(0.01, done.set).start()
            return out
        pub = Publisher(self.sites, runner=runner)
        pub.refresh(force=True)
        self.assertTrue(done.wait(2)); time.sleep(0.05)
        self.assertFalse(pub.state["connected"])
        done.clear()
        pub.refresh(force=True)
        self.assertTrue(done.wait(2)); time.sleep(0.05)
        self.assertTrue(pub.state["connected"])
        self.assertEqual(slug("Steńos Studio!!"), "doxa-ste-os-studio")
