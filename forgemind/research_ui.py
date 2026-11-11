from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .research_lab import LabSession


def pump_research(app):
    session = app._research_session
    if session:
        session.tick()
        app._research_last_message = session.message
        if not session.background and not app.busy:
            app._set_status(session.message)
        if hasattr(app, 'learning_label'):
            app.learning_label.configure(text='Learning · '+session.message if session.background else 'Research running')
        for run in app.research_lab.runs():
            if run["status"] == "completed" and run["id"] not in app._research_reported:
                app._research_reported.add(run["id"])
                # Actual worker metrics, not model-generated success claims.
                report = json.dumps({"experiment": run["id"], "spec": run["spec"],
                    "result": run["result"]}, indent=2)
                app._store_knowledge_text("# Measured tiny-model experiment\n\n" + report,
                                          "research-experiment")
                if not session.background and not app.busy:
                    app._append("assistant", "RESEARCH LAB — MEASURED RESULT\n")
                    app._append("body", f"Run {run['id']}: {run['spec']['family']}; validation loss "
                        f"{run['result']['validation_nll']:.3f}; {run['result']['parameters']:,} parameters. "
                        "This is an experimental model, not an upgrade to the coding assistant.\n\n")
        if not session.active:
            app._research_session = None
            if session.device == 'cuda':
                app.busy = False
                app.send_button.configure(state="normal")
            if session.background:
                app.settings_data.local_learning_enabled = False
                app.settings_data.save()
                app.learning_label.configure(text='Learning paused · '+session.message)
            app.refresh_all()
            if session.device == 'cuda' and not app._closing and app.settings_data.model_path and Path(app.settings_data.model_path).is_file():
                app._load_model(app.settings_data.model_path)
    if not app._closing:
        app.after(500, lambda: pump_research(app))


