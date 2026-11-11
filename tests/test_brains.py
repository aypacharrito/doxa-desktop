"""1.13: several AI brains (local, OpenAI, Claude), one $25/month budget, Autopilot leads review."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from forgemind.autopilot import Autopilot
from forgemind.brain import Brain, effort_for, redact, wants_cloud
from forgemind.claude_brain import PRICE, ClaudeBrain
from forgemind.cloud_brain import CloudBrain, CloudBudget
from forgemind.config import Settings
from forgemind.task_queue import TaskQueue


class FakeLocal:
    provider_id, display_name, local = "llama.cpp", "Local", True

    def __init__(self, loaded=True):
        self.loaded, self.calls = loaded, []

    def stream(self, history, text, settings, memories, web, stop_event=None):
        self.calls.append(text)
        yield "local answer"


class FakeCloud:
    def __init__(self, name, loaded=True, error=None, chunks=("cloud ", "answer"), fail_after=None):
        self.provider_id, self.display_name, self.model_name = name, name.title(), name + "-model"
        self.loaded, self.error, self.chunks, self.fail_after, self.requests = loaded, error, chunks, fail_after, []

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000):
        self.requests.append((system, messages, effort))
        if self.error and self.fail_after is None:
            raise self.error
        for index, chunk in enumerate(self.chunks):
            if self.fail_after is not None and index == self.fail_after:
                raise self.error
            yield chunk


def make_brain(local=True, claude=True, openai=True, **cloud_kw):
    lc = FakeLocal(local)
    cl = FakeCloud("claude", claude, **cloud_kw)
    oa = FakeCloud("openai", openai)
    return Brain(lc, oa, cl, build_context=lambda m, w: "MEMORY: likes tacos"), lc, cl, oa


class RouterTests(unittest.TestCase):
    def test_redaction(self):
        self.assertEqual(redact("call Ana at (818) 555-0142 or ana@x.com"), "call Ana at [phone] or [email]")

    def test_auto_keeps_quick_things_local_and_sends_hard_work_to_the_preferred_cloud(self):
        brain, lc, cl, oa = make_brain()
        settings = Settings()
        self.assertIs(brain.pick("what time is it?", settings)[0], lc)
        self.assertIs(brain.pick("write a python script to rename my files", settings)[0], cl)
        self.assertIs(brain.pick("plan my marketing for this week", Settings(cloud_preference="openai"))[0], oa)
        self.assertIs(brain.pick("x" * 400, settings)[0], cl)
        self.assertTrue(wants_cloud("research the best lead sources") and not wants_cloud("hey doxa how are you"))
        self.assertEqual(effort_for("debug this traceback"), "medium")
        self.assertEqual(effort_for("write a caption"), "low")

    def test_modes_and_prefixes(self):
        brain, lc, cl, oa = make_brain()
        self.assertIs(brain.pick("write code", Settings(brain_mode="local"))[0], lc)
        self.assertIs(brain.pick("hi", Settings(brain_mode="openai"))[0], oa)
        picked, text, _ = brain.pick("gpt: what's 2+2", Settings())
        self.assertIs(picked, oa)
        self.assertEqual(text, "what's 2+2")
        self.assertIs(brain.pick("Claude, hi there", Settings())[0], cl)
        self.assertIs(brain.pick("local: write a long python program", Settings())[0], lc)

    def test_missing_brains(self):
        brain, lc, cl, oa = make_brain(claude=False)
        self.assertIs(brain.pick("write a plan", Settings())[0], oa)       # falls to the other cloud
        picked, _, reason = brain.pick("claude: hi", Settings())
        self.assertIs(picked, lc)
        self.assertIn("isn't connected", reason)
        brain, lc, cl, oa = make_brain(local=False)
        self.assertIs(brain.pick("hi", Settings())[0], cl)                # no local model: use the cloud
        brain, *_ = make_brain(local=False, claude=False, openai=False)
        self.assertFalse(brain.ready(Settings()))

    def test_cloud_gets_context_with_contact_details_masked(self):
        brain, lc, cl, oa = make_brain()
        history = [{"role": "assistant", "content": "Hello!"},
                   {"role": "user", "content": "my client Ana, 818-555-0142, ana@example.com"},
                   {"role": "assistant", "content": "Got it."}]
        out = "".join(brain.stream(history, "write a follow-up email plan", Settings(), [], []))
        self.assertEqual(out, "cloud answer")
        system, messages, effort = cl.requests[0]
        self.assertIn("MEMORY: likes tacos", system)
        self.assertEqual(messages[0]["role"], "user")                    # opening assistant turn dropped
        flat = json.dumps(messages)
        self.assertNotIn("555-0142", flat)
        self.assertNotIn("ana@example.com", flat)
        self.assertIn("[phone]", flat)
        self.assertEqual(messages[-1], {"role": "user", "content": "write a follow-up email plan"})
        self.assertEqual(brain.last["provider"], "claude")

    def test_failure_before_any_words_switches_to_the_next_brain(self):
        brain, lc, cl, oa = make_brain(error=ValueError("Doxa reached its $25 monthly cloud AI allowance."))
        out = "".join(brain.stream([], "write a marketing plan", Settings(), [], []))
        self.assertIn("$25 monthly", out)
        self.assertIn("Switching to Openai", out)
        self.assertTrue(out.endswith("cloud answer"))
        self.assertEqual(brain.last["provider"], "openai")

    def test_every_cloud_failing_answers_locally(self):
        brain, lc, cl, oa = make_brain(error=ValueError("Doxa reached its $25 monthly cloud AI allowance."))
        oa.error = ValueError("Couldn't reach OpenAI.")
        out = "".join(brain.stream([], "write a marketing plan", Settings(), [], []))
        self.assertTrue(out.endswith("local answer"))
        self.assertIn("Answering with the local model", out)
        self.assertEqual(brain.last["provider"], "local")

    def test_chat_lane_stays_on_the_pc_and_uses_free_brains_only_without_it(self):
        brain, lc, cl, oa = make_brain()
        out = "".join(brain.stream([], "write a marketing plan", Settings(), [], [], lane="chat"))
        self.assertEqual(out, "local answer")
        self.assertEqual(cl.requests, [])
        self.assertEqual(oa.requests, [])
        lc.loaded = False
        free = FakeCloud("opencode")
        brain.extra = {"opencode": free}
        out = "".join(brain.stream([], "hi", Settings(), [], [], lane="chat"))
        self.assertEqual(out, "cloud answer")
        self.assertEqual(len(free.requests), 1)
        self.assertEqual(cl.requests, [])  # never a paid brain in Chat
        self.assertEqual(brain.pick("claude: hi", Settings(), "chat")[0], cl)  # asking by name still works

    def test_work_lane_uses_paid_brains_and_rests_one_that_ran_out(self):
        brain, lc, cl, oa = make_brain(error=ValueError("Kimi is out of credit."))
        now = [1000.0]
        brain.clock = lambda: now[0]
        self.assertEqual(brain.pick("hi", Settings(), "work")[0], cl)  # quick things too: Work = paid
        out = "".join(brain.stream([], "hi", Settings(), [], [], lane="work"))
        self.assertTrue(out.endswith("cloud answer"))
        self.assertEqual(len(cl.requests), 1)
        "".join(brain.stream([], "hi again", Settings(), [], [], lane="work"))
        self.assertEqual(len(cl.requests), 1)  # resting: not tried again
        self.assertEqual(len(oa.requests), 2)
        now[0] += 3601
        self.assertEqual(brain.pick("hi", Settings(), "work")[0], cl)  # back after an hour
        cl.loaded = oa.loaded = False
        chosen, _, reason = brain.pick("hi", Settings(), "work")
        self.assertIs(chosen, lc)
        self.assertIn("no paid AI", reason)

    def test_a_plain_error_does_not_rest_the_brain(self):
        brain, lc, cl, oa = make_brain(error=ValueError("Claude returned a strange reply."))
        "".join(brain.stream([], "write a plan", Settings(), [], [], lane="work"))
        self.assertEqual(brain.resting, {})

    def test_failure_mid_answer_is_reported_not_hidden(self):
        brain, *_ = make_brain(error=ValueError("connection dropped"), fail_after=1)
        with self.assertRaises(ValueError):
            list(brain.stream([], "write a plan", Settings(), [], []))


class FakeStream:
    def __init__(self, texts, stop_reason="end_turn", usage=(1000, 200)):
        self.texts, self.stop_reason, self.usage = texts, stop_reason, usage

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(self.texts)

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason,
                               usage=SimpleNamespace(input_tokens=self.usage[0], output_tokens=self.usage[1]))


class FakeAnthropic:
    def __init__(self, stream):
        self.calls = []
        outer = self

        class Messages:
            def stream(self, **kwargs):
                outer.calls.append(kwargs)
                return stream
        self.beta = SimpleNamespace(messages=Messages())


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.budget = CloudBudget(self.root / "budget.db", limit_cents=2500)
        (self.root / "anthropic-key.dpapi").write_bytes(b"encrypted")

    def tearDown(self):
        self.tmp.cleanup()

    def brain(self, stream):
        client = FakeAnthropic(stream)
        return ClaudeBrain(self.root, self.budget, client_factory=lambda: client), client

    def test_streams_text_and_settles_the_budget_to_real_cost(self):
        brain, client = self.brain(FakeStream(["Hel", "lo"]))
        self.assertEqual("".join(brain.chat_stream("sys", [{"role": "user", "content": "hi"}], effort="medium")), "Hello")
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["output_config"], {"effort": "medium"})
        self.assertEqual(call["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", call["betas"])
        self.assertNotIn("thinking", call)  # adaptive thinking is always on for Opus 5.5
        expected = (1000 * PRICE[0] + 200 * PRICE[1]) / 1_000_000
        self.assertAlmostEqual(self.budget.summary()["actual_usd"], expected)
        self.assertAlmostEqual(self.budget.summary()["reserved_cents"], round(expected * 100, 2))  # real cost counts

    def test_refusal_and_cut_short_are_explained(self):
        brain, _ = self.brain(FakeStream(["No"], stop_reason="refusal"))
        self.assertIn("declined", "".join(brain.chat_stream("s", [{"role": "user", "content": "x"}])))
        brain, _ = self.brain(FakeStream(["Long"], stop_reason="max_tokens"))
        self.assertIn("cut short", "".join(brain.chat_stream("s", [{"role": "user", "content": "x"}])))

    def test_stop_keeps_the_reservation(self):
        stop = threading.Event()
        stop.set()
        brain, _ = self.brain(FakeStream(["a", "b"]))
        self.assertEqual(list(brain.chat_stream("s", [{"role": "user", "content": "x"}], stop_event=stop)), [])
        self.assertEqual(self.budget.summary()["reserved_cents"], 12)

    def test_budget_cap_fails_closed(self):
        tight = CloudBudget(self.root / "tight.db", limit_cents=10)
        brain = ClaudeBrain(self.root, tight, client_factory=lambda: FakeAnthropic(FakeStream(["x"])))
        with self.assertRaises(ValueError) as caught:
            list(brain.chat_stream("s", [{"role": "user", "content": "x"}]))
        self.assertIn("$0 monthly", str(caught.exception))

    def test_key_format_is_checked_before_saving(self):
        brain = ClaudeBrain(self.root, self.budget)
        for bad in ["", "sk-proj-123", "sk-ant-short", "sk-ant-" + "a" * 40 + " b"]:
            with self.assertRaises(ValueError):
                brain.save_key(bad)

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_key_is_stored_encrypted(self):
        brain = ClaudeBrain(self.root, self.budget)
        key = "sk-ant-api03-" + "x" * 60
        brain.save_key(key)
        self.assertNotIn(key.encode(), brain.key_path.read_bytes())
        brain.forget_key()
        self.assertFalse(brain.key_path.exists())


class OpenAIStreamTests(unittest.TestCase):
    def test_streams_deltas_and_settles_cost(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "openai-key.dpapi").write_bytes(b"x")
        lines = [b'data: {"type":"response.output_text.delta","delta":"Hi "}', b"",
                 b'data: {"type":"response.output_text.delta","delta":"there"}',
                 b'data: {"type":"response.completed","response":{"usage":{"input_tokens":2000,"output_tokens":100}}}']
        sent = {}

        def transport(url, **kwargs):
            sent.update(kwargs)
            return SimpleNamespace(ok=True, status_code=200, iter_lines=lambda: iter(lines))
        import forgemind.cloud_brain as cb
        original = cb.windows_key
        cb.windows_key = lambda data, encrypt: b"sk-test"
        try:
            brain = CloudBrain(root, transport=transport, limit_cents=2500)
            out = "".join(brain.chat_stream("SYSTEM", [{"role": "user", "content": "hello"}]))
        finally:
            cb.windows_key = original
        self.assertEqual(out, "Hi there")
        self.assertTrue(sent["stream"])
        self.assertEqual(sent["json"]["instructions"], "SYSTEM")
        self.assertEqual(sent["json"]["input"], [{"role": "user", "content": "hello"}])
        self.assertTrue(sent["json"]["stream"])
        self.assertNotIn("tools", sent["json"])
        self.assertEqual(brain.budget.summary()["limit_cents"], 2500)
        self.assertLess(brain.budget.summary()["reserved_cents"], 1)  # settled to the real fraction of a cent


class AutopilotLeadsTests(unittest.TestCase):
    def test_leads_prompt_uses_aggregates_only(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "pacifica-summary.json").write_text(json.dumps(
            {"contacts": 412, "do_not_call": 9, "call_records": 1880, "names": ["Ana Ruiz"], "checked_at": "x"}))
        app = SimpleNamespace(task_queue=TaskQueue(root / "jobs.db"), cloud=SimpleNamespace(root=root))
        prompt = Autopilot(app).prompt("leads")
        self.assertIn('"contacts": 412', prompt)
        self.assertNotIn("Ana Ruiz", prompt)
        self.assertIn("TCPA", prompt)
        self.assertIn("never bind", prompt.lower().replace("never bind or quote", "never bind"))

    def test_listening_does_not_block_scheduled_work(self):
        from forgemind import autopilot
        source = Path(autopilot.__file__).read_text(encoding="utf-8")
        self.assertNotIn("getattr(getattr(self.app,'voice',None),'enabled',False)", source)


if __name__ == "__main__":
    unittest.main()


class PrivateGpuTests(unittest.TestCase):
    """the owner 2026-11-09: "this idea, I just want it to stay in the GPU"."""

    def test_private_messages_go_to_the_gpu_and_never_into_cloud_history(self):
        from forgemind.brain import Brain, PRIVATE
        brain = Brain.__new__(Brain)
        brain.build_context = lambda memories, web: ""
        self.assertTrue(PRIVATE.match("private: my Web Studio pricing idea"))
        self.assertTrue(PRIVATE.match("gpu, keep this one"))
        history = [{"role": "user", "content": "private: my secret plan is X"},
                   {"role": "assistant", "content": "Noted, X stays here."},
                   {"role": "user", "content": "what's the weather"},
                   {"role": "assistant", "content": "Sunny."}]
        from types import SimpleNamespace
        settings = SimpleNamespace(personal_brief="", owner_name="", brain_mode="auto")
        from unittest import mock
        with mock.patch("forgemind.brain.personal_context", return_value=""),                 mock.patch("forgemind.brain.system_prompt_for", return_value="sys"):
            system, turns = brain._cloud_request(history, "next question", settings, [], [])
        sent = " ".join(t["content"] for t in turns)
        self.assertNotIn("secret plan", sent)
        self.assertNotIn("X stays here", sent)
        self.assertIn("Sunny.", sent)
