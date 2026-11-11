from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


def open_growth_panel(app):
    window = tk.Toplevel(app)
    window.title("Doxa — Growth Lab")
    window.geometry("900x750")
    window.transient(app)
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(3, weight=1)
    frame.rowconfigure(4, weight=1)
    ttk.Label(frame, text="Growth Lab", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    status = ttk.Label(frame, wraplength=850)
    status.grid(row=1, column=0, sticky="ew", pady=8)
    controls = ttk.Frame(frame)
    controls.grid(row=2, column=0, sticky="ew", pady=5)
    tree = ttk.Treeview(frame, columns=("state", "goal"), show="headings", height=7)
    tree.heading("state", text="State")
    tree.heading("goal", text="Upgrade")
    tree.column("state", width=130, stretch=False)
    tree.column("goal", width=680)
    tree.grid(row=3, column=0, sticky="nsew", pady=5)
    details = ScrolledText(frame, height=8, wrap="word", font=("Segoe UI", 10))
    details.grid(row=4, column=0, sticky="nsew", pady=5)
    ttk.Label(frame, text="Priorities for the automatic planner").grid(row=5, column=0, sticky="w", pady=(5, 2))
    priorities = tk.StringVar(value=app.growth.preference("priorities"))
    ttk.Entry(frame, textvariable=priorities).grid(row=6, column=0, sticky="ew")
    ttk.Button(frame, text="Save priorities", command=lambda:
               app.growth.configure(priorities=priorities.get().strip()[:2000])).grid(row=7, column=0, sticky="w", pady=5)
    ttk.Label(frame, text="Add a concrete upgrade goal").grid(row=8, column=0, sticky="w")
    goal = tk.StringVar()
    ttk.Entry(frame, textvariable=goal).grid(row=9, column=0, sticky="ew", pady=4)
    ttk.Label(frame, text="How should it be verified?").grid(row=10, column=0, sticky="w")
    acceptance = tk.StringVar(value="Add tests that demonstrate the feature and preserve existing behavior.")
    ttk.Entry(frame, textvariable=acceptance).grid(row=11, column=0, sticky="ew", pady=4)
    note = ttk.Label(frame, text="When enabled, Doxa works after 60 seconds of inactivity. It researches, edits, "
        "tests, repairs, and installs verified upgrades, then restarts when idle. Failed goals remain visible; "
        "the queue can proceed to another goal. This changes application code, not neural weights.",
        style="Muted.TLabel", wraplength=850)
    note.grid(row=13, column=0, sticky="ew", pady=8)
    last_signature = None

    def selected():
        selection = tree.selection()
        return next((item for item in app.growth.tasks() if str(item["id"]) in selection), None)

    def show(_event=None):
        task = selected()
        if not task:
            return
        text = f"Goal: {task['goal']}\n\nVerification target: {task['acceptance']}\n\nOrigin: {task['origin']}\n"
        if task["result"]:
            result = json.loads(task["result"])
            text += (f"\nResult: {result.get('summary', '')}\nTests passed: {result.get('tests_passed', False)}"
                     f"\nAttempts: {result.get('attempts', 0)}\nElapsed: {result.get('elapsed_seconds', 0):.1f}s"
                     f"\nChanged files: {', '.join(result.get('changed_files', []))}"
                     f"\nAudit report: {result.get('report_path', '')}")
        details.configure(state="normal")
        details.delete("1.0", "end")
        details.insert("end", text)
        details.configure(state="disabled")

    def refresh():
        nonlocal last_signature
        tasks = app.growth.tasks()
        enabled = app.growth.preference("enabled")
        counts = {state: sum(item["status"] == state for item in tasks)
                  for state in ("pending", "running", "installed", "verified", "needs_attention")}
        status.configure(text=f"Automatic improvement {'ON' if enabled else 'PAUSED'} · "
            f"{counts['pending']} pending · {counts['running']} running · {counts['installed']} installed · "
            f"{counts['verified']} verified · {counts['needs_attention']} need attention")
        signature = [(item["id"], item["status"], item["result"]) for item in tasks]
        if signature != last_signature:
            selection = tree.selection()
            tree.delete(*tree.get_children())
            for item in tasks:
                tree.insert("", "end", iid=str(item["id"]), values=(item["status"], item["title"]))
            for identifier in selection:
                if tree.exists(identifier):
                    tree.selection_add(identifier)
            last_signature = signature
            show()
        if window.winfo_exists():
            window.after(1000, refresh)

    def add():
        try:
            identifier = app.growth.add(goal.get()[:80], goal.get(), acceptance.get())
            status.configure(text="Upgrade queued." if identifier else "That goal is already in the backlog.")
            goal.set("")
        except ValueError as exc:
            status.configure(text=str(exc))

    def retry():
        task = selected()
        if task:
            try:
                app.growth.retry(task["id"])
            except ValueError as exc:
                status.configure(text=str(exc))

    ttk.Button(controls, text="Resume automatic growth", command=lambda:
               app.growth.configure(enabled=True)).pack(side="left", padx=(0, 6))
    ttk.Button(controls, text="Pause growth", command=app.stop_current_work).pack(side="left", padx=(0, 6))
    ttk.Button(controls, text="Plan next upgrades", command=lambda: app._plan_growth(force=True)).pack(side="left", padx=(0, 6))
    ttk.Button(controls, text="Retry selected", command=retry).pack(side="left")
    ttk.Button(frame, text="Queue upgrade", command=add).grid(row=12, column=0, sticky="w", pady=4)
    tree.bind("<<TreeviewSelect>>", show)
    refresh()
