"""Google Calendar panels: connect/disconnect, and the event card that asks before anything is added.

Background work posts ("ui", callback) to app.events so every widget change happens on the Tk thread.
"""
from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from zoneinfo import ZoneInfo

from forgemind import jarvis_ui as ui
from forgemind.calendar_connector import event_lines, new_event_id
from forgemind.calendar_intent import ParsedEvent, build_draft, describe, parse_event_request

SETUP_STEPS = (
    "One-time setup (about 5 minutes, all on Google's own pages):\n\n"
    "1. Open console.cloud.google.com and pick a project (the YouTube one is fine) or create one.\n"
    "2. APIs & Services → Library → Google Calendar API → Enable.\n"
    "3. OAuth consent screen → External. Add your Gmail as a test user. Then press Publish app "
    "(Testing mode makes Google end the permission every 7 days). Google will warn that the app "
    "isn't verified; that's expected for your own private app.\n"
    "4. Credentials → Create credentials → OAuth client ID → Desktop app → Download JSON.\n"
    "5. Back here: Connect Google Calendar → choose that JSON → sign in and press Allow in your browser.\n\n"
    "Doxa keeps the permission in Windows Credential Manager, never in a file or in chat. "
    "It can see and add events on your calendar; it can't change calendar sharing or settings."
)


def calendar_now(app) -> datetime:
    """Now, in the calendar's own time zone once connected (else this PC's)."""
    calendar = getattr(app, "calendar", None)
    zone = calendar.time_zone() if calendar is not None else ""
    try:
        return datetime.now(ZoneInfo(zone)) if zone else datetime.now().astimezone()
    except Exception:
        return datetime.now().astimezone()


def _run(app, work, done):
    """work() runs in a thread; done(result, error) runs on the Tk thread."""
    def target():
        try:
            result, error = work(), None
        except Exception as exc:  # shown to the owner, never swallowed
            result, error = None, exc
        app.events.put(("ui", lambda: done(result, error)))
    threading.Thread(target=target, daemon=True).start()


def _entry(parent, variable):
    """Dark text field (ttk.Entry ignores the dark field colour under Windows' native theme)."""
    return tk.Entry(parent, textvariable=variable, bg=ui.SURFACE_2, fg=ui.TEXT, insertbackground=ui.GOLD,
                    disabledbackground=ui.SURFACE, disabledforeground=ui.FAINT, relief="flat", borderwidth=6,
                    highlightthickness=1, highlightbackground=ui.LINE, highlightcolor=ui.GOLD_DIM,
                    selectbackground=ui.SELECT, selectforeground=ui.TEXT, font=(ui.BODY, 11))


def _say(app, user_text: str, reply: str, *, from_phone: bool = False, speak: str = "", voice=None) -> None:
    voice = getattr(app, "_voice_turn", False) if voice is None else voice
    app.db.add_message("user", user_text)
    app.db.add_message("assistant", reply)
    app._append("user", "YOU · PHONE\n" if from_phone else "YOU\n")
    app._append("body", user_text + "\n\n")
    app._append("assistant", "DOXA\n")
    app._append("body", reply + "\n\n")
    if speak and voice and app.voice.enabled:
        app.voice.speak(speak)
    app.refresh_all()


def _note(app, reply: str) -> None:
    app.db.add_message("assistant", reply)
    app._append("assistant", "DOXA\n")
    app._append("body", reply + "\n\n")
    app.refresh_all()


NOT_CONNECTED = ("Google Calendar isn't connected yet, so I can't see or add events. I've opened "
                 "Settings → Google Calendar; connect it once and ask me again.")


# ── chat entry points ─────────────────────────────────────────

def offer_event(app, text: str, *, from_phone: bool = False) -> str:
    """A calendar request from chat: show the card. Nothing is written until the owner presses Yes."""
    if not app.calendar.connected():
        _say(app, text, NOT_CONNECTED, from_phone=from_phone, speak="Google Calendar isn't connected yet.")
        open_calendar_panel(app)
        return NOT_CONNECTED
    parsed = parse_event_request(text, calendar_now(app))
    reply = ("Here's the event. Check the details and press Yes to add it to your Google Calendar. "
             "Nothing goes on your calendar until you do.")
    _say(app, text, reply, from_phone=from_phone, speak="Here's the event. Press Yes to add it.")
    open_event_card(app, parsed)
    return reply


