import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from forgemind import agent
from forgemind.agent import DoxaTools, needs_tools
from forgemind.brain import Brain
from forgemind.claude_brain import ClaudeBrain, usage_of
from forgemind.cloud_brain import CloudBudget
from forgemind.config import Settings


def usage(searches=0):
    return SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=400,
                           cache_read_input_tokens=1000, server_tool_use=SimpleNamespace(web_search_requests=searches))


class FakeStream:
    def __init__(self, events, final):
        self.events, self.final = events, final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.final


def text_event(text):
    return SimpleNamespace(type="text", text=text)


def turn(stop_reason, blocks, events=(), searches=0):
    return FakeStream(list(events), SimpleNamespace(stop_reason=stop_reason, content=blocks, usage=usage(searches)))


class FakeClient:
    def __init__(self, turns):
        self.turns, self.calls = list(turns), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **params):
        self.calls.append({**params, "messages": list(params["messages"])})
        return self.turns.pop(0)


class FakeTools:
    specs = [{"name": "save_note", "description": "x", "input_schema": {"type": "object"}}]

    def __init__(self):
        self.calls = []

    def execute(self, name, data):
        self.calls.append((name, data))
        if data.get("fail"):
            raise ValueError("bad input")
        return "Saved to C:/notes/x.md"


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "anthropic-key.dpapi").write_bytes(b"x")
        self.budget = CloudBudget(root / "claude-budget.sqlite3", 2000)
        self.root = root

    def tearDown(self):
        self.dir.cleanup()

    def brain(self, turns):
        self.client = FakeClient(turns)
        return ClaudeBrain(self.root, self.budget, client_factory=lambda: self.client)

    def test_tool_call_then_answer(self):
        tool_use = SimpleNamespace(type="tool_use", id="t1", name="save_note", input={"title": "a", "markdown": "b"})
        search = SimpleNamespace(type="server_tool_use", name="web_search", input={"query": "viral products"})
        claude = self.brain([
            turn("tool_use", [SimpleNamespace(type="text", text="Looking."), tool_use],
                 [text_event("Looking."), SimpleNamespace(type="content_block_stop", content_block=search)], searches=3),
            turn("end_turn", [SimpleNamespace(type="text", text="Done.")], [text_event("Done.")]),
        ])
        tools, statuses = FakeTools(), []
        out = "".join(claude.agent_stream("sys", [{"role": "user", "content": "go"}], tools, on_status=statuses.append))
        self.assertEqual(out, "Looking.\n\nDone.")
        self.assertEqual(tools.calls, [("save_note", {"title": "a", "markdown": "b"})])
        second = self.client.calls[1]["messages"]
        self.assertEqual(second[-1]["content"][0]["tool_use_id"], "t1")
        self.assertFalse(second[-1]["content"][0]["is_error"])
        self.assertIn("Searching the web: viral products", statuses)
        names = [t.get("name") for t in self.client.calls[0]["tools"]]
        self.assertEqual(names[:2], ["web_search", "web_fetch"])
        self.assertEqual(self.client.calls[0]["system"][0]["cache_control"], {"type": "ephemeral"})
        # two calls settled to real cost (+3 searches at 1¢), not left at the 40¢ reservation
        self.assertLess(self.budget.summary()["reserved_cents"], 10)

    def test_text_around_searches_is_split_into_paragraphs(self):
        search = SimpleNamespace(type="server_tool_use", name="web_search", input={"query": "q"})
        claude = self.brain([turn("end_turn", [], [text_event("First pass."), SimpleNamespace(
            type="content_block_stop", content_block=search), text_event("Now reading.")])])
        out = "".join(claude.agent_stream("sys", [{"role": "user", "content": "go"}], FakeTools()))
        self.assertEqual(out, "First pass.\n\nNow reading.")

    def test_tool_errors_go_back_to_claude(self):
        bad = SimpleNamespace(type="tool_use", id="t1", name="save_note", input={"fail": True})
        claude = self.brain([turn("tool_use", [bad]), turn("end_turn", [], [text_event("Fixed.")])])
        out = "".join(claude.agent_stream("sys", [{"role": "user", "content": "go"}], FakeTools()))
        self.assertEqual(out, "Fixed.")
        result = self.client.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("bad input", result["content"])

    def test_pause_turn_continues_without_extra_message(self):
        claude = self.brain([turn("pause_turn", [SimpleNamespace(type="server_tool_use")]),
                             turn("end_turn", [], [text_event("ok")])])
        out = "".join(claude.agent_stream("sys", [{"role": "user", "content": "go"}], FakeTools()))
        self.assertEqual(out, "ok")
        self.assertEqual(self.client.calls[1]["messages"][-1]["role"], "assistant")

    def test_stop_and_refusal(self):
        stop = threading.Event()
        stop.set()
        claude = self.brain([turn("end_turn", [], [text_event("never")])])
        self.assertEqual("".join(claude.agent_stream("s", [{"role": "user", "content": "x"}], FakeTools(),
                                                     stop_event=stop)), "")
        claude = self.brain([turn("refusal", [], [])])
        self.assertIn("declined", "".join(claude.agent_stream("s", [{"role": "user", "content": "x"}], FakeTools())))

    def test_step_cap(self):
        loop = lambda: turn("tool_use", [SimpleNamespace(type="tool_use", id="t", name="save_note", input={})])
        claude = self.brain([loop() for _ in range(3)])
        out = "".join(claude.agent_stream("s", [{"role": "user", "content": "x"}], FakeTools(), max_calls=3))
        self.assertIn("most steps", out)

    def test_usage_counts_cache_and_searches(self):
        self.assertEqual(usage_of(usage(4)), {"input_tokens": 1000 + 500 + 100, "output_tokens": 200,
                                               "web_search_requests": 4})


class DoxaToolsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.app = SimpleNamespace(events=queue.Queue(), show_product_hunter=lambda: None,
                                   browser_controller=SimpleNamespace(running=False, start=mock.Mock()),
                                   show_browser=lambda task="": None)
        self.tools = DoxaTools(self.app, notes_dir=Path(self.dir.name))

    def tearDown(self):
        self.dir.cleanup()

    def test_open_panel_goes_through_the_window_thread(self):
        self.assertIn("Opened Product hunter", self.tools.execute("open_doxa_tool", {"tool": "Product hunter"}))
        self.assertEqual(self.app.events.get_nowait()[0], "ui")
        with self.assertRaises(ValueError):
            self.tools.execute("open_doxa_tool", {"tool": "Registry editor"})

    def test_every_listed_panel_exists_on_the_app(self):
        from app import ForgeMindApp
        for name, method in agent.PANELS.items():
            if method:
                self.assertTrue(hasattr(ForgeMindApp, method), name)

    def test_unknown_tool_and_bad_input(self):
        with self.assertRaises(ValueError):
            self.tools.execute("delete_files", {})
        with self.assertRaises(ValueError):
            self.tools.execute("supplier_quote_check", {"unit_price": "five", "shipping_per_unit": 1, "sell_price": 9})
        with self.assertRaises(ValueError):
            self.tools.execute("save_note", "not a dict")

    def test_quote_check(self):
        out = self.tools.execute("supplier_quote_check", {"unit_price": 5, "shipping_per_unit": 3, "sell_price": 25})
        self.assertIn("profit per order", out)

    def test_open_on_laptop_only_web_links(self):
        with mock.patch("webbrowser.open") as opened:
            self.tools.execute("open_on_laptop", {"url": "https://ads.tiktok.com/business/creativecenter"})
            with self.assertRaises(ValueError):
                self.tools.execute("open_on_laptop", {"url": "file:///C:/Windows/System32/cmd.exe"})
        self.assertEqual(opened.call_count, 1)

    def test_save_note_stays_in_the_notes_folder(self):
        out = self.tools.execute("save_note", {"title": "../../evil\\name", "markdown": "# hi"})
        path = Path(out.split("Saved to ", 1)[1])
        self.assertEqual(path.parent, Path(self.dir.name))
        self.assertTrue(path.read_text("utf-8").startswith("# ../../evil"))

    def test_browser_task_starts_once(self):
        self.assertIn("Started", self.tools.execute("start_browser_task", {"task": "Check the Meta Ad Library"}))
        self.app.browser_controller.start.assert_called_once_with("Check the Meta Ad Library")
        self.app.browser_controller.running = True
        self.assertIn("already running", self.tools.execute("start_browser_task", {"task": "again"}))


class RoutingTests(unittest.TestCase):
    def test_tool_requests_go_to_claude_agent(self):
        local = SimpleNamespace(loaded=True)
        claude = SimpleNamespace(loaded=True, provider_id="claude", display_name="Claude")
        openai = SimpleNamespace(loaded=True, provider_id="openai", display_name="OpenAI")
        brain = Brain(local, openai, claude)
        brain.tools = object()
        settings = Settings()
        self.assertIs(brain.pick("open my calendar", settings)[0], claude)
        self.assertIs(brain.pick("research how dropshippers market for 5 minutes", settings)[0], claude)
        self.assertIs(brain.pick("hi", settings)[0], local)
        self.assertTrue(needs_tools("check the meta ad library"))
        self.assertFalse(needs_tools("hello there"))


if __name__ == "__main__":
    unittest.main()
