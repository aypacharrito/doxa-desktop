"""Gemini + Kimi brains (fake HTTP, real DPAPI key files in a temp folder), chat prefixes, and the team spread across
models (research by Gemini-with-search + Claude, scripts split between Kimi and Claude and tagged, analyst Claude)."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from forgemind.brain import Brain
from forgemind.cloud_brain import CloudBudget
from forgemind.extra_brains import GeminiBrain, KimiBrain, OpenCodeGoBrain, choose_model
from forgemind.team import TeamRunner, TeamStore, staff_for

GEMINI_KEY = "AIza" + "x" * 35
KIMI_KEY = "sk-" + "k" * 40


class Response:
    def __init__(self, status=200, body=None, lines=()):
        self.status_code, self.ok, self._body, self._lines = status, 200 <= status < 300, body or {}, list(lines)

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


class Transport:
    def __init__(self, models, lines, status=200):
        self.models, self.lines, self.status, self.posts, self.gets = models, lines, status, [], []

    def get(self, url, **kw):
        self.gets.append((url, kw))
        return Response(body=self.models)

    def post(self, url, **kw):
        self.posts.append((url, kw))
        return Response(self.status, lines=self.lines)


def sse(*events):
    return [f"data: {json.dumps(e)}" for e in events] + ["data: [DONE]"]


class ExtraBrainTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def budget(self, name, cents=500):
        return CloudBudget(self.root / f"{name}.sqlite3", cents)

    def test_choose_model_prefers_newest_stable(self):
        names = ["gemini-2.5-flash", "gemini-3.0-flash-preview", "gemini-3.0-flash", "gemini-2.5-pro", "embedding-001"]
        self.assertEqual(choose_model(names, r"^gemini-(\d+(?:\.\d+)?)-flash"), "gemini-3.0-flash")
        self.assertEqual(choose_model(["kimi-k2-0905", "kimi-k2.5", "moonshot-v1-8k"], r"^kimi-k(\d+(?:\.\d+)?)"),
                         "kimi-k2.5")
        self.assertEqual(choose_model(["moonshot-v1-8k"], r"^kimi-k(\d+)", r"^moonshot-"), "moonshot-v1-8k")

    def test_gemini_streams_with_google_search_and_sources(self):
        models = {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                             {"name": "models/gemini-3.0-flash", "supportedGenerationMethods": ["generateContent"]},
                             {"name": "models/text-embedding", "supportedGenerationMethods": ["embedContent"]}]}
        lines = sse({"candidates": [{"content": {"parts": [{"text": "Hooks that "}]}}]},
                    {"candidates": [{"content": {"parts": [{"text": "work."}]},
                                     "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://a.test/x",
                                                                                         "title": "A"}}]}}],
                     "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 200}})
        transport = Transport(models, lines)
        brain = GeminiBrain(self.root, self.budget("g"), transport=transport)
        self.assertFalse(brain.loaded)
        with self.assertRaises(ValueError):
            brain.save_key("nope")
        brain.save_key(GEMINI_KEY)
        self.assertNotIn(GEMINI_KEY.encode(), brain.key_path.read_bytes())  # DPAPI-encrypted, never in clear
        text = "".join(brain.chat_stream("sys", [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"},
                                                 {"role": "user", "content": "go"}], search=True))
        self.assertTrue(text.startswith("Hooks that work."))
        self.assertIn("https://a.test/x", text)
        url, kw = transport.posts[0]
        self.assertIn("gemini-3.0-flash:streamGenerateContent", url)
        self.assertEqual(kw["headers"]["x-goog-api-key"], GEMINI_KEY)  # key in a header, not the URL
        self.assertNotIn(GEMINI_KEY, url)
        self.assertEqual(kw["json"]["tools"], [{"google_search": {}}])
        self.assertEqual([c["role"] for c in kw["json"]["contents"]], ["user", "model", "user"])
        self.assertEqual(kw["json"]["systemInstruction"]["parts"][0]["text"], "sys")
        self.assertEqual(brain.model_name, "gemini-3.0-flash")
        self.assertGreater(brain.budget.summary()["actual_usd"], 0)

    def test_kimi_streams_openai_style_and_reports_errors_plainly(self):
        models = {"data": [{"id": "moonshot-v1-8k"}, {"id": "kimi-k2-thinking"}, {"id": "kimi-k2-0905-preview"},
                           {"id": "kimi-k2.5"}]}
        lines = sse({"choices": [{"delta": {"content": "Draft "}}]}, {"choices": [{"delta": {"content": "one."}}]},
                    {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 10}})
        transport = Transport(models, lines)
        brain = KimiBrain(self.root, self.budget("k"), transport=transport)
        brain.save_key(KIMI_KEY)
        self.assertEqual("".join(brain.chat_stream("sys", [{"role": "user", "content": "hi"}])), "Draft one.")
        url, kw = transport.posts[0]
        self.assertTrue(url.endswith("/chat/completions"))
        self.assertEqual(kw["json"]["model"], "kimi-k2.5")  # newest K model, not the thinking variant
        self.assertEqual(kw["json"]["messages"][0], {"role": "system", "content": "sys"})
        self.assertTrue(kw["json"]["stream"])
        for status, words in ((401, "rejected the key"), (429, "out of credit")):
            bad = KimiBrain(self.root, self.budget(f"k{status}"), model="kimi-k2.5", transport=Transport({}, [], status))
            with self.assertRaises(ValueError) as caught:
                "".join(bad.chat_stream("s", [{"role": "user", "content": "x"}]))
            self.assertIn(words, str(caught.exception))
        brain.forget_key()
        self.assertFalse(brain.loaded)

    def test_opencode_go_uses_its_endpoint_and_prefers_kimi(self):
        models = {"data": [{"id": "deepseek-v4-flash"}, {"id": "qwen3.8-max"}, {"id": "kimi-k3"}, {"id": "kimi-k2.6"}]}
        lines = sse({"choices": [{"delta": {"content": "Go."}}]})
        transport = Transport(models, lines)
        brain = OpenCodeGoBrain(self.root, self.budget("o", 6000), transport=transport)
        brain.save_key("oc-" + "z" * 30)
        self.assertEqual("".join(brain.chat_stream("s", [{"role": "user", "content": "hi"}])), "Go.")
        self.assertEqual(transport.gets[0][0], "https://opencode.ai/zen/go/v1/models")
        url, kw = transport.posts[0]
        self.assertEqual(url, "https://opencode.ai/zen/go/v1/chat/completions")
        self.assertEqual(kw["json"]["model"], "kimi-k3")
        self.assertEqual(choose_model(["deepseek-v4", "qwen3"], *OpenCodeGoBrain.PREFER), "deepseek-v4")
        limited = OpenCodeGoBrain(self.root, self.budget("o2"), model="kimi-k3", transport=Transport({}, [], 429))
        with self.assertRaises(ValueError) as caught:
            "".join(limited.chat_stream("s", [{"role": "user", "content": "x"}]))
        self.assertIn("usage limit", str(caught.exception))

    def test_budget_cap_stops_calls(self):
        brain = KimiBrain(self.root, self.budget("cap", cents=1), model="kimi-k2.5", transport=Transport({}, []))
        brain.save_key(KIMI_KEY)
        with self.assertRaises(ValueError):
            "".join(brain.chat_stream("s", [{"role": "user", "content": "x"}]))


class FakeChat:
    def __init__(self, provider, reply="ok", agent=False):
        self.provider_id, self.display_name, self.loaded, self.reply, self.calls = provider, provider.title(), True, reply, []
        self.model_name = provider
        if agent:
            self.agent_stream = self._agent

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000, **kw):
        self.calls.append(("chat", messages[-1]["content"][:40], kw))
        yield self.reply() if callable(self.reply) else self.reply

    def _agent(self, system, messages, tools, **kw):
        self.calls.append(("agent", messages[-1]["content"][:40], {}))
        yield self.reply() if callable(self.reply) else self.reply


class RoutingTests(unittest.TestCase):
    def brain(self, **extra):
        local = SimpleNamespace(loaded=True, stream=lambda *a, **k: iter(["local"]))
        brain = Brain(local, None, None)
        brain.extra = extra
        return brain

    def test_prefixes_and_modes(self):
        gemini, kimi = FakeChat("gemini", "g"), FakeChat("kimi", "k")
        brain = self.brain(gemini=gemini, kimi=kimi)
        settings = SimpleNamespace(brain_mode="auto", cloud_preference="claude")
        self.assertIs(brain.pick("gemini: what's trending", settings)[0], gemini)
        self.assertIs(brain.pick("Kimi, write 3 hooks", settings)[0], kimi)
        go = FakeChat("opencode", "o")
        brain.extra["opencode"] = go
        self.assertIs(brain.pick("opencode: draft a caption", settings)[0], go)
        self.assertEqual(brain.clouds(settings), [go, kimi, gemini])
        del brain.extra["opencode"]
        self.assertIs(brain.pick("anything", SimpleNamespace(brain_mode="kimi", cloud_preference="claude"))[0], kimi)
        self.assertEqual(brain.clouds(settings), [kimi, gemini])  # last-resort fallbacks when nothing else is connected
        missing = self.brain()
        chosen, _text, reason = missing.pick("gemini: hi", settings)
        self.assertIs(chosen, missing.local)
        self.assertIn("Gemini isn't connected", reason)

    def test_every_cloud_brain_gets_the_shared_core_rules_for_business_work(self):
        from unittest import mock
        kimi = FakeChat("kimi", "k")
        seen = []
        kimi.chat_stream = lambda system, messages, **kw: (seen.append(system), iter(["k"]))[1]
        brain = self.brain(kimi=kimi)
        settings = SimpleNamespace(brain_mode="auto", cloud_preference="claude", display_name="", personal_brief="")
        with mock.patch("forgemind.knowledge.core_rules", return_value="1. Distribution beats product."):
            list(brain.stream([], "kimi: write marketing hooks for my song", settings, [], []))
            list(brain.stream([], "kimi: hi", settings, [], []))
        self.assertIn("Distribution beats product", seen[0])
        self.assertNotIn("Distribution beats product", seen[1])  # small talk stays light

    def test_gemini_searches_google_for_research_messages(self):
        gemini = FakeChat("gemini", "g")
        brain = self.brain(gemini=gemini)
        settings = SimpleNamespace(brain_mode="auto", cloud_preference="claude", display_name="", personal_brief="")
        list(brain.stream([], "gemini: research what's trending for night drive songs", settings, [], []))
        list(brain.stream([], "gemini: hi there", settings, [], []))
        self.assertEqual(gemini.calls[0][2], {"search": True})
        self.assertEqual(gemini.calls[1][2], {})


SCRIPTS = lambda n, tag: json.dumps([{"angle": f"{tag}{i}", "hook": f"hook {tag}{i}", "script": "s", "cta": "c"}
                                     for i in range(n)])


class SpreadTeamTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.store = TeamStore(root / "team.json", work_root=root / "Doxa Team")
        self.store.create_campaign("Song", "1,000 saves", "night drivers")

    def tearDown(self):
        self.dir.cleanup()

    def run_room(self, runner, room):
        finished = threading.Event()
        runner.on_change = lambda: finished.set() if room not in runner.busy else None
        runner.start(room)
        self.assertTrue(finished.wait(5))
        return self.store.data["workers"][room]

    def test_staff_and_owner_override(self):
        brains = {"claude": 1, "gemini": 2, "kimi": 3, "openai": 4}
        self.assertEqual([n for n, _ in staff_for("research", brains)], ["gemini", "claude"])
        self.assertEqual([n for n, _ in staff_for("writers", brains)], ["kimi", "claude"])
        self.assertEqual([n for n, _ in staff_for("analyst", brains)], ["claude"])
        self.assertEqual([n for n, _ in staff_for("writers", brains, "openai")], ["openai"])
        self.assertEqual([n for n, _ in staff_for("writers", {"gemini": 2}, "kimi")], ["gemini"])  # pick not connected
        self.assertEqual(staff_for("mailroom", brains), [])
        both = {"claude": 1, "kimi": 3, "opencode": 5}  # flat-fee OpenCode Go writes; pay-per-use Kimi isn't doubled up
        self.assertEqual([n for n, _ in staff_for("writers", both)], ["opencode", "claude"])

    def test_research_and_scripts_spread_across_models(self):
        gemini = FakeChat("gemini", "Google says https://g.test/1 and https://g.test/2")
        claude_replies = iter(["Deep read https://c.test/1", SCRIPTS(3, "C")])
        claude = FakeChat("claude", lambda: next(claude_replies), agent=True)
        kimi = FakeChat("kimi", SCRIPTS(3, "K"))
        runner = TeamRunner(self.store, lambda: {"claude": claude, "gemini": gemini, "kimi": kimi},
                            rules=lambda: "rules")
        self.assertEqual(runner.models()["research"], ["Iris (Gemini)", "Astra (Claude)"])
        worker = self.run_room(runner, "research")
        self.assertEqual(worker["status"], "done", worker)
        self.assertIn("Iris (Gemini) + Astra (Claude)", worker["detail"])
        self.assertEqual(gemini.calls[0][2], {"search": True})
        self.assertEqual(claude.calls[0][0], "agent")
        brief = self.store.campaign()["brief"]
        self.assertIn("## Researcher: Iris (Gemini)", brief)
        self.assertIn("## Researcher: Astra (Claude)", brief)
        self.assertEqual(self.store.campaign()["sources"], 3)
        worker = self.run_room(runner, "writers")
        self.assertEqual(worker["status"], "done", worker)
        items = self.store.items(stage="waiting")
        self.assertEqual(sorted(i["model"] for i in items), ["Astra (Claude)"] * 3 + ["Kiro (Kimi)"] * 3)
        self.assertIn("3 by Kiro (Kimi), 3 by Astra (Claude)", worker["detail"])

    def test_team_workers_get_the_rules_and_shipping_counts_by_platform(self):
        systems = []
        kimi = FakeChat("kimi", SCRIPTS(2, "K"))
        kimi.chat_stream = lambda system, messages, **kw: (systems.append(system), iter([SCRIPTS(2, "K")]))[1]
        runner = TeamRunner(self.store, lambda: {"kimi": kimi}, rules=lambda: "1. Humans approve; AI works.")
        self.store.campaign()["brief"] = "brief"
        self.run_room(runner, "writers")
        self.assertIn("Humans approve; AI works.", systems[0])
        items = self.store.items()
        for item, (platform, link) in zip(items, [("TikTok", "https://tiktok.com/@d/1"), ("Instagram", "https://instagram.com/reel/x")]):
            self.store.decide(item["id"], True)
            self.store.mark_filmed(item["id"])
            self.store.mark_posted(item["id"], platform, link)
        self.assertEqual(self.store.platforms(), {"tiktok": 1, "reels": 1, "shorts": 0, "other": 0})

    def test_one_failing_model_does_not_sink_the_room(self):
        class Broken(FakeChat):
            def chat_stream(self, *a, **k):
                raise ValueError("Gemini is rate-limiting or out of credit/free quota right now.")
                yield ""
        claude = FakeChat("claude", "Deep read https://c.test/1", agent=True)
        runner = TeamRunner(self.store, lambda: {"claude": claude, "gemini": Broken("gemini")})
        worker = self.run_room(runner, "research")
        self.assertEqual(worker["status"], "done")
        self.assertIn("rate-limiting", worker["detail"])
        self.assertNotIn("Researcher:", self.store.campaign()["brief"])  # only one brief came back


if __name__ == "__main__":
    unittest.main()
