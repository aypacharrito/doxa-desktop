import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from forgemind import code_mode
from forgemind.agent import DoxaTools, needs_tools
from forgemind.cloud_brain import CloudBudget
from forgemind.code_mode import CodeRunner, code_request, job_folder, parse_claude, parse_codex


class FakeProcess:
    def __init__(self, lines, code=0, gate=None):
        self.lines, self.code, self.gate, self.pid = lines, code, gate, 4242
        self.stdout = self._read()

    def _read(self):
        for line in self.lines:
            yield line + "\n"
        if self.gate is not None:
            self.gate.wait(5)

    def wait(self):
        return self.code

    def kill(self):
        if self.gate is not None:
            self.gate.set()


CODEX_LINES = [
    json.dumps({"type": "thread.started"}),
    json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "dir"}}),
    json.dumps({"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "C:/x/app.py"}]}}),
    json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Built app.py; run it with python."}}),
    json.dumps({"type": "turn.completed", "usage": {}}),
]
CLAUDE_LINES = [
    json.dumps({"type": "system", "subtype": "init"}),
    json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Looking at the binary."},
        {"type": "tool_use", "name": "Bash", "input": {"command": "strings game.exe"}}]}}),
    json.dumps({"type": "result", "is_error": False, "result": "Save format documented in FORMAT.md.",
                "total_cost_usd": 0.42}),
]


