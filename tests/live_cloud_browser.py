"""Live check: the REAL connected cloud brain (Claude or OpenAI, via Doxa's own keys and $ budget) plans the local
mock-DMV wizard from test_browser_cloud.py in headless Edge, then the approval is DECLINED, so nothing is booked.

Not part of the unit suite (no `test_` prefix) because it spends real cloud budget (~10-60¢). Run it on purpose:
    "%LOCALAPPDATA%\\Programs\\Jarvis\\runtime\\Scripts\\python.exe" tests\\live_cloud_browser.py [--show]
Answers to Doxa's questions are fictional test values, never real personal details.
"""
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent)]

from forgemind.browser_agent import BrowserSession, BrowserTask, CloudPlanner, make_planner  # noqa: E402
from forgemind.brain import Brain  # noqa: E402
from forgemind.claude_brain import ClaudeBrain  # noqa: E402
from forgemind.cloud_brain import CloudBrain  # noqa: E402
from forgemind.config import Settings, app_data_dir  # noqa: E402
from test_browser_cloud import BROWSER, Wizard  # noqa: E402

ANSWERS = {"time": "Wed Nov 12, 9:00 AM", "name": "Test Person", "phone": "818-555-0142", "email": "test.person@example.com"}


def main():
    settings = Settings.load() if hasattr(Settings, "load") else Settings()
    openai = CloudBrain(app_data_dir(), limit_cents=getattr(settings, "cloud_monthly_cents", None))
    brain = Brain(None, openai, ClaudeBrain(app_data_dir(), openai.budget))
    planner = make_planner(brain, settings, engine=None)
    if not isinstance(planner, CloudPlanner):
        sys.exit("No cloud brain is connected (Tools → AI brains). Nothing was run.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Wizard)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    folder = tempfile.mkdtemp(prefix="doxa-live-")
    session = BrowserSession(Path(folder) / "profile", headless="--show" not in sys.argv, executable_path=BROWSER).open()
    approvals = []

    def ask(question):
        answer = next((v for k, v in ANSWERS.items() if k in question.lower()), None)
        if "time" in question.lower() or "date" in question.lower():
            answer = ANSWERS["time"]
        print(f"  ASKED: {question}\n  -> {answer}")
        return (answer, False) if answer else None

    try:
        session.goto(base + "/")
        task = BrowserTask("Book a DMV appointment at the Van Nuys office for a vehicle title transfer", planner, session,
                           ask=ask, confirm=lambda t, b: approvals.append((t, b)) or False,  # always decline
                           hand_off=lambda r: print("  HAND-OFF:", r) or False,
                           notify=lambda text: print(" ", text[:160]), root=Path(folder) / "runs")
        started = time.monotonic()
        result = task.run()
    finally:
        session.close()
        server.shutdown()
    print("\nRESULT:", result["status"], "-", result["message"])
    print(f"Planner {result.get('planner')}: {result.get('cloud_steps')} cloud steps, ~{result.get('cloud_cents')}¢, "
          f"{time.monotonic() - started:.0f} s")
    print("Approval asked:", approvals[0][0] if approvals else "never")
    print("Bookings made:", Wizard.bookings or "none")
    ok = bool(approvals) and "Confirm appointment" in approvals[0][0] and not Wizard.bookings
    print("PASS: reached the approval step, nothing submitted" if ok else "DID NOT REACH THE APPROVAL STEP")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