def answer_day(app, text: str, day: date, *, from_phone: bool = False) -> None:
    """'What's on my calendar tomorrow?' — read only, answered off the Tk thread."""
    if not app.calendar.connected():
        _say(app, text, NOT_CONNECTED, from_phone=from_phone, speak="Google Calendar isn't connected yet.")
        open_calendar_panel(app)
        return
    voice = getattr(app, "_voice_turn", False)
    app._set_status("Checking your Google Calendar…")

    def done(events, error):
        reply = day_summary(day, events, error, calendar_now(app).date())
        _say(app, text, reply, from_phone=from_phone, speak=reply.split("\n")[0], voice=voice)
        app._set_status("Ready")
    _run(app, lambda: app.calendar.events_on(day), done)


def day_summary(day: date, events, error, today: date) -> str:
    label = {0: "today", 1: "tomorrow", -1: "yesterday"}.get((day - today).days,
                                                            day.strftime("%A, %B ") + str(day.day))
    if error is not None:
        return f"I couldn't read your calendar: {error}"
    if not events:
        return f"Nothing on your calendar {label}."
    count = f"{len(events)} event{'s' if len(events) != 1 else ''}"
    return f"You have {count} {label}:\n" + "\n".join(event_lines(events))


# ── connect panel ─────────────────────────────────────────────

def open_calendar_panel(app):
    existing = getattr(app, "_calendar_panel", None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return existing
    window = tk.Toplevel(app)
    ui.pop_in(window)
    app._calendar_panel = window
    window.title("Doxa · Google Calendar")
    window.geometry("560x620")
    window.configure(bg=ui.BG)
    window.transient(app)
    app.after(50, lambda: window.winfo_exists() and ui._dark_titlebar(window))
    content = tk.Frame(window, bg=ui.BG, padx=28, pady=24)
    content.pack(fill="both", expand=True)
    tk.Label(content, text="Google Calendar", bg=ui.BG, fg=ui.TEXT, font=(ui.DISPLAY, 22)).pack(anchor="w")
    tk.Label(content, text="Doxa reads today's events for your brief and adds events only after you press Yes.",
             bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 10), wraplength=500, justify="left").pack(anchor="w", pady=(4, 16))

    status_card = ui.Rounded(content)
    status_card.pack(fill="x")
    status = tk.Label(status_card.inner, bg=ui.SURFACE, fg=ui.TEXT, font=(ui.BODY_BOLD, 11), anchor="w", justify="left")
    status.pack(fill="x")
    detail = tk.Label(status_card.inner, bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w", justify="left",
                      wraplength=460)
    detail.pack(fill="x", pady=(4, 0))

    account_row = tk.Frame(content, bg=ui.BG)
    account_row.pack(fill="x", pady=(16, 4))
    tk.Label(account_row, text="Google account", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9)).pack(anchor="w")
    account = tk.StringVar(value=getattr(app.settings_data, "calendar_account", ""))
    _entry(account_row, account).pack(fill="x", pady=(4, 0))

    buttons = tk.Frame(content, bg=ui.BG)
    buttons.pack(fill="x", pady=(12, 0))
    connect_button = ui.button(buttons, "Connect Google Calendar", lambda: connect(), active=True)
    connect_button.pack(fill="x", pady=2)
    ui.button(buttons, "Setup steps", lambda: messagebox.showinfo("Google Calendar setup", SETUP_STEPS,
                                                                   parent=window)).pack(fill="x", pady=2)
    ui.button(buttons, "Show today's events", lambda: show_today()).pack(fill="x", pady=2)
    ui.button(buttons, "Open Google Calendar", lambda: webbrowser.open("https://calendar.google.com")).pack(fill="x", pady=2)
    disconnect_button = ui.button(buttons, "Disconnect", lambda: disconnect())
    disconnect_button.pack(fill="x", pady=2)
    today_box = tk.Label(content, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY, 10), anchor="w", justify="left", wraplength=500)
    today_box.pack(fill="x", pady=(14, 0))

    def refresh(message=""):
        if not window.winfo_exists():
            return
        info = app.calendar.summary()
        if info["connected"]:
            status.configure(text="Connected", fg=ui.GOLD)
            detail.configure(text=message or f"{info['account'] or 'Primary calendar'} · {info['time_zone'] or 'time zone unknown'}")
            connect_button.configure(text="Reconnect Google Calendar")
        else:
            status.configure(text="Not connected", fg=ui.TEXT)
            detail.configure(text=message or "Press Setup steps first if you haven't made an OAuth client yet.")
            connect_button.configure(text="Connect Google Calendar")

    def save_account():
        value = account.get().strip()
        if value != getattr(app.settings_data, "calendar_account", ""):
            app.settings_data.calendar_account = value
            app.settings_data.save()
        return value

    def connect():
        path = filedialog.askopenfilename(parent=window, title="Choose the Google OAuth Desktop app client JSON",
                                          filetypes=[("JSON", "*.json")])
        if not path:
            return
        hint = save_account()
        connect_button.configure(state="disabled")
        refresh("Finish signing in on Google's page in your browser (5 minutes max)…")

        def done(info, error):
            if window.winfo_exists():
                connect_button.configure(state="normal")
            if error is not None:
                refresh(f"Not connected: {error}")
                return
            refresh()
            app._set_status("Google Calendar connected")
        _run(app, lambda: app.calendar.connect(Path(path), hint), done)

    def disconnect():
        if not app.calendar.connected():
            return
        if messagebox.askyesno("Disconnect Google Calendar",
                               "Remove Doxa's calendar permission from this PC and ask Google to revoke it?",
                               parent=window):
            _run(app, app.calendar.disconnect, lambda _r, _e: refresh("Disconnected."))

    def show_today():
        if not app.calendar.connected():
            refresh("Connect first.")
            return
        today = calendar_now(app).date()
        today_box.configure(text="Reading today's events…", fg=ui.MUTED)
        _run(app, lambda: app.calendar.events_on(today),
             lambda events, error: window.winfo_exists() and today_box.configure(
                 text=day_summary(today, events, error, today), fg=ui.ERROR if error else ui.TEXT))

    def close():
        app._calendar_panel = None
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    refresh()
    return window


