"""Small, explicit local commands. Model output never enters this dispatcher."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Command:
    kind: str
    target: str = ""


APPS = {
    "calculator": "Calculator", "notepad": "Notepad", "downloads": "Downloads",
    "documents": "Documents", "pacifica": "Pacifica", "vyra": "VYRA",
}
ALIASES = {"calc": "calculator", "my downloads": "downloads", "my documents": "documents",
           "pacifica crm": "pacifica"}


def parse_command(text: str) -> Command | None:
    """Whole-request matching keeps quoted, compound and hypothetical requests inert."""
    value = text.strip()
    match = re.fullmatch(r"(?:please\s+)?(?:open|launch|/open)\s+([\w ]+?)(?:\s+please)?[.!]?", value, re.I)
    if match:
        name = " ".join(match[1].lower().split())
        name = ALIASES.get(name, name)
        if name in APPS:
            return Command("open", name)
    normalized = value.casefold().rstrip(".!?")
    if normalized in {"morning brief", "my morning brief", "give me my morning brief", "evening review", "my evening review"}:
        return Command("brief", "evening" if "evening" in normalized else "morning")
    match = re.fullmatch(r"(?:computer:|use my computer to|on my computer,)\s*(.{1,2400})", value, re.I | re.S)
    if match:
        return Command("computer", match[1].strip())
    return None


def launch_app(name: str, *, startfile=None, home=None, local=None, windows=None) -> str:
    """Open only an allowlisted app/folder; no shell, URLs, arguments or arbitrary paths."""
    if name not in APPS:
        raise ValueError("Choose an app from the available shortcuts.")
    home = Path(home) if home else Path.home()
    local = Path(local) if local else Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
    windows = Path(windows) if windows else Path(os.environ.get("SystemRoot", "C:/Windows"))
    targets = {
        "calculator": windows / "System32/calc.exe",
        "notepad": windows / "System32/notepad.exe",
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "vyra": local / "Programs/VYRA/VYRA.exe",
    }
    # The existing cloud workspace opens in the owner's default browser.
    if name == "pacifica":
        destination = "https://crm.example.com"
    else:
        target = targets[name]
        if not target.exists():
            raise FileNotFoundError(f"{APPS[name]} is not available at its usual location.")
        destination = str(target)
    (startfile or os.startfile)(destination)
    return f"Sent the open request to Windows for {APPS[name]}."


def local_brief(settings, counts, runs, *, today: str, calendar=None) -> str:
    """A factual snapshot, not an invented calendar or achievement summary.

    calendar: None when Google Calendar isn't connected, a list of today's events from
    GoogleCalendar.events_on, or an error string when reading it failed.
    """
    todays = [row for row in runs if row.get("local_date") == today]
    complete = sum(row.get("status") == "complete" for row in todays)
    interrupted = sum(row.get("status") in {"error", "interrupted", "stopped"} for row in todays)
    lines = [f"Your local workspace · {today}", ""]
    brief = getattr(settings, "personal_brief", "").strip()
    lines += ["Your saved priorities:", brief[:1200] if brief else "Add your priorities in Your brief to personalize this view.", ""]
    lines += [f"Today: {complete} completed requests · {interrupted} stopped or needing attention.",
              "A completed request means Doxa finished its response, not that a real-world task was completed.",
              f"Memory: {counts.get('memories', 0)} pinned items · {counts.get('documents', 0)} indexed files."]
    if todays:
        lines += ["", "Recent requests:"]
        lines += [f"• {row['title']} — {row['stage']}" for row in todays[:4]]
    if calendar is None:
        lines += ["", "Calendar isn't connected (Settings → Google Calendar). Email is not connected to this brief."]
    elif isinstance(calendar, str):
        lines += ["", f"Couldn't read today's Google Calendar: {calendar}", "Email is not connected to this brief."]
    else:
        from .calendar_connector import event_lines
        lines += ["", "Today on your Google Calendar:"] if calendar else ["", "Nothing on your Google Calendar today."]
        lines += event_lines(calendar)
        lines += ["", "Email is not connected to this brief."]
    return "\n".join(lines)
