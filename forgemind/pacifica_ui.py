"""Tk panels for the Pacifica CRM connection: Settings → Pacifica connection, and the quote confirmation card.

Network calls run on worker threads; results come back through app.events (drained by the Tk loop).
The token is never shown, logged or put in settings.json — only in Windows Credential Manager.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from . import jarvis_ui as ui
from . import pacifica


def _window(app, title, size):
    window = tk.Toplevel(app)
    ui.pop_in(window)
    window.title("Doxa · " + title)
    window.geometry(size)
    window.configure(bg=ui.BG)
    window.transient(app)
    window.after(50, lambda: ui._dark_titlebar(window))
    frame = tk.Frame(window, bg=ui.BG, padx=26, pady=22)
    frame.pack(fill="both", expand=True)
    return window, frame


def _label(parent, text, *, fg=None, font=None, wrap=480):
    widget = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=fg or ui.TEXT, font=font or (ui.BODY, 10),
                      justify="left", anchor="w", wraplength=wrap)
    widget.pack(fill="x", anchor="w")
    return widget


def _entry(parent, *, show=""):
    widget = tk.Entry(parent, bg=ui.SURFACE, fg=ui.TEXT, insertbackground=ui.GOLD, relief="flat",
                      highlightthickness=1, highlightbackground=ui.LINE, highlightcolor=ui.GOLD_DIM,
                      font=(ui.BODY, 11), show=show)
    widget.pack(fill="x", ipady=7, pady=(4, 12))
    return widget


def open_connection(app):
    """Settings → Pacifica connection: CRM address (settings.json) + token (Credential Manager)."""
    existing = getattr(app, "_pacifica_panel", None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return existing
    window, frame = _window(app, "Pacifica connection", "560x560")
    app._pacifica_panel = window
    _label(frame, "Pacifica connection", font=(ui.DISPLAY, 20))
    _label(frame, "Lets you say “start a quote for <customer>, <coverage>”. Doxa shows you exactly what it "
                  "will send and only sends after you press Send. It creates a quote request in your CRM — "
                  "it never binds coverage or contacts carriers.", fg=ui.MUTED).pack_configure(pady=(6, 16))
    _label(frame, "Pacifica address", fg=ui.MUTED, font=(ui.BODY_BOLD, 9))
    url = _entry(frame)
    url.insert(0, getattr(app.settings_data, "pacifica_url", "") or "")
    _label(frame, "Integration token (same value as JARVIS_INTEGRATION_TOKEN in Vercel)", fg=ui.MUTED,
           font=(ui.BODY_BOLD, 9))
    token = _entry(frame, show="•")
    saved = tk.StringVar()
    status = tk.StringVar()

    def refresh_saved():
        saved.set("Token: saved in Windows Credential Manager" if pacifica.token_get()
                  else "Token: not saved yet")
    refresh_saved()
    _label(frame, "", fg=ui.MUTED).configure(textvariable=saved)
    _label(frame, "", fg=ui.GOLD).configure(textvariable=status)

    def save():
        try:
            address = pacifica.clean_base_url(url.get())
            if token.get().strip():
                pacifica.token_set(token.get())
            app.settings_data.pacifica_url = address
            app.settings_data.save()
        except ValueError as exc:
            status.set(str(exc))
            return
        except Exception:
            status.set("Couldn't save the token in Windows Credential Manager.")
            return
        token.delete(0, "end")
        refresh_saved()
        status.set("Saved." if pacifica.is_configured(address) else "Saved. Add the token to finish connecting.")

    def remove():
        pacifica.token_set("")
        refresh_saved()
        status.set("Token removed. Doxa can no longer reach Pacifica.")

    def test():
        try:
            client = pacifica.PacificaClient(url.get())
        except ValueError as exc:
            status.set(str(exc))
            return
        status.set("Checking Pacifica (read-only)…")

        def work():
            try:
                client.check()
                message = "Connected. Pacifica accepted Doxa's token."
            except pacifica.PacificaError as exc:
                message = str(exc)
            app.events.put(("pacifica_status", message))
        threading.Thread(target=work, daemon=True, name="pacifica-check").start()
    app._pacifica_status = status

    bar = tk.Frame(frame, bg=ui.BG)
    bar.pack(fill="x", pady=(14, 0))
    ui.button(bar, "Save", save, active=True).pack(side="left")
    ui.button(bar, "Test connection", test).pack(side="left", padx=8)
    ui.button(bar, "Remove token", remove).pack(side="left")
    return window


def confirm_quote(app, draft: pacifica.QuoteDraft, on_send):
    """Show exactly what will be sent. on_send(draft) runs only when the owner presses Send."""
    old = getattr(app, "_pacifica_card", None)
    if old is not None and old.winfo_exists():
        old.destroy()  # one pending card at a time; a new request replaces the old one
    client = pacifica.PacificaClient(app.settings_data.pacifica_url)
    window, frame = _window(app, "Confirm quote request", "540x520")
    app._pacifica_card = window
    _label(frame, "Send this quote request to Pacifica?", font=(ui.DISPLAY, 17))
    _label(frame, "This is exactly what Doxa will send. Nothing is sent until you press Send.",
           fg=ui.MUTED).pack_configure(pady=(6, 14))
    surface = ui.Rounded(frame, fill=ui.SURFACE, outline=ui.LINE, radius=12, padx=18, pady=14)
    surface.pack(fill="x")
    grid = tk.Frame(surface.inner, bg=ui.SURFACE)
    grid.pack(fill="x")
    for row, (name, value) in enumerate(draft.card_rows()):
        tk.Label(grid, text=name, bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY_BOLD, 9), anchor="nw").grid(
            row=row, column=0, sticky="nw", padx=(0, 14), pady=3)
        tk.Label(grid, text=value, bg=ui.SURFACE, fg=ui.TEXT, font=(ui.BODY, 10), anchor="w", justify="left",
                 wraplength=340).grid(row=row, column=1, sticky="w", pady=3)
    _label(frame, f"To: {client.endpoint}", fg=ui.FAINT, font=(ui.BODY, 9)).pack_configure(pady=(12, 0))
    _label(frame, "Creates a quote request for you to review in Pacifica. Doxa does not bind coverage, "
                  "contact carriers or run carrier quotes.", fg=ui.FAINT, font=(ui.BODY, 9))
    status = tk.StringVar()
    _label(frame, "", fg=ui.GOLD).configure(textvariable=status)
    bar = tk.Frame(frame, bg=ui.BG)
    bar.pack(fill="x", pady=(12, 0))

    def send():
        send_button.configure(state="disabled")
        cancel_button.configure(state="disabled")
        status.set("Sending to Pacifica…")
        on_send(draft)
        window.after(300, window.destroy)

    def cancel():
        app.events.put(("pacifica_done", None, "Okay — I didn't send that quote request."))
        window.destroy()
    send_button = ui.button(bar, "Send to Pacifica", send, active=True)
    send_button.pack(side="left")
    cancel_button = ui.button(bar, "Cancel", cancel)
    cancel_button.pack(side="left", padx=8)
    window.protocol("WM_DELETE_WINDOW", cancel)
    window.lift()
    window.focus_force()
    return window
