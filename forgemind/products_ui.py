"""Product hunter panel (Tools → Product hunter, or say "find winning products [for pets]")."""
from __future__ import annotations

import os
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import jarvis_ui as ui
from . import products

STATUS_LABELS = {"new": "New", "testing": "Testing", "winner": "Winner", "dud": "Dud", "skip": "Skip"}


def open_hunter(app, niche: str = ""):
    from .calendar_ui import _entry
    window, content = ui._panel(
        app, "Product hunter",
        "Doxa searches the web for what's trending, then Claude or OpenAI picks and scores products worth testing: wow "
        "factor, problem solved, margin, easy to film, not saturated, easy to ship. You get supplier links, hooks and a "
        "test plan. Your test videos pick the winner. Mark results below and the next hunt learns from them.",
        size="680x800")
    tk.Label(content, text="Niche (optional, e.g. pets, kitchen, car, gym, home decor)", bg=ui.BG, fg=ui.MUTED,
             font=(ui.BODY_BOLD, 9), anchor="w").pack(fill="x", pady=(8, 2))
    niche_var = tk.StringVar(value=niche)
    _entry(content, niche_var).pack(fill="x")
    clouds = app.brain.clouds(app.settings_data) if getattr(app, "brain", None) else []
    status = tk.StringVar(value=(f"Uses {clouds[0].display_name} · about 5-15¢ of your monthly cloud budget per hunt."
                                 if clouds else "Connect Claude or OpenAI in Tools → AI brains to hunt."))
    row = tk.Frame(content, bg=ui.BG)
    row.pack(fill="x", pady=(12, 4))

    def hunt_now():
        if app.start_product_hunt("Find winning products" + (f" for {niche_var.get().strip()}" if niche_var.get().strip()
                                                             else ""), niche_var.get().strip()):
            status.set("Hunting… results will appear in chat in about a minute. You can close this window.")

    ui.button(row, "Hunt now", hunt_now, active=True).pack(side="left")
    ui.button(row, "Open latest report", lambda: _open_latest(app, status), small=True).pack(side="left", padx=8)
    ui.button(row, "Reports folder", lambda: _open_folder(status), small=True).pack(side="left")
    tk.Label(content, textvariable=status, bg=ui.BG, fg=ui.GOLD, font=(ui.BODY, 10), anchor="w", justify="left",
             wraplength=600).pack(fill="x", pady=4)

    daily = tk.BooleanVar(value=bool(app.settings_data.product_hunt_daily))

    def save_daily():
        app.settings_data.product_hunt_daily = bool(daily.get())
        app.settings_data.save()

    ttk.Checkbutton(content, variable=daily, command=save_daily,
                    text="Hunt automatically every morning (after 8:30, when the PC is idle; results land in chat)"
                    ).pack(anchor="w", pady=(6, 2))

    tk.Label(content, text="YOUR PRODUCTS", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY_BOLD, 9), anchor="w").pack(
        fill="x", pady=(18, 4))
    history = list(reversed(app.products.history()))[:30]
    if not history:
        tk.Label(content, text="No hunts yet. Press Hunt now.", bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 10),
                 anchor="w").pack(fill="x")
    for item in history:
        line = tk.Frame(content, bg=ui.BG)
        line.pack(fill="x", pady=1)
        tk.Label(line, text=f"{item['name']}", bg=ui.BG, fg=ui.TEXT, font=(ui.BODY, 10), anchor="w").pack(
            side="left", fill="x", expand=True)
        tk.Label(line, text=f"{item.get('score', 0):.0f} · {item.get('date', '')[:10]}", bg=ui.BG, fg=ui.FAINT,
                 font=(ui.BODY, 9)).pack(side="left", padx=8)
        choice = tk.StringVar(value=STATUS_LABELS.get(item.get("status", "new"), "New"))
        box = ttk.Combobox(line, textvariable=choice, values=list(STATUS_LABELS.values()), state="readonly", width=9)
        box.pack(side="right")

        def changed(_event=None, product_id=item["id"], choice=choice):
            key = next(k for k, v in STATUS_LABELS.items() if v == choice.get())
            app.products.mark(product_id, key)
            status.set("Saved. The next hunt will learn from it.")
        box.bind("<<ComboboxSelected>>", changed)
    tk.Label(content, text=products.TEST_PLAN, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w", justify="left",
             wraplength=600).pack(fill="x", pady=(18, 4))
    return window


def _open_latest(app, status):
    hunts = app.products.load().get("hunts") or []
    report = hunts[-1]["report"] if hunts else ""
    if report and os.path.isfile(report):
        webbrowser.open(report)
    else:
        status.set("No report yet. Press Hunt now.")


def _open_folder(status):
    folder = products.output_dir()
    if folder.is_dir():
        os.startfile(folder)  # noqa: S606 - opens Explorer on Doxa's own folder
    else:
        status.set("No reports yet. Press Hunt now.")
