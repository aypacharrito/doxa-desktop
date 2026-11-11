"""A chat box on every HQ island: answers with the island's context, queues research for its bot, queues the owner's
build requests for Code mode, keeps private messages local."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from forgemind.island_chat import IslandChat
from forgemind.upgrades import UpgradeLab, UpgradeStore
from forgemind.warehouses import WarehouseBots

ISLANDS = {"prime": ("Command", "Doxa", "Runs everything."), "lab": ("Research Lab", "Tinker", "Upgrades."),
           "trading": ("Trading", "Oracle", "Paper trading.")}


class FakeBrain:
    display_name = "Fake Claude"
    provider_id = "claude"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat_stream(self, system, messages, **kw):
        self.calls.append((system, messages))
        yield self.reply


def wait(chat, key):
    for _ in range(200):
        if key not in chat.busy:
            return
        time.sleep(0.01)
    raise AssertionError("no answer")


class IslandChatTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def make(self, brain, **kw):
        return IslandChat(self.root / "chats.json", brain_for=lambda private: brain, islands=ISLANDS, **kw)

    def test_answer_gets_the_island_context_and_queues_research(self):
        brain = FakeBrain(json.dumps({"reply": "Looking into it.", "research": [{"island": "trading", "question": "copy trading apps 2026"}], "build": None}))
        asked = []
        chat = self.make(brain, context=lambda key: f"numbers for {key}",
                         queue_research=lambda key, q: asked.append((key, q)) or "Oracle")
        chat.send("trading", "what's the copy trading app?")
        wait(chat, "trading")
        system, messages = brain.calls[0]
        self.assertIn("Trading island", system)
        self.assertIn("numbers for trading", system)
        self.assertEqual(messages[-1], {"role": "user", "content": "what's the copy trading app?"})
        self.assertEqual(asked, [("trading", "copy trading apps 2026")])
        view = chat.view("trading")
        self.assertEqual([m["role"] for m in view["messages"]], ["you", "doxa"])
        self.assertEqual(view["messages"][1]["text"], "Looking into it.")
        self.assertIn("Queued for Oracle", view["messages"][1]["queued"][0])
        self.assertEqual(chat.summary()["trading"]["n"], 2)
        again = IslandChat(self.root / "chats.json", brain_for=lambda p: brain, islands=ISLANDS)  # survives a restart
        self.assertEqual(len(again.view("trading")["messages"]), 2)

    def test_a_pasted_prompt_becomes_a_build_with_davids_words_kept(self):
        pasted = "Restyle Doxa HQ: JoJo colours, " + "x" * 300
        brain = FakeBrain(json.dumps({"reply": "On it.", "research": [], "build": {"title": "HQ restyle", "prompt": "Restyle the HQ page."}}))
        builds = []
        chat = self.make(brain, queue_build=lambda key, title, prompt: builds.append((key, title, prompt)) or {"id": "x"})
        chat.send("prime", pasted)
        wait(chat, "prime")
        key, title, prompt = builds[0]
        self.assertEqual((key, title), ("prime", "HQ restyle"))
        self.assertIn(pasted, prompt)                         # never shortened by the model
        self.assertIn("Queued to build", chat.view("prime")["messages"][-1]["queued"][0])

    def test_private_messages_stay_local_without_context_or_queues(self):
        local = FakeBrain(json.dumps({"reply": "ok", "research": [{"question": "x"}], "build": {"title": "t", "prompt": "p"}}))
        asked, builds, wanted = [], [], []
        chat = IslandChat(self.root / "c.json", brain_for=lambda private: wanted.append(private) or local, islands=ISLANDS,
                          context=lambda key: "SECRET NUMBERS", queue_research=lambda k, q: asked.append(q) or "Bot",
                          queue_build=lambda *a: builds.append(a))
        chat.send("lab", "private: my idea")
        wait(chat, "lab")
        self.assertEqual(wanted, [True])
        system, messages = local.calls[0]
        self.assertNotIn("SECRET NUMBERS", system)
        self.assertEqual(messages, [{"role": "user", "content": "my idea"}])
        self.assertEqual((asked, builds), ([], []))

    def test_errors_are_plain(self):
        chat = IslandChat(self.root / "c.json", brain_for=lambda private: None, islands=ISLANDS)
        with self.assertRaisesRegex(ValueError, "Connect an AI brain"):
            chat.send("lab", "hi")
        with self.assertRaisesRegex(ValueError, "Unknown island"):
            chat.send("nowhere", "hi")

        class Broken(FakeBrain):
            def chat_stream(self, *a, **kw):
                raise RuntimeError("overloaded")
                yield ""
        chat = self.make(Broken(""))
        chat.send("lab", "hi")
        wait(chat, "lab")
        self.assertIn("overloaded", chat.view("lab")["messages"][-1]["text"])

    def test_a_plain_text_reply_is_still_shown(self):
        chat = self.make(FakeBrain("Just text, no JSON."))
        chat.send("lab", "hi")
        wait(chat, "lab")
        self.assertEqual(chat.view("lab")["messages"][-1]["text"], "Just text, no JSON.")


class QueueTests(unittest.TestCase):
    def test_davids_question_goes_before_the_rotation_without_waiting_for_the_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            started = []
            bots = WarehouseBots(root / "w.json", brains=lambda: {"opencode": object()}, log_root=root / "logs",
                                 clock=lambda: 1000.0)
            bots._start = lambda key, brain, name, asked="": started.append((key, asked))
            bots.data["last_run"] = 999.0                    # the gap isn't over: no rotation run now
            self.assertIsNone(bots.tick())
            self.assertEqual(bots.ask("trading", "copy trading apps"), "Oracle")
            self.assertEqual(bots.view("trading")["asks"], ["copy trading apps"])
            self.assertEqual(bots.tick(), "trading")
            self.assertEqual(started, [("trading", "copy trading apps")])
            self.assertEqual(bots.view("trading")["asks"], [])

    def test_davids_build_request_is_built_without_review_when_code_mode_is_free(self):
        with tempfile.TemporaryDirectory() as folder:
            built, free = [], [False]
            lab = UpgradeLab(UpgradeStore(Path(folder) / "u.json"), brains=lambda: {}, build=lambda task: built.append(task) or "Started.",
                             auto=lambda: True, can_build=lambda: free[0])
            proposal = lab.queue_david("HQ restyle", "Restyle the HQ page with JoJo colours. " * 3, island="prime")
            self.assertTrue(proposal["david"])
            self.assertIsNone(lab.review_tick())             # never sent to the reviewer
            self.assertIsNone(lab.david_tick())              # Code mode busy: waits
            free[0] = True
            self.assertEqual(lab.david_tick(), proposal["id"])
            self.assertEqual(lab.store.get(proposal["id"])["status"], "building")
            self.assertTrue(built[0].startswith("HQ restyle"))   # the owner's own: no AUTO_GUARD in front


if __name__ == "__main__":
    unittest.main()
