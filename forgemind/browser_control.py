"""One running browser task, shared by the desktop panel and the phone.

Questions, hand-offs and approvals become a single "pending request" that either
screen can answer; the first answer wins. Nothing here touches Tk.
"""
from __future__ import annotations

import threading
import uuid
from collections import deque
from typing import Callable

from .browser_agent import BrowserTask, OwnerFacts


class BrowserController:
    def __init__(self, make_session: Callable, make_planner: Callable, *, facts: OwnerFacts | None = None,
                 search=None, root=None, on_finish: Callable[[dict], None] | None = None,
                 on_change: Callable[[], None] | None = None,
                 on_request: Callable[[dict], None] | None = None):
        self.make_session, self.make_planner = make_session, make_planner
        self.facts, self.search, self.root = facts, search, root
        self.on_finish = on_finish or (lambda result: None)
        self.on_change = on_change or (lambda: None)
        self.on_request = on_request or (lambda pending: None)
        self._lock = threading.RLock()
        self._task: BrowserTask | None = None
        self._goal = ""
        self._log: deque[str] = deque(maxlen=60)
        self._pending: dict | None = None
        self._result: dict | None = None
        self._thread: threading.Thread | None = None

    # State -------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def task(self) -> BrowserTask | None:
        return self._task

    def state(self) -> dict:
        with self._lock:
            pending = None
            if self._pending:
                pending = {k: self._pending[k] for k in ("id", "kind", "text", "title", "body")}
            return {
                "running": self.running,
                "paused": bool(self._task and self._task.pause.is_set()),
                "task": self._goal,
                "log": list(self._log)[-30:],
                "pending": pending,
                "result": self._result,
            }

    def _note(self, text: str) -> None:
        with self._lock:
            self._log.append(text)
        self.on_change()

    # Owner interaction (called from the task thread) -----------------------------------
    def _request(self, kind: str, text: str = "", title: str = "", body: str = ""):
        reply = {"id": uuid.uuid4().hex[:10], "kind": kind, "text": text, "title": title, "body": body,
                 "done": threading.Event(), "value": None}
        with self._lock:
            self._pending = reply
        self.on_change()
        try:
            self.on_request({k: reply[k] for k in ("id", "kind", "text", "title", "body")})
        except Exception:
            pass  # a notification problem must never block the task
        task = self._task
        while not reply["done"].wait(0.2):
            if task is not None and task.stop.is_set():
                break
        with self._lock:
            if self._pending is reply:
                self._pending = None
        self.on_change()
        return reply["value"]

    def respond(self, request_id: str, value) -> bool:
        """Answer the pending request. Returns False if it was already answered elsewhere."""
        with self._lock:
            pending = self._pending
            if not pending or pending["id"] != request_id:
                return False
            if pending["kind"] == "ask":
                if value is not None:
                    answer, remember = value if isinstance(value, (list, tuple)) else (value, False)
                    answer = str(answer).strip()[:500]
                    value = (answer, bool(remember)) if answer else None
            else:
                value = bool(value)
            pending["value"] = value
            self._pending = None
            pending["done"].set()
        self.on_change()
        return True

    # Control -----------------------------------------------------------------------------
    def start(self, goal: str) -> None:
        goal = goal.strip()
        if not goal:
            raise ValueError("Describe the website task first.")
        if len(goal) > 2400:
            raise ValueError("That task description is too long.")
        with self._lock:
            if self.running:
                raise RuntimeError("A browser task is already running. Stop it first.")
            self._goal, self._result, self._pending = goal, None, None
            self._log.clear()
            self._log.append("OWNER TASK: " + goal)
            ready = threading.Event()
            self._thread = threading.Thread(target=self._work, args=(goal, ready), daemon=True)
            self._thread.start()
        ready.wait(5)
        self.on_change()

    def _work(self, goal: str, ready: threading.Event) -> None:
        session, result = None, None
        try:
            session = self.make_session()
            self._task = BrowserTask(
                goal, self.make_planner(), session,
                ask=lambda q: self._request("ask", text=q),
                confirm=lambda t, b: bool(self._request("confirm", title=t, body=b)),
                hand_off=lambda r: bool(self._request("hand_off", text=r)),
                notify=self._note, facts=self.facts, search=self.search, root=self.root)
            ready.set()
            session.open()
            result = self._task.run()
        except Exception as exc:
            ready.set()
            result = {"task": goal, "status": "error", "message": str(exc)[:300], "steps": 0}
            self._note("Could not finish: " + str(exc)[:300])
        finally:
            try:
                if session is not None:
                    session.close()  # same thread that opened it
            except Exception:
                pass
            with self._lock:
                self._result = result
                self._pending = None
            self.on_finish(result)
            self.on_change()

    def stop(self) -> None:
        task = self._task
        if task is not None and self.running:
            task.stop.set()
            with self._lock:
                pending = self._pending
                self._pending = None
            if pending:
                pending["done"].set()
            self._note("Stop requested. No further steps will be taken.")

    def toggle_pause(self) -> bool:
        task = self._task
        if task is None or not self.running:
            return False
        if task.pause.is_set():
            task.pause.clear()
            self._note("Resumed.")
        else:
            task.pause.set()
            self._note("Paused. Resume continues from what's on screen.")
        return task.pause.is_set()

    def join(self, timeout=None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