class RequestTests(unittest.TestCase):
    def test_prefixes_and_phrases(self):
        self.assertEqual(code_request("code: make a todo app"), ("auto", "make a todo app"))
        self.assertEqual(code_request("Code mode: fix C:\\proj"), ("auto", "fix C:\\proj"))
        self.assertEqual(code_request("codex: build a scraper"), ("codex", "build a scraper"))
        self.assertEqual(code_request("Claude Code: refactor this"), ("claude", "refactor this"))
        self.assertEqual(code_request("reverse engineer C:\\Games\\x.exe")[0], "auto")
        for text in ("claude: what's the weather", "code", "what is code mode?", "my code is broken",
                     "how do people reverse engineer games?", "code:   "):
            self.assertIsNone(code_request(text), text)

    def test_job_folder(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(code_mode, "WORK_ROOT", Path(root) / "Doxa Code"):
            made = job_folder(str(Path(root) / "new" / "proj"), "x")
            self.assertTrue(made.is_dir())
            target = Path(root) / "tool.exe"
            target.write_bytes(b"MZ")
            self.assertEqual(job_folder(None, f"reverse engineer {target} please"), Path(root))
            fresh = job_folder(None, "Make a budget tracker!")
            self.assertEqual(fresh.parent, Path(root) / "Doxa Code")
            self.assertIn("make-a-budget-tracker", fresh.name)

    def test_parsers(self):
        self.assertEqual(parse_codex(CODEX_LINES[1]), ("step", "Running: dir"))
        self.assertEqual(parse_codex(CODEX_LINES[3])[0], "say")
        self.assertEqual(parse_codex(json.dumps({"type": "turn.failed", "error": {"message": "quota"}})), ("error", "quota"))
        self.assertIsNone(parse_codex("not json"))
        steps = parse_claude(CLAUDE_LINES[1])
        self.assertEqual(steps[1], ("step", "Bash: strings game.exe", 0.0))
        self.assertEqual(parse_claude(CLAUDE_LINES[2]), [("final", "Save format documented in FORMAT.md.", 0.42)])

    def test_tool_words_route_to_claude(self):
        self.assertTrue(needs_tools("reverse engineer this program"))
        self.assertTrue(needs_tools("rename the files in my downloads folder"))
        self.assertFalse(needs_tools("I'm going for a run"))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.calls = []
        self.patch = mock.patch.object(code_mode, "WORK_ROOT", self.root / "Doxa Code")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def runner(self, lines, key="sk-ant-test", budget=None, gate=None, code=0):
        def popen(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return FakeProcess(lines, code, gate)
        return CodeRunner(self.root, claude_key=lambda: key, budget=budget, popen=popen,
                          finders={"codex": lambda: "C:/codex.exe", "claude": lambda: "C:/claude.exe"})

    def run_job(self, runner, **kwargs):
        done = threading.Event()
        result = {}
        steps = []
        job = runner.start(kwargs.pop("task", "build it"), on_step=steps.append,
                           on_done=lambda j: (result.setdefault("job", j), done.set()), **kwargs)
        self.assertTrue(done.wait(5))
        return job, result["job"], steps

    def test_codex_job_runs_with_full_access_and_reports(self):
        runner = self.runner(CODEX_LINES)
        job, finished, steps = self.run_job(runner, folder=str(self.root / "proj"))
        argv, kwargs = self.calls[0]
        self.assertEqual(job.engine, "codex")
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertEqual(argv[argv.index("-C") + 1], str(self.root / "proj"))
        self.assertIn("build it", argv[-1])
        self.assertEqual(kwargs["cwd"], str(self.root / "proj"))
        self.assertEqual(finished.status, "done")
        self.assertIn("Running: dir", steps)
        self.assertIn("Built app.py", finished.report())
        self.assertTrue(finished.log_path.read_text("utf-8").startswith("{"))
        self.assertFalse(runner.running)

    def test_claude_job_uses_key_in_env_and_budget(self):
        budget = CloudBudget(self.root / "claude-budget.sqlite3", 2000)
        runner = self.runner(CLAUDE_LINES, budget=budget)
        job, finished, steps = self.run_job(runner, engine="claude", max_usd=3.0)
        argv, kwargs = self.calls[0]
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "3.00")
        self.assertEqual(kwargs["env"]["ANTHROPIC_API_KEY"], "sk-ant-test")
        self.assertNotIn("sk-ant-test", " ".join(argv))
        self.assertEqual(finished.summary, "Save format documented in FORMAT.md.")
        self.assertIn("$0.42", finished.report())
        self.assertAlmostEqual(budget.summary()["reserved_cents"], 42, places=1)

    def test_engine_choice(self):
        self.assertEqual(self.runner([]).pick("auto")[0], "codex")
        no_key = self.runner([], key=None)
        self.assertEqual(list(no_key.available()), ["codex"])
        with self.assertRaises(ValueError):
            no_key.pick("claude")
        nothing = CodeRunner(self.root, finders={"codex": lambda: None, "claude": lambda: None})
        with self.assertRaises(ValueError):
            nothing.pick("auto")

    def test_spent_budget_blocks_claude(self):
        budget = CloudBudget(self.root / "b.sqlite3", 10)
        with self.assertRaises(ValueError):
            self.runner(CLAUDE_LINES, budget=budget).start("x", engine="claude")
        self.assertEqual(self.calls, [])

    def test_one_job_at_a_time_and_stop(self):
        gate = threading.Event()
        runner = self.runner(CODEX_LINES[:2], gate=gate)
        done = threading.Event()
        runner.start("long job", on_done=lambda job: done.set())
        with self.assertRaises(ValueError):
            runner.start("another")
        with mock.patch("subprocess.run", side_effect=lambda *a, **k: gate.set()):
            self.assertTrue(runner.stop())
        self.assertTrue(done.wait(5))
        self.assertEqual(runner.job.status, "stopped")

    def test_failure_is_reported(self):
        lines = [json.dumps({"type": "turn.failed", "error": {"message": "usage limit reached"}})]
        _, finished, _ = self.run_job(self.runner(lines, code=1))
        self.assertEqual(finished.status, "failed")
        self.assertIn("usage limit reached", finished.report())


class FullAccessToolTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        ran = []

        class Events:
            def put(self, item):  # run window callbacks right away, like the Tk loop would
                if item[0] == "ui":
                    item[1]()
        self.started = []
        self.app = SimpleNamespace(events=Events(), start_code_job=lambda *a, **k: (self.started.append((a, k)),
                                                                                    "Code mode started with Codex.")[1])
        self.tools = DoxaTools(self.app, notes_dir=self.root / "notes")
        self.ran = ran

    def tearDown(self):
        self.dir.cleanup()

    def test_write_read_with_backup(self):
        target = self.root / "deep" / "file.txt"
        with mock.patch.object(code_mode, "BACKUPS", self.root / "_backups"):
            self.assertIn("Saved", self.tools.execute("write_file", {"path": str(target), "content": "one"}))
            out = self.tools.execute("write_file", {"path": str(target), "content": "two"})
        self.assertIn("old version was copied", out)
        self.assertEqual(self.tools.execute("read_file", {"path": str(target)}), "two")
        backups = list((self.root / "_backups").rglob("*file.txt"))
        self.assertEqual(backups[0].read_text("utf-8"), "one")

    def test_run_command(self):
        out = self.tools.execute("run_command", {"command": "Write-Output doxa-ok", "folder": str(self.root)})
        self.assertIn("Exit code 0", out)
        self.assertIn("doxa-ok", out)

    def test_open_anything_and_code_job(self):
        with mock.patch("os.startfile", create=True) as opened:
            self.tools.execute("open_anything", {"target": str(self.root)})
        opened.assert_called_once_with(str(self.root))
        out = self.tools.execute("run_code_job", {"task": "decompile it", "engine": "codex"})
        self.assertIn("Code mode started", out)
        args, kwargs = self.started[0]
        self.assertEqual(args[1:4], ("decompile it", None, "codex"))
        self.assertFalse(kwargs["post"])
        with self.assertRaises(ValueError):
            self.tools.execute("run_code_job", {"task": "x", "engine": "gpt"})


if __name__ == "__main__":
    unittest.main()
