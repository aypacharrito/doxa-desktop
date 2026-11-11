"""Code mode panel (Tools → Code mode): pick a folder (or none), describe the job, Start; live steps; Stop."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from . import jarvis_ui as ui
from .code_mode import ENGINE_NAMES, short


def open_panel(app, task: str = "", folder: str = ""):
    from .calendar_ui import _entry
    runner = app.code_runner
    window, content = ui._panel(
        app, "Code mode",
        "Give Doxa any software job: build an app or script, fix a project, or reverse-engineer a program or file. "
        "It runs Codex (your ChatGPT sign-in) or Claude Code on this PC with full access, no prompts. Files it replaces "
        "outside the job folder are copied to Documents\\Doxa Code\\_backups first.", size="720x780")

    tk.Label(content, text="Folder (leave empty for a new one in Documents\\Doxa Code)", bg=ui.BG, fg=ui.MUTED,
             font=(ui.BODY_BOLD, 9), anchor="w").pack(fill="x", pady=(4, 2))
    row = tk.Frame(content, bg=ui.BG)
    row.pack(fill="x")
    folder_var = tk.StringVar(value=folder)
    _entry(row, folder_var).pack(side="left", fill="x", expand=True)

    def browse():
        chosen = filedialog.askdirectory(parent=window, title="Folder for this job")
        if chosen:
            folder_var.set(os.path.normpath(chosen))
    ui.button(row, "Browse…", browse, small=True).pack(side="left", padx=(8, 0))

    tk.Label(content, text="What should it do?", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY_BOLD, 9),
             anchor="w").pack(fill="x", pady=(10, 2))
    box = tk.Text(content, height=6, wrap="word", bg=ui.SURFACE_2, fg=ui.TEXT, insertbackground=ui.GOLD, relief="flat",
                  borderwidth=6, highlightthickness=1, highlightbackground=ui.LINE, highlightcolor=ui.GOLD_DIM,
                  font=(ui.BODY, 10))
    box.pack(fill="x")
    if task:
        box.insert("1.0", task)

    found = runner.available()
    choices = ["Automatic"] + [ENGINE_NAMES[name] for name in found]
    engine_var = tk.StringVar(value="Automatic")
    options = tk.Frame(content, bg=ui.BG)
    options.pack(fill="x", pady=(10, 0))
    tk.Label(options, text="Engine", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY_BOLD, 9)).pack(side="left")
    ttk.Combobox(options, textvariable=engine_var, values=choices, state="readonly", width=16).pack(side="left", padx=8)
    ready = ", ".join(ENGINE_NAMES[name] for name in found) or "none yet (sign in to Codex or connect Claude)"
    tk.Label(options, text=f"Ready: {ready}", bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9)).pack(side="left")

    buttons = tk.Frame(content, bg=ui.BG)
    buttons.pack(fill="x", pady=(12, 6))
    status = tk.StringVar()
    tk.Label(content, textvariable=status, bg=ui.BG, fg=ui.GOLD, font=(ui.BODY, 9), anchor="w", justify="left",
             wraplength=660).pack(fill="x")
    log = tk.Text(content, height=16, wrap="word", bg=ui.SURFACE, fg=ui.MUTED, relief="flat", borderwidth=8,
                  highlightthickness=0, font=("Consolas", 9), state="disabled")
    log.pack(fill="both", expand=True, pady=(6, 0))
    shown = {"steps": 0}

    def start():
        engine = {v: k for k, v in ENGINE_NAMES.items()}.get(engine_var.get(), "auto")
        text = box.get("1.0", "end").strip()
        app.start_code_job(text, text, folder_var.get().strip() or None, engine)

    def refresh():
        if not window.winfo_exists():
            return
        job = runner.job
        if job is not None:
            status.set(f"{job.name} · {job.status} · {job.folder}")
            new = job.steps[shown["steps"]:]
            if new:
                log.configure(state="normal")
                for step in new:
                    log.insert("end", "• " + short(step, 300) + "\n")
                log.see("end")
                log.configure(state="disabled")
                shown["steps"] = len(job.steps)
        start_button.configure(state="disabled" if runner.running else "normal")
        stop_button.configure(state="normal" if runner.running else "disabled")
        window.after(700, refresh)

    start_button = ui.button(buttons, "Start", start, active=True)
    start_button.pack(side="left")
    stop_button = ui.button(buttons, "Stop", lambda: runner.stop(), small=True)
    stop_button.pack(side="left", padx=8)
    ui.button(buttons, "Open folder", lambda: os.startfile(str(runner.job.folder)) if runner.job else None,
              small=True).pack(side="left")
    refresh()
    return window
