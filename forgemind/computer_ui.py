from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from forgemind.computer import Controls, ComputerTask, DesktopBackend, DesktopLease, ScreenEngine
from forgemind.config import app_data_dir
from forgemind import jarvis_ui as ui


def open_computer_panel(app, task=""):
    existing = getattr(app, "_computer_panel", None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return existing
    window = tk.Toplevel(app)
    app._computer_panel = window
    window.title("Doxa · Screen control")
    window.geometry("550x620")
    window.minsize(500, 500)
    window.configure(bg=ui.BG)
    window.attributes("-topmost", True)
    frame = ttk.Frame(window, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Screen control", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, wraplength=490, text=(
        "Controls the primary screen using your Windows account. Start an explicit task; "
        "move your mouse or type to pause. Ctrl+Alt+F11 pauses/resumes. Ctrl+Alt+F12 stops. "
        "A mouse corner also stops input. Keep the target app on your primary monitor."
    )).pack(fill="x", pady=8)
    entry = ScrolledText(frame, height=4, wrap="word", bg=ui.SURFACE, fg=ui.TEXT,
                         insertbackground=ui.BLUE, relief="flat", borderwidth=0, padx=12, pady=12,
                         font=("Segoe UI", 11))
    entry.pack(fill="x")
    entry.insert("1.0", task)
    status = tk.StringVar(value="Local vision ready · review your task, then Start" if app.media_library.vision_ready else "Vision model required (about 2.8 GB)")
    ttk.Label(frame, textvariable=status, wraplength=490).pack(fill="x", pady=8)
    bar = ttk.Frame(frame)
    bar.pack(fill="x")
    log = ScrolledText(frame, height=10, wrap="word", state="disabled", bg=ui.BG, fg=ui.MUTED,
                       relief="flat", borderwidth=0, padx=6, pady=10, font=("Segoe UI", 10))
    log.pack(fill="both", expand=True, pady=8)
    events = queue.Queue()
    active = False
    closed = False
    last_report = None
    controls = None
    previous_pause = False
    previous_stop = False
    controller_rect = None

    def append(text):
        log.configure(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.configure(state="disabled")

    def stop():
        if controls:
            controls.cancel()
            status.set("Stop requested — no next action; waiting for the current model call to return")

    def toggle():
        if controls and active:
            controls.toggle()
            status.set("Paused — take over; Resume re-observes the screen" if controls.paused.is_set() else "Resuming")

    def launch():
        nonlocal active, controls, controller_rect, previous_pause, previous_stop
        goal = entry.get("1.0", "end").strip()
        if not goal or active:
            return
        if app.busy or app._upload_running or app._creator_operations:
            messagebox.showinfo("Work in progress", "Wait for the current task to finish, or stop evolution first.", parent=window)
            return
        if not app.media_library.vision_ready:
            status.set("Click Download vision first. The coding model cannot see the screen.")
            return
        controls = Controls()
        previous_pause = previous_stop = False
        app._computer_controls = controls
        active = True
        app.busy = True
        app.send_button.configure(state="disabled")
        start_button.configure(state="disabled")
        download_button.configure(state="disabled")
        entry.configure(state="disabled")
        window.update_idletasks()
        controller_rect = (window.winfo_rootx(), window.winfo_rooty(),
                           window.winfo_rootx() + window.winfo_width(), window.winfo_rooty() + window.winfo_height())
        # Minimize the main chat without hiding the separate, always-visible controller.
        app.iconify()
        status.set("Loading vision model; choose the app you want it to operate")
        append("OWNER TASK: " + goal)
        previous_model = app.settings_data.model_path if app.engine.loaded else ""

        def work():
            vision = None
            lease = DesktopLease()
            unloaded = False
            final_status = "Task stopped"
            runner = None
            try:
                runner = ComputerTask(goal, controls, None, None,
                                      notify=lambda text: events.put(("status", text)))
                lease.__enter__()
                runner.save("loading", "Loading the local vision model")
                app.engine.unload()
                unloaded = True
                controls.start_listeners()
                if controls.stop.is_set():
                    raise RuntimeError("Stopped before loading vision")
                vision = ScreenEngine(app.media_library)
                for remaining in (3, 2, 1):
                    events.put(("status", f"Control starts in {remaining}s — stop: Ctrl+Alt+F12"))
                    if controls.stop.wait(1):
                        raise RuntimeError("Stopped before desktop input")
                controls.armed = True
                backend = DesktopBackend(controls, lambda: controller_rect)
                runner.backend, runner.engine = backend, vision
                result = runner.run()
                final_status = result["status"] + ": " + result.get("reason", "")
                events.put(("result", result))
            except Exception as exc:
                final_status = "Task did not finish: " + str(exc)
                events.put(("status", final_status))
                if runner:
                    try:
                        runner.save("stopped" if controls.stop.is_set() else "needs_input", str(exc))
                        events.put(("result", dict(runner.state, report=str(runner.run_dir / "task.json"))))
                    except Exception as report_error:
                        events.put(("status", "Could not save task report: " + str(report_error)))
            finally:
                try:
                    controls.close()
                    if vision:
                        vision.close()
                    if unloaded and previous_model and not getattr(app, "_closing", False):
                        events.put(("status", "Restoring your local coding model…"))
                        app.engine.load(previous_model, app.settings_data.context_size)
                except Exception as exc:
                    final_status += " · Cleanup/model reload needs attention: " + str(exc)
                finally:
                    try:
                        lease.__exit__(None, None, None)
                    finally:
                        events.put(("finished", final_status))

        threading.Thread(target=work, daemon=True).start()

    def download():
        nonlocal active, controls
        if active or app.busy:
            return
        if app.media_library.vision_ready:
            status.set("Vision model already downloaded")
            return
        active = True
        controls = None
        app.busy = True
        app.send_button.configure(state="disabled")
        start_button.configure(state="disabled")
        download_button.configure(state="disabled")

        def work():
            final_status = "Vision download complete — enter a task and click Start"
            try:
                app.media_library.download_vision_models(lambda text: events.put(("status", text)))
                events.put(("status", final_status))
            except Exception as exc:
                final_status = "Vision download failed: " + str(exc)
                events.put(("status", final_status))
            finally:
                events.put(("finished", final_status))
        threading.Thread(target=work, daemon=True).start()

    start_button = ttk.Button(bar, text="Start task", command=launch, style="Accent.TButton")
    start_button.pack(side="left")
    ttk.Button(bar, text="Pause / Resume", command=toggle).pack(side="left", padx=6)
    ttk.Button(bar, text="STOP", command=stop).pack(side="left")
    download_button = ttk.Button(frame, text="Download vision (local GPU)", command=download)
    download_button.pack(anchor="w")

    def report():
        destination = Path(last_report).parent if last_report else app_data_dir() / "computer"
        destination.mkdir(parents=True, exist_ok=True)
        os.startfile(str(destination))
    ttk.Button(frame, text="Open task logs", command=report).pack(anchor="w", pady=(6, 0))

    def close():
        nonlocal closed
        if active:
            stop()
            status.set("Stopping… keep this controller open until cleanup finishes")
            return
        closed = True
        app._computer_panel = None
        window.destroy()
        app.deiconify()
        app._touch_activity()

    def pump():
        nonlocal active, last_report, previous_pause, previous_stop, controller_rect
        if closed or not window.winfo_exists():
            return
        controller_rect = (window.winfo_rootx(), window.winfo_rooty(),
                           window.winfo_rootx() + window.winfo_width(), window.winfo_rooty() + window.winfo_height())
        try:
            while True:
                event = events.get_nowait()
                if event[0] == "status":
                    status.set(event[1])
                    append(event[1])
                elif event[0] == "result":
                    result = event[1]
                    last_report = result["report"]
                    summary = f"{result['status']} · {result['steps']} actions · {result.get('reason', '')}"
                    try:
                        app.db.add_message("user", "[Computer task] " + result["task"])
                        app.db.add_message("assistant", summary + "\nTask report: " + last_report)
                        app._store_knowledge_text(summary + "\nTask: " + result["task"] + "\nReport: " + last_report,
                                                  "computer-task-result")
                    except Exception as exc:
                        append("Memory indexing needs attention: " + str(exc))
                    append("REPORT: " + last_report)
                    status.set(summary)
                elif event[0] == "finished":
                    active = False
                    app.busy = False
                    app._computer_controls = None
                    app.send_button.configure(state="normal")
                    start_button.configure(state="normal")
                    download_button.configure(state="normal")
                    entry.configure(state="normal")
                    app._touch_activity()
                    app.refresh_all()
                    status.set(event[1])
                    append("Computer control released. You can start another task.")
        except queue.Empty:
            pass
        if active and controls and controls.paused.is_set() != previous_pause:
            previous_pause = controls.paused.is_set()
            if previous_pause:
                status.set(controls.reason + " — click Pause / Resume or Ctrl+Alt+F11")
                append("OWNER OVERRIDE: " + controls.reason)
        if active and controls and controls.stop.is_set() and not previous_stop:
            previous_stop = True
            status.set("STOP requested — waiting for the current model call; no next input")
            append("OWNER STOP: no further actions will be dispatched")
        window.after(100, pump)

    window.protocol("WM_DELETE_WINDOW", close)
    window.after(100, pump)
    return window
