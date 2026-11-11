"""Owner-written context and an honest, local record of assistant runs."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ROUTINES = [
    {"name": "Plan my next hour", "prompt": "Help me plan my next hour around these priorities. Give me three concrete steps and the first action to take. Ask for anything essential that is missing.\n\nMy priorities: "},
    {"name": "Turn notes into actions", "prompt": "Turn these notes into a short action list with owners and dates only where stated. Separate unanswered questions. Do not invent appointments or say you saved anything.\n\nNotes: "},
    {"name": "Research a decision", "prompt": "Research this decision. Compare the realistic options, cite the evidence you actually have, and give me a recommendation with its main tradeoff.\n\nDecision: "},
]


def clean_routines(items) -> list[dict[str, str]]:
    """Never execute templates; callers only place these strings in the composer."""
    if not isinstance(items, list):
        return []
    result = []
    for item in items[:24]:
        if not isinstance(item, dict):
            continue
        name, prompt = item.get("name"), item.get("prompt")
        if isinstance(name, str) and isinstance(prompt, str) and name.strip() and prompt.strip():
            result.append({"name": name.strip()[:60], "prompt": prompt[:4000]})
    return result


def personal_context(settings) -> str:
    name = getattr(settings, "display_name", "")
    brief = getattr(settings, "personal_brief", "")
    name = name.strip()[:60] if isinstance(name, str) else ""
    brief = brief.strip()[:4000] if isinstance(brief, str) else ""
    if not name and not brief:
        return ""
    return (
        "OWNER'S SAVED BRIEF (local preferences and background, not evidence of completed actions "
        "or permission to operate external tools):\n"
        + json.dumps({"preferred_name": name, "priorities_and_style": brief}, ensure_ascii=False)
    )


class RunJournal:
    """Persist actual stages and measured times; never fabricate percentage progress."""

    def __init__(self, path: Path, *, clock=time.monotonic):
        self.path, self.clock = path, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._started: dict[str, float] = {}
        with closing(self._connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS assistant_runs (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, started_at TEXT NOT NULL,
                status TEXT NOT NULL, stage TEXT NOT NULL, elapsed_ms INTEGER NOT NULL DEFAULT 0,
                first_response_ms INTEGER, detail TEXT NOT NULL DEFAULT '')""")
            # A process exit is not success and must not silently replay a request.
            conn.execute("UPDATE assistant_runs SET status='interrupted', stage='Stopped before completion' WHERE status='running'")

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def start(self, text: str) -> str:
        run_id = uuid.uuid4().hex
        self._started[run_id] = self.clock()
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT INTO assistant_runs(id,title,started_at,status,stage) VALUES(?,?,?,?,?)", (
                run_id, " ".join(text.split())[:160], datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "running", "Looking up local context"))
            # Keep a bounded local activity log. Conversation memory is managed separately.
            conn.execute("DELETE FROM assistant_runs WHERE status!='running' AND id NOT IN (SELECT id FROM assistant_runs ORDER BY started_at DESC, rowid DESC LIMIT 100)")
        return run_id

    def elapsed(self, run_id: str) -> int:
        return max(0, round((self.clock() - self._started[run_id]) * 1000)) if run_id in self._started else 0

    def stage(self, run_id: str, stage: str):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE assistant_runs SET stage=?,elapsed_ms=? WHERE id=? AND status='running'", (stage[:180], self.elapsed(run_id), run_id))

    def first_response(self, run_id: str):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE assistant_runs SET first_response_ms=? WHERE id=? AND status='running' AND first_response_ms IS NULL", (self.elapsed(run_id), run_id))

    def finish(self, run_id: str, status: str, detail: str = ""):
        if status not in {"complete", "stopped", "error"}:
            raise ValueError("Invalid final run status")
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE assistant_runs SET status=?,stage=?,elapsed_ms=?,detail=? WHERE id=? AND status='running'", (
                status, {"complete": "Response ready", "stopped": "Stopped by you", "error": "Needs attention"}[status],
                self.elapsed(run_id), detail[:400], run_id))
        self._started.pop(run_id, None)

    def recent(self, limit: int = 20) -> list[dict]:
        with closing(self._connect()) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM assistant_runs ORDER BY started_at DESC, rowid DESC LIMIT ?", (min(100, max(1, limit)),))]
