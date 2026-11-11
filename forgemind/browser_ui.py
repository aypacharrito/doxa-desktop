"""Browser task panel. The task itself lives in app.browser_controller, shared with the phone."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from forgemind import jarvis_ui as ui
from forgemind.browser_agent import planner_ready
from forgemind.config import app_data_dir


def open_browser_panel(app, task=""):
    controller = app.browser_controller
    existing = getattr(app, "_browser_panel", None)
    if existing is not None and existing.winfo_exists():
        if task and not controller.running:
            existing._set_task(task)
        existing.deiconify()
        existing.lift()
        return existing

    window = tk.Toplevel(app)
    app._browser_panel = window
    window.title("Doxa · Browser task")
    window.geometry("560x700")
    window.minsize(500, 540)
    window.configure(bg=ui.BG)
    frame = ttk.Frame(window, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Browser task", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, wraplength=500, text=(
        "Doxa works in its own browser window, so your mouse and main browser stay yours. "
        "It asks for details it doesn't know, hands you passwords and human checks, and waits for "
        "your OK before anything that books, submits or pays. You can also answer from your phone."
    )).pack(fill="x", pady=8)
    entry = ScrolledText(frame, height=4, wrap="word", bg=ui.SURFACE, fg=ui.TEXT, insertbackground=ui.BLUE,
                         relief="flat", borderwidth=0, padx=12, pady=12, font=("Segoe UI", 11))
    entry.pack(fill="x")
    entry.insert("1.0", task)
    status = tk.StringVar(value="Review the task, then Start.")
    ttk.Label(frame, textvariable=status, wraplength=500).pack(fill="x", pady=8)
    bar = ttk.Frame(frame)
    bar.pack(fill="x")

    prompt_box = ttk.Frame(frame, padding=(0, 10, 0, 0))
    prompt_title = ttk.Label(prompt_box, wraplength=500, style="Title.TLabel")
    prompt_body = ttk.Label(prompt_box, wraplength=500, justify="left")
    answer_var = tk.StringVar()
    answer_entry = ttk.Entry(prompt_box, textvariable=answer_var, font=("Segoe UI", 11))
    remember_var = tk.BooleanVar(value=False)
    remember_box = ttk.Checkbutton(prompt_box, text="Remember this for future tasks", variable=remember_var)
    prompt_buttons = ttk.Frame(prompt_box)

    log = ScrolledText(frame, height=12, wrap="word", state="disabled", bg=ui.BG, fg=ui.MUTED, relief="flat",
                       borderwidth=0, padx=6, pady=10, font=("Segoe UI", 10))
    log.pack(fill="both", expand=True, pady=8)
    view = {"lines": 0, "pending": None, "running": False, "closed": False}

    def set_task(text):
        entry.configure(state="normal")
        entry.delete("1.0", "end")
        entry.insert("1.0", text)
    window._set_task = set_task

    def clear_prompt():
        for widget in (prompt_title, prompt_body, answer_entry, remember_box, prompt_buttons):
            widget.pack_forget()
        for child in prompt_buttons.winfo_children():
            child.destroy()
        prompt_box.pack_forget()

    def answer(request_id):
        text = answer_var.get().strip()
        if text:
            controller.respond(request_id, (text, remember_var.get()))

    def show_pending(pending):
        clear_prompt()
        if not pending:
            return
        prompt_box.pack(fill="x", before=log)
        window.deiconify()
        window.lift()
        rid = pending["id"]
        if pending["kind"] == "ask":
            prompt_title.configure(text="Doxa asks: " + pending["text"])
            prompt_title.pack(anchor="w")
            answer_var.set("")
            remember_var.set(False)
            answer_entry.pack(fill="x", pady=6)
            remember_box.pack(anchor="w")
            prompt_buttons.pack(fill="x", pady=6)
            ttk.Button(prompt_buttons, text="Answer", style="Accent.TButton", command=lambda: answer(rid)).pack(side="left")
            ttk.Button(prompt_buttons, text="Skip — stop the task", command=lambda: controller.respond(rid, None)).pack(side="left", padx=6)
            answer_entry.bind("<Return>", lambda _e: answer(rid))
            answer_entry.focus_set()
            status.set("Doxa needs a detail from you.")
        elif pending["kind"] == "hand_off":
            prompt_title.configure(text=pending["text"])
            prompt_title.pack(anchor="w")
            prompt_buttons.pack(fill="x", pady=6)
            ttk.Button(prompt_buttons, text="Continue", style="Accent.TButton", command=lambda: controller.respond(rid, True)).pack(side="left")
            ttk.Button(prompt_buttons, text="Stop task", command=lambda: controller.respond(rid, False)).pack(side="left", padx=6)
            status.set("Your turn in the Doxa browser window.")
        else:
            prompt_title.configure(text="Approve? " + pending["title"])
            prompt_title.pack(anchor="w")
            prompt_body.configure(text=pending["body"])
            prompt_body.pack(fill="x", pady=4)
            prompt_buttons.pack(fill="x", pady=6)
            ttk.Button(prompt_buttons, text="Approve", style="Accent.TButton", command=lambda: controller.respond(rid, True)).pack(side="left")
            ttk.Button(prompt_buttons, text="Decline — submit nothing", command=lambda: controller.respond(rid, False)).pack(side="left", padx=6)
            status.set("Waiting for your approval.")
            window.bell()

    def launch():
        goal = entry.get("1.0", "end").strip()
        if not goal or controller.running:
            return
        if not planner_ready(getattr(app, "brain", None), app.settings_data, app.engine):
            status.set("Connect Claude or OpenAI in Tools → AI brains (recommended for real sites), "
                       "or load your local model first. Browser tasks use it to decide each step.")
            return
        if getattr(app, "_computer_controls", None):
            status.set("Screen control is running. Wait for it to finish first.")
            return
        try:
            controller.start(goal)
        except (ValueError, RuntimeError) as exc:
            status.set(str(exc))

    def toggle_pause():
        paused = controller.toggle_pause()
        status.set("Paused. You can use the Doxa browser window." if paused else "Running.")

    start_button = ttk.Button(bar, text="Start", command=launch, style="Accent.TButton")
    start_button.pack(side="left")
    ttk.Button(bar, text="Pause / Resume", command=toggle_pause).pack(side="left", padx=6)
    ttk.Button(bar, text="STOP", command=controller.stop).pack(side="left")

    def open_logs():
        target = app_data_dir() / "browser" / "runs"
        target.mkdir(parents=True, exist_ok=True)
        os.startfile(str(target))

    def forget():
        if messagebox.askyesno("Forget details", "Forget all details Doxa remembered for browser tasks?", parent=window):
            controller.facts.forget_all()
            status.set("Remembered details cleared.")

    extras = ttk.Frame(frame)
    extras.pack(fill="x")
    ttk.Button(extras, text="Open task logs", command=open_logs).pack(side="left")
    ttk.Button(extras, text="Forget remembered details", command=forget).pack(side="left", padx=6)

    def poll():
        if view["closed"] or not window.winfo_exists():
            return
        state = controller.state()
        lines = state["log"]
        if len(lines) < view["lines"]:
            view["lines"] = 0
            log.configure(state="normal")
            log.delete("1.0", "end")
            log.configure(state="disabled")
        if len(lines) > view["lines"]:
            log.configure(state="normal")
            for line in lines[view["lines"]:]:
                log.insert("end", line + "\n")
            log.see("end")
            log.configure(state="disabled")
            view["lines"] = len(lines)
            if not state["pending"] and lines:
                status.set(lines[-1][:200])
        pending_id = state["pending"]["id"] if state["pending"] else None
        if pending_id != view["pending"]:
            view["pending"] = pending_id
            show_pending(state["pending"])
        if state["running"] != view["running"]:
            view["running"] = state["running"]
            entry.configure(state="disabled" if state["running"] else "normal")
            start_button.configure(state="disabled" if state["running"] else "normal")
            if state["running"] and state["task"]:
                set_task(state["task"])
                entry.configure(state="disabled")
        window.after(300, poll)

    def close():
        if controller.running and not messagebox.askyesno(
                "Browser task running", "Keep the task running in the background? Choose No to stop it.", parent=window):
            controller.stop()
        view["closed"] = True
        app._browser_panel = None
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    window.after(100, poll)
    return window
