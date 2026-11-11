"""Doxa HQ as its own pop-up window (the owner 2026-11-08: "keep the app how it is … a normal AI chat box … this HQ can
have a kind of pop instead of changing tabs"). A dark Doxa window that hosts the 3D team page (Edge in kiosk mode,
attached as a child by embed_web) and falls back to the classic team cards when that isn't possible. Closing it only
hides it, so it pops back instantly; Doxa closes it for real when Doxa exits.
"""
from __future__ import annotations

import tkinter as tk

from . import jarvis_ui as ui

INK, BONE, BLOOD = "#0b0b0d", "#f2ede4", "#e5383b"


def open_hq_window(app):
    window = getattr(app, "_hq_window", None)
    if window is not None and window.winfo_exists():
        window.deiconify()
        window.lift()
        window.focus_force()
        return window
    window = tk.Toplevel(app)
    window.title("Doxa HQ")
    window.configure(bg=INK)
    screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
    width, height = int(screen_w * 0.8), int(screen_h * 0.82)
    x, y = (screen_w - width) // 2, max(0, (screen_h - height) // 2 - 20)
    window.after(30, lambda: ui._dark_titlebar(window))
    window.protocol("WM_DELETE_WINDOW", window.withdraw)  # hide, don't kill: it pops back instantly
    window.bind("<Escape>", lambda _e: window.withdraw())
    app._hq_window = window

    host = tk.Frame(window, bg=INK, highlightthickness=0, borderwidth=0)
    host.pack(fill="both", expand=True)
    splash = tk.Frame(host, bg=INK)
    splash.place(relx=0.5, rely=0.46, anchor="center")
    tk.Label(splash, text="DOXA HQ", bg=INK, fg=BONE, font=(ui.DISPLAY, 30, "bold")).pack()
    tk.Label(splash, text="waking the team…", bg=INK, fg=BLOOD, font=(ui.BODY_BOLD, 11)).pack(pady=(4, 0))

    def on_state(text):
        if not window.winfo_exists():
            return
        if text == "embedded":
            splash.place_forget()
        elif text != "starting":  # couldn't show the 3D floor here: the classic cards instead, and say why
            app._set_status(text)
            splash.destroy()
            from . import team_view
            team_view.build(app, host).pack(fill="both", expand=True, padx=24, pady=12)

    # the pop: grow from 92% to full size in a few frames (the page attaches a moment later)
    steps = [0.92, 0.96, 0.985, 1.0]

    def grow(i=0):
        if not window.winfo_exists():
            return
        scale = steps[i]
        w, h = int(width * scale), int(height * scale)
        window.geometry(f"{w}x{h}+{x + (width - w) // 2}+{y + (height - h) // 2}")
        if i + 1 < len(steps):
            window.after(28, lambda: grow(i + 1))
        else:
            app.embed_hq(host, on_state)
    grow()
    return window
