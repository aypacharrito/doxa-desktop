"""The Code side of the Chat | Code switch: Codex / Claude Code jobs in the main window (like Claude's Code tab).

The shared message box sends here while Code is selected (`app.send` → `app.start_code_job`). Live steps, what the
agent says and the final report are shown in one scrolling log; follow-ups continue the same agent chat."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from . import jarvis_ui as ui
from .code_mode import ENGINE_NAMES, short

ENGINE_LABELS = [("auto", "Automatic"), ("codex", "Codex"), ("claude", "Claude Code")]


def build(app, parent) -> tk.Frame:
    frame = tk.Frame(parent, bg=ui.BG)
    app.code_engine_var = tk.StringVar(value="auto")
    app.code_folder_var = tk.StringVar(value="")
    app.code_fresh_var = tk.BooleanVar(value=False)

    bar = tk.Frame(frame, bg=ui.BG)
    bar.pack(fill="x", pady=(10, 4))
    engines = ui.Segmented(bar, ENGINE_LABELS, lambda value: (app.code_engine_var.set(value), engines.select(value)),
                           height=30, font_size=9)
    engines.pack(side="left")
    fresh = {}

    def toggle_fresh():
        app.code_fresh_var.set(not app.code_fresh_var.get())
    fresh_link = ui.link(bar, "New chat", toggle_fresh)
    fresh_link.pack(side="right")
    app.code_fresh_var.trace_add("write", lambda *_: fresh_link.configure(
        text="✓ New chat" if app.code_fresh_var.get() else "New chat",
        fg=ui.GOLD if app.code_fresh_var.get() else ui.MUTED))
    folder_label = tk.Label(bar, text="", bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9))

    def browse():
        chosen = filedialog.askdirectory(parent=app, title="Folder for Code mode")
        if chosen:
            app.code_folder_var.set(os.path.normpath(chosen))
    ui.link(bar, "Choose folder", browse).pack(side="right", padx=(0, 18))
    folder_label.pack(side="right", padx=(0, 10))

    def show_folder(*_):
        value = app.code_folder_var.get().strip()
        folder_label.configure(text=("Folder: " + short(value, 60)) if value else "New folder in Documents\\Doxa Code")
    app.code_folder_var.trace_add("write", show_folder)
    show_folder()

    log = tk.Text(frame, wrap="word", bg=ui.BG, fg=ui.TEXT, relief="flat", borderwidth=0, highlightthickness=0,
                  font=(ui.BODY, 11), padx=8, pady=14, spacing1=3, spacing3=6, state="disabled",
                  selectbackground=ui.SELECT)
    box = log
    log.pack(fill="both", expand=True)
    log.tag_configure("head", foreground=ui.TEXT, font=(ui.BODY_BOLD, 11), spacing1=16)
    log.tag_configure("intro", foreground=ui.MUTED, font=(ui.BODY, 11))
    log.tag_configure("step", foreground=ui.FAINT, font=(ui.BODY, 9), lmargin1=14, lmargin2=24)
    log.tag_configure("say", foreground=ui.TEXT, font=(ui.BODY, 11))
    log.tag_configure("report", foreground=ui.TEXT, font=(ui.BODY, 11), lmargin1=10, lmargin2=10)
    app.code_log = log
    state = {"job": None, "steps": 0, "reported": None}

    def write(text, tag):
        log.configure(state="normal")
        log.insert("end", text, tag)
        log.see("end")
        log.configure(state="disabled")

    found = app.code_runner.available() if getattr(app, "code_runner", None) else {}
    ready = ", ".join(ENGINE_NAMES[name] for name in found) or "none yet"
    write("Give Codex or Claude Code a job: build an app, fix a project, or reverse-engineer a program or file.\n"
          f"Ready on this PC: {ready}. It works with full access and reports back here. Follow-ups continue the "
          "same chat.\n", "intro")

    def refresh():
        if not frame.winfo_exists():
            return
        job = app.code_runner.job if getattr(app, "code_runner", None) else None
        if job is not None:
            if job is not state["job"]:
                state.update(job=job, steps=0, reported=None)
                title = ("Continuing " if job.continued else "") + f"{job.name} · {short(job.task, 160)}"
                write("\n" + title + "\n", "head")
            for step in job.steps[state["steps"]:]:
                if step.startswith(job.name + ": "):
                    write(step[len(job.name) + 2:] + "\n", "say")
                else:
                    write("• " + short(step, 220) + "\n", "step")
            state["steps"] = len(job.steps)
            if job.status != "running" and state["reported"] is not job:
                state["reported"] = job
                write("\n" + job.report() + "\n", "report")
        frame.after(700, refresh)
    refresh()
    return frame