def open_research_panel(app):
    existing = getattr(app, "_research_panel", None)
    if existing and existing.winfo_exists():
        existing.lift()
        return existing
    window = tk.Toplevel(app)
    app._research_panel = window
    window.title("Doxa — Neural Research Lab")
    window.geometry("960x780")
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(5, weight=1)
    frame.rowconfigure(6, weight=1)
    ttk.Label(frame, text="Neural Research Lab", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(frame, text="Actual weight training · architecture search · checkpoints · measured comparisons",
              style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=5)
    corpus_path = tk.StringVar(value="Original synthetic Python examples (included)")
    selected_corpus = [None]
    settings = ttk.Frame(frame)
    settings.grid(row=2, column=0, sticky="ew", pady=6)
    device = tk.StringVar(value="cpu")
    steps = tk.StringVar(value="300")
    seconds = tk.StringVar(value="60")
    continuous = tk.BooleanVar(value=False)
    ttk.Label(settings, text="Device").pack(side="left")
    ttk.Combobox(settings, textvariable=device, values=("cuda", "cpu"), width=7, state="readonly").pack(side="left", padx=5)
    ttk.Label(settings, text="Max steps/trial").pack(side="left")
    ttk.Entry(settings, textvariable=steps, width=8).pack(side="left", padx=5)
    ttk.Label(settings, text="Max seconds/trial").pack(side="left")
    ttk.Entry(settings, textvariable=seconds, width=8).pack(side="left", padx=5)
    ttk.Checkbutton(settings, text="Keep experimenting until I stop", variable=continuous).pack(side="left", padx=8)
    data_row = ttk.Frame(frame)
    data_row.grid(row=3, column=0, sticky="ew", pady=5)
    ttk.Label(data_row, textvariable=corpus_path, wraplength=580).pack(side="left", fill="x", expand=True)

    def choose():
        path = filedialog.askopenfilename(parent=window, title="Owner-approved training text (read only)",
            filetypes=[("Text corpus", "*.txt *.md *.py *.jsonl"), ("All files", "*.*")])
        if path:
            selected_corpus[0] = Path(path)
            corpus_path.set(path)
    ttk.Button(data_row, text="Choose corpus", command=choose).pack(side="right")
    ttk.Button(data_row, text="Use starter", command=lambda: (selected_corpus.__setitem__(0, None),
        corpus_path.set("Original synthetic Python examples (included)"))).pack(side="right", padx=5)
    controls = ttk.Frame(frame)
    controls.grid(row=4, column=0, sticky="ew", pady=6)
    tree = ttk.Treeview(frame, columns=("state", "family", "params", "score", "time"), show="headings", height=7)
    for column, label, width in (("state", "State", 110), ("family", "Architecture", 140),
                               ("params", "Parameters/counts", 150), ("score", "Validation loss ↓", 150),
                               ("time", "Elapsed seconds", 120)):
        tree.heading(column, text=label)
        tree.column(column, width=width)
    tree.grid(row=5, column=0, sticky="nsew", pady=5)
    details = ScrolledText(frame, height=10, wrap="word", font=("Consolas", 10))
    details.grid(row=6, column=0, sticky="nsew", pady=5)
    status = ttk.Label(frame, wraplength=910)
    status.grid(row=7, column=0, sticky="ew", pady=5)
    ttk.Label(frame, text="Start runs a non-neural n-gram baseline first, then alternates small GRU and Transformer "
        "candidates. The planner mutates validation winners within registered research spaces. Train/validation/test "
        "bytes are split 80/10/10; final test is only opened by Holdout audit, never by the planner. Validation can "
        "be overfit after many trials. This prototype is NOT a general coding model, unrestricted code executor, "
        "LLM fine-tuner, or proof of increasing intelligence. It doesn't replace your chat model. "
        "CPU experiments can run alongside chat. CUDA training temporarily releases the chat model's GPU memory. Closing this panel does not stop training; "
        "use Pause lab or close Doxa. Missing dependencies and actual hardware errors remain visible.",
        style="Muted.TLabel", wraplength=910).grid(row=8, column=0, sticky="ew", pady=6)
    last_signature = [None]

    def selected():
        identifiers = tree.selection()
        return next((run for run in app.research_lab.runs() if str(run["id"]) in identifiers), None)

    def show(_event=None):
        run = selected()
        if not run:
            return
        folder = app.research_lab.run_dir(run["id"])
        text = json.dumps(run, indent=2) + f"\n\nArtifacts: {folder}\n"
        for name in ("sample.txt", "audit.json"):
            path = folder / name
            if path.exists():
                text += f"\n{name}:\n" + path.read_text(encoding="utf-8")[:2500]
        details.configure(state="normal")
        details.delete("1.0", "end")
        details.insert("end", text)
        details.configure(state="disabled")

    def start(*, resume=False, audit=False):
        if app.busy or app._creator_operations or app._computer_controls is not None:
            messagebox.showinfo("Finish current work", "Wait for the active chat, media or computer task to finish.", parent=window)
            return
        try:
            run = selected() if resume or audit else None
            if (resume or audit) and not run:
                raise ValueError("Select the run first.")
            digest = run["corpus"] if run else app.research_lab.corpus(selected_corpus[0])
            session = LabSession(app.research_lab, digest, continuous=continuous.get() and not (resume or audit),
                steps=int(steps.get()), seconds=int(seconds.get()), device=device.get(),
                resume_id=run["id"] if resume else None, audit_id=run["id"] if audit else None)
            app._research_session = session
            if session.device == 'cuda':
                app.busy = True
                app.send_button.configure(state="disabled")
                app.engine.unload()
                app._set_status("Training session owns GPU; chat model released")
            else:
                app._set_status('CPU experiments started; chat model stays available')
            app.refresh_all()
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("Research setup", str(exc), parent=window)

    def stop():
        if app._research_session:
            app._research_session.stop()

    def artifacts():
        run = selected()
        os.startfile(app.research_lab.run_dir(run["id"]) if run else app.research_lab.root)

    def refresh():
        if not window.winfo_exists():
            return
        runs = app.research_lab.runs()
        signature = [(run["id"], run["status"], json.dumps(run["result"])) for run in runs]
        if signature != last_signature[0]:
            selection = tree.selection()
            tree.delete(*tree.get_children())
            for run in runs:
                result = run["result"]
                tree.insert("", "end", iid=str(run["id"]), values=(run["status"], run["spec"]["family"],
                    result.get("parameters", "—"), f"{result['validation_nll']:.3f}" if "validation_nll" in result else "—",
                    f"{result.get('elapsed_seconds', 0):.1f}"))
            for identifier in selection:
                if tree.exists(identifier):
                    tree.selection_add(identifier)
            last_signature[0] = signature
        show()
        status.configure(text=app._research_session.message if app._research_session else
                         getattr(app, "_research_last_message", "Lab paused. Results and checkpoints survive restart. Start a single trial or enable continuous search."))
        window.after(750, refresh)

    ttk.Button(controls, text="Start experiments", command=start).pack(side="left", padx=(0, 6))
    ttk.Button(controls, text="Pause lab", command=stop).pack(side="left", padx=(0, 6))
    ttk.Button(controls, text="Resume selected", command=lambda: start(resume=True)).pack(side="left", padx=(0, 6))
    ttk.Button(controls, text="Holdout audit", command=lambda: start(audit=True)).pack(side="left", padx=(0, 6))
    ttk.Button(controls, text="Open artifacts", command=artifacts).pack(side="left")
    tree.bind("<<TreeviewSelect>>", show)
    refresh()
    return window