# ── the approval card ─────────────────────────────────────────

def _clock(value) -> str:
    return value.strftime("%I:%M %p").lstrip("0") if value else ""


def open_event_card(app, parsed: ParsedEvent):
    old = getattr(app, "_calendar_card", None)
    if old is not None and old.winfo_exists():
        old.destroy()
    zone = app.calendar.time_zone() or str(calendar_now(app).tzinfo)
    window = tk.Toplevel(app)
    ui.pop_in(window)
    app._calendar_card = window
    window.title("Doxa · Add to calendar?")
    window.geometry("540x640")
    window.minsize(480, 560)
    window.configure(bg=ui.BG)
    window.transient(app)
    app.after(50, lambda: window.winfo_exists() and ui._dark_titlebar(window))
    content = tk.Frame(window, bg=ui.BG, padx=26, pady=22)
    content.pack(fill="both", expand=True)
    tk.Label(content, text="Add to your calendar?", bg=ui.BG, fg=ui.TEXT, font=(ui.DISPLAY, 20)).pack(anchor="w")
    tk.Label(content, text="Google Calendar · " + (app.calendar.summary().get("account") or "primary calendar"),
             bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9)).pack(anchor="w", pady=(2, 14))

    surface = ui.Rounded(content, padx=18, pady=16)
    surface.pack(fill="x")
    form = surface.inner
    form.columnconfigure(1, weight=1)
    fields: dict[str, tk.Variable] = {
        "title": tk.StringVar(value=parsed.title),
        "day": tk.StringVar(value=parsed.day.isoformat()),
        "start": tk.StringVar(value=_clock(parsed.start)),
        "end": tk.StringVar(value=_clock(parsed.end)),
        "attendees": tk.StringVar(value=", ".join(parsed.attendees)),
        "location": tk.StringVar(value=""),
    }
    all_day = tk.BooleanVar(value=parsed.all_day)
    invites = tk.BooleanVar(value=False)
    rows = [("Title", "title"), ("Date", "day"), ("Starts", "start"), ("Ends", "end"),
            ("Attendees", "attendees"), ("Location", "location")]
    entries = {}
    for row, (label, key) in enumerate(rows):
        tk.Label(form, text=label, bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 14), pady=4)
        entries[key] = _entry(form, fields[key])
        entries[key].grid(row=row, column=1, sticky="ew", pady=4)
    weekday = tk.Label(form, bg=ui.SURFACE, fg=ui.GOLD, font=(ui.BODY, 9), anchor="w")
    weekday.configure(width=10)
    weekday.grid(row=1, column=2, sticky="w", padx=(10, 0))  # beside the date
    tk.Label(form, text="Time zone", bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w").grid(
        row=len(rows) + 1, column=0, sticky="w", padx=(0, 14), pady=4)
    tk.Label(form, text=zone, bg=ui.SURFACE, fg=ui.TEXT, font=(ui.BODY, 10), anchor="w").grid(
        row=len(rows) + 1, column=1, sticky="w", pady=4)
    checks = tk.Frame(form, bg=ui.SURFACE)
    checks.grid(row=len(rows) + 2, column=0, columnspan=2, sticky="w", pady=(6, 0))
    tk.Checkbutton(checks, text="All day", variable=all_day, bg=ui.SURFACE, fg=ui.TEXT, selectcolor=ui.SURFACE_2,
                   activebackground=ui.SURFACE, activeforeground=ui.TEXT, highlightthickness=0,
                   command=lambda: sync()).pack(side="left")
    tk.Checkbutton(checks, text="Email invitations to attendees", variable=invites, bg=ui.SURFACE, fg=ui.TEXT,
                   selectcolor=ui.SURFACE_2, activebackground=ui.SURFACE, activeforeground=ui.TEXT,
                   highlightthickness=0).pack(side="left", padx=(16, 0))

    notes = "\n".join("• " + note for note in parsed.notes)
    if not parsed.attendees:
        notes += ("\n" if notes else "") + "• No attendees: add email addresses if you want to invite anyone."
    tk.Label(content, text=notes, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w", justify="left",
             wraplength=480).pack(fill="x", pady=(12, 0))
    message = tk.Label(content, bg=ui.BG, fg=ui.ERROR, font=(ui.BODY, 10), anchor="w", justify="left",
                       wraplength=480)
    message.pack(fill="x", pady=(8, 0))
    bar = tk.Frame(content, bg=ui.BG)
    bar.pack(fill="x", pady=(10, 0))
    yes = ui.button(bar, "Yes, add it", lambda: approve(), active=True)
    yes.pack(side="left")
    no = ui.button(bar, "No", lambda: decline())
    no.pack(side="left", padx=8)
    state = {"event_id": new_event_id(), "busy": False}  # same ID on retry → never a duplicate

    def sync(*_):
        for key in ("start", "end"):
            entries[key].configure(state="disabled" if all_day.get() else "normal")
        try:
            weekday.configure(text=date.fromisoformat(fields["day"].get().strip()).strftime("%A"), fg=ui.GOLD)
        except ValueError:
            weekday.configure(text="Use YYYY-MM-DD", fg=ui.ERROR)
    fields["day"].trace_add("write", sync)
    sync()

    def draft():
        return build_draft(title=fields["title"].get(), day=fields["day"].get(), start=fields["start"].get(),
                           end=fields["end"].get(), all_day=all_day.get(), attendees=fields["attendees"].get(),
                           time_zone=zone, send_invites=invites.get(), location=fields["location"].get(),
                           event_id=state["event_id"], today=calendar_now(app).date())

    def approve():
        if state["busy"]:
            return
        try:
            event = draft()
        except ValueError as exc:
            message.configure(text=str(exc), fg=ui.ERROR)
            return
        state["busy"] = True
        yes.configure(state="disabled")
        no.configure(state="disabled")
        message.configure(text="Adding to Google Calendar…", fg=ui.MUTED)
        app._set_status("Adding the event to Google Calendar…")
        voice = getattr(app, "_voice_turn", False)

        def done(created, error):
            state["busy"] = False
            if error is not None:
                if window.winfo_exists():
                    yes.configure(state="normal")
                    no.configure(state="normal")
                    hint = " Try Yes again; it won't make a duplicate." if not isinstance(error, ValueError) else ""
                    message.configure(text=f"Not added: {str(error).rstrip('.')}.{hint}", fg=ui.ERROR)
                app._set_status("The event was not added", error=True)
                return
            reply = f"Added to your Google Calendar: {describe(event)}."
            if event.attendees:
                reply += " Invitations emailed." if event.send_invites else " Attendees were added without emailing them."
            _note(app, reply)
            app._set_status("Event added to Google Calendar")
            if voice and app.voice.enabled:
                app.voice.speak("Done. It's on your calendar.")
            if window.winfo_exists():
                window.destroy()
        _run(app, lambda: app.calendar.create_event(event), done)

    def decline():
        if state["busy"]:
            return
        _note(app, "Okay, I didn't add anything to your calendar.")
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", decline)
    window.bind("<Escape>", lambda _e: decline())
    window.approve, window.decline, window.fields, window.all_day, window.message = (  # for tests
        approve, decline, fields, all_day, message)
    entries["title"].focus_set()
    window.lift()
    return window
