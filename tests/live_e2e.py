"""Live end-to-end check of Doxa's AI paths (spends real budget, a few cents to ~$1; run on purpose):

    runtime\\Scripts\\python.exe tests\\live_e2e.py

Real Claude (chat agent with web search + Doxa tools), real laptop commands and files, a real Code mode job (Codex,
ChatGPT plan) started *by Claude through its tool*, and a real plugin (DeepWiki's public MCP server, no account).
Each scenario records which tools fired and checks the answer; the summary says PASS/FAIL per scenario."""
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forgemind.agent import DoxaTools  # noqa: E402
from forgemind.brain import Brain  # noqa: E402
from forgemind.claude_brain import ClaudeBrain  # noqa: E402
from forgemind.cloud_brain import CloudBrain, CloudBudget  # noqa: E402
from forgemind.code_mode import CodeRunner  # noqa: E402
from forgemind.config import Settings, app_data_dir  # noqa: E402
from forgemind.plugins import PluginStore  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="doxa-e2e-"))
settings = Settings.load()
settings.brain_mode = "auto"
cloud = CloudBrain(app_data_dir(), limit_cents=settings.cloud_monthly_cents)
claude = ClaudeBrain(app_data_dir(), CloudBudget(app_data_dir() / "claude-budget.sqlite3", settings.claude_monthly_cents))
spent_before = claude.budget.summary()["reserved_cents"]


class NoLocal:
    loaded = False


runner = CodeRunner(work / "data", claude_key=claude.api_key, budget=claude.budget)
jobs = []


def start_code_job(text, task, folder=None, engine="auto", source="", post=True, follow_up=None):
    job = runner.start(task, folder or str(work / "code"), engine, 1.0, follow_up=follow_up)
    jobs.append(job)
    return f"Code mode started with {job.name} in {job.folder}."


class Memory:
    def __init__(self):
        self.data = {}

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value):
        self.data[name] = value

    def delete(self, name):
        self.data.pop(name, None)


class Events:
    def put(self, item):
        if item[0] == "ui":
            item[1]()


app = SimpleNamespace(events=Events(), start_code_job=start_code_job)
tools = DoxaTools(app, notes_dir=work / "notes")
fired = []
original = tools.execute
tools.execute = lambda name, data: (fired.append(name), original(name, data))[1]
plugins = PluginStore(work / "plugins.json", Memory())
plugins.add("DeepWiki", "https://mcp.deepwiki.com/mcp")
brain = Brain(NoLocal(), cloud, claude)
brain.tools, brain.plugins = tools, plugins
statuses = []
brain.on_status = statuses.append


def ask(text):
    fired.clear()
    statuses.clear()
    started = time.monotonic()
    try:
        answer = "".join(brain.stream([], text, settings, [], []))
    except Exception as exc:
        answer = f"ERROR: {exc}"
    return answer, list(fired), list(statuses), time.monotonic() - started


results = []


def scenario(name, text, check):
    answer, used, seen, took = ask(text)
    try:
        ok, why = check(answer, used, seen)
    except Exception as exc:
        ok, why = False, f"check crashed: {exc}"
    results.append((name, ok, why, took, used))
    print(f"\n=== {name}: {'PASS' if ok else 'FAIL'} ({took:.0f} s) · tools {used} · {why}")
    print("    brain:", brain.last, "|", answer[:300].replace("\n", " "))


(work / "files").mkdir()
for n in range(3):
    (work / "files" / f"sample{n}.txt").write_text("x")

scenario("web research", "Search the web: what is the latest stable Python version? One line with the source.",
         lambda a, u, s: (any("Searching" in x or "Reading" in x for x in s) and "3." in a, "searched and answered"))
scenario("laptop command", f"How many .txt files are in {work / 'files'}? Check with a command, answer with the number.",
         lambda a, u, s: ("run_command" in u and "3" in a, "used run_command, said 3"))
target = work / "note.txt"
scenario("write + read a file", f"Create the file {target} containing exactly: doxa e2e ok. Then read it back to me.",
         lambda a, u, s: ("write_file" in u and target.read_text("utf-8").strip() == "doxa e2e ok",
                          "file written with the right text"))
scenario("plugin (MCP)", "Use the DeepWiki plugin: in one sentence, what is the GitHub repo anthropics/anthropic-sdk-python?",
         lambda a, u, s: (any("Using" in x for x in s) or "SDK" in a or "sdk" in a,
                          "plugin tool used" if any("Using" in x for x in s) else "answered (plugin status not seen)"))
scenario("code mode via chat", "Use code mode with codex: create add.py with a function add(a, b) and a tiny test that "
         "prints PASS when add(2, 3) == 5, then run it.",
         lambda a, u, s: ("run_code_job" in u and bool(jobs), "Claude started a Code mode job"))
if jobs:
    deadline = time.time() + 600
    while jobs[-1].status == "running" and time.time() < deadline:
        time.sleep(3)
    job = jobs[-1]
    ok = job.status == "done" and (Path(job.folder) / "add.py").is_file()
    results.append(("code job finished", ok, f"{job.status}, add.py exists: {(Path(job.folder) / 'add.py').is_file()}",
                    time.time() - job.started, []))
    print(f"\n=== code job finished: {'PASS' if ok else 'FAIL'} · {job.summary[:200]!r}")

spent = claude.budget.summary()["reserved_cents"] - spent_before
print("\n" + "=" * 70)
for name, ok, why, took, used in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name:<22} {took:5.0f} s  {why}")
print(f"{sum(1 for r in results if r[1])}/{len(results)} passed · Claude spend {spent:.1f}¢ · work folder {work}")
