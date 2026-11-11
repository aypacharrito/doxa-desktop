from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from forgemind.config import app_data_dir


STARTER_GOALS = [
    ("Readable clip captions", "Improve forgemind/clips.py captions so long transcript segments are split into "
     "short readable caption cues without changing the clip timing. Add generated evaluation tests for "
     "long speech, partial overlaps, and empty transcripts.", "Captions remain within clip boundaries and use short readable lines."),
    ("Accurate sampled frame times", "Improve forgemind/media.py sample_video_frames to decode past the seek "
     "keyframe until the requested sample time, rather than returning an earlier keyframe. Preserve actual "
     "sample timestamps in each media record. Test with mocked frame timestamps and no-video input.",
     "Sampled frames match their documented timestamps; source recordings are unchanged."),
    ("Useful clip export errors", "Improve forgemind/clips.py render failure messages so missing video tracks, "
     "caption rendering failures, and unavailable encoders have clear specific causes. Preserve render logs "
     "and the existing NVIDIA-to-CPU fallback. Add generated tests that mock failed exporter output.",
     "Failures identify their actual cause and retain logs; working exports still pass."),
]


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class GrowthStore:
    """A durable queue for application upgrades, not a model-weight trainer."""

    def __init__(self, root: Path | None = None, seed: bool = True) -> None:
        self.root = Path(root) if root else app_data_dir() / "growth"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "growth.sqlite3"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(
                    id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                    goal TEXT NOT NULL, acceptance TEXT NOT NULL, origin TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL,
                    started REAL, finished REAL, owner_pid INTEGER, result TEXT);
            """)
            db.execute("INSERT OR IGNORE INTO preferences VALUES('enabled','true')")
            db.execute("INSERT OR IGNORE INTO preferences VALUES('priorities',?)", (json.dumps(
                "Improve local coding, Pacifica CRM project workflows, recording understanding, clipping, "
                "and Roblox development tools. Make small measurable upgrades to Doxa itself."),))
            if seed and not db.execute("SELECT 1 FROM preferences WHERE key='seeded'").fetchone():
                for title, goal, acceptance in STARTER_GOALS:
                    self._insert(db, title, goal, acceptance, "starter")
                db.execute("INSERT INTO preferences VALUES('seeded','true')")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def preference(self, key: str):
        with self.connection() as db:
            row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
            return json.loads(row["value"]) if row else None

    def configure(self, **values):
        with self.connection() as db:
            for key, value in values.items():
                db.execute("INSERT OR REPLACE INTO preferences VALUES(?,?)", (key, json.dumps(value)))

    @staticmethod
    def _insert(db, title, goal, acceptance, origin):
        goal = " ".join(str(goal).split())
        if not 10 <= len(goal) <= 2000 or not str(acceptance).strip():
            raise ValueError("Add one concrete goal (10–2000 characters) and a way to verify it.")
        digest = hashlib.sha256(goal.lower().encode()).hexdigest()
        cursor = db.execute("INSERT OR IGNORE INTO tasks(digest,title,goal,acceptance,origin,created) "
                            "VALUES(?,?,?,?,?,?)", (digest, str(title)[:100], goal, str(acceptance)[:1000], origin, time.time()))
        return cursor.lastrowid if cursor.rowcount else None

    def add(self, title, goal, acceptance, origin="owner"):
        with self.connection() as db:
            return self._insert(db, title, goal, acceptance, origin)

    def tasks(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")]

    def active(self):
        return next((row for row in self.tasks() if row["status"] == "running"), None)

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            enabled = db.execute("SELECT value FROM preferences WHERE key='enabled'").fetchone()
            if not enabled or not json.loads(enabled[0]) or db.execute(
                "SELECT 1 FROM tasks WHERE status='running'"
            ).fetchone():
                return None
            task = db.execute("SELECT * FROM tasks WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if not task:
                return None
            db.execute("UPDATE tasks SET status='running', started=?, owner_pid=? WHERE id=?",
                       (time.time(), os.getpid(), task["id"]))
            return dict(db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone())

    def finish(self, identifier: int, result):
        data = asdict(result) if hasattr(result, "__dataclass_fields__") else dict(result)
        tests_passed = data.get("tests_passed") is True
        if data.get("applied") and not tests_passed:
            raise ValueError("An update cannot be recorded as installed without passing verification.")
        status = "installed" if data.get("applied") else "verified" if tests_passed and data.get("status") == "verified" else (
            "paused" if data.get("status") == "stopped" else "needs_attention")
        with self.connection() as db:
            task = db.execute("SELECT started FROM tasks WHERE id=? AND status='running'", (identifier,)).fetchone()
            if not task:
                raise ValueError("Only a running task can receive a completion result.")
            data["elapsed_seconds"] = max(0, time.time() - (task["started"] or time.time()))
            db.execute("UPDATE tasks SET status=?, finished=?, result=?, owner_pid=NULL WHERE id=?",
                       (status, time.time(), json.dumps(data), identifier))
        return status

    def retry(self, identifier):
        with self.connection() as db:
            cursor = db.execute("UPDATE tasks SET status='pending', started=NULL, finished=NULL, result=NULL "
                                "WHERE id=? AND status IN ('paused','needs_attention')", (identifier,))
            if not cursor.rowcount:
                raise ValueError("Select a paused task or one that needs attention.")

    def recover(self, evolver):
        task = self.active()
        if not task or _alive(task.get("owner_pid") or 0):
            return
        # Reconcile a completed campaign if the process exited before updating its queue row.
        for path in sorted(evolver.campaigns_root.glob("*.json"), reverse=True):
            try:
                campaign = json.loads(path.read_text(encoding="utf-8"))
                if not campaign.get("goal", "").startswith(task["goal"]):
                    continue
                attempts = campaign.get("attempts", [])
                if attempts and campaign["status"] in {"applied", "verified"}:
                    result_path = evolver.runs_root / attempts[-1]["run_id"] / "result.json"
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    self.finish(task["id"], result)
                    return
                break
            except (OSError, ValueError, KeyError):
                continue
        with self.connection() as db:
            db.execute("UPDATE tasks SET status='pending', owner_pid=NULL WHERE id=? AND status='running'", (task["id"],))

    def propose(self, engine, manifest: str):
        recent = [{"title": row["title"], "goal": row["goal"], "status": row["status"],
                   "outcome": json.loads(row["result"]) if row["result"] else None} for row in self.tasks()[-12:]]
        response = engine.generate_json(
            "Plan small testable upgrades to the owner's Doxa application. Return JSON with tasks "
            "(up to 3 objects, each title, goal, acceptance). Use existing source modules. Inspect recorded "
            "failures and suggest a narrower repair or a useful missing capability. Do not repeat past goals. "
            "Do not weaken verification, fabricate success, modify connected personal projects, retrain "
            "weights, purchase services, or publish content as part of an application upgrade. Use empty "
            "tasks if no concrete next upgrade is justified. Each goal should fit one small coding change.",
            f"OWNER PRIORITIES:\n{self.preference('priorities')}\nRECENT OUTCOMES:\n"
            f"{json.dumps(recent)[:6000]}\nCURRENT SOURCE MANIFEST:\n{manifest[:7000]}", max_tokens=1200)
        added = 0
        for item in response.get("tasks", [])[:3]:
            if not isinstance(item, dict):
                continue
            try:
                added += bool(self.add(item["title"], item["goal"], item["acceptance"], "planner"))
            except (KeyError, ValueError):
                continue
        return added
