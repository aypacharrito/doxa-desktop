from __future__ import annotations

import os
import queue
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from forgemind.clips import ClipStudio, timestamp
from forgemind.youtube import YouTubePublisher


def open_creator_panel(app) -> None:
    window = tk.Toplevel(app)
    window.title("Doxa — Clips & YouTube Shorts")
    window.geometry("960x810")
    window.minsize(820, 730)
    window.transient(app)
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(3, weight=1)
    frame.rowconfigure(10, weight=1)
    events = queue.Queue()
    active = False
    library = app.media_library
    studio = app.clip_studio
    publisher = YouTubePublisher()
    records = []
    proposals = []
    exported = []
    current_job = None

    ttk.Label(frame, text="Clips & YouTube Shorts", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
    status = ttk.Label(frame, text="Choose a recording. Analyze it in Media library first for AI suggestions.", wraplength=880)
    status.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
    ttk.Label(frame, text="Recording").grid(row=2, column=0, sticky="w")
    recording = ttk.Combobox(frame, state="readonly")
    recording.grid(row=2, column=1, sticky="ew", padx=8)
    suggestions = tk.Listbox(frame, exportselection=False, height=5)
    suggestions.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=8)
    editor = ttk.Frame(frame)
    editor.grid(row=4, column=0, columnspan=3, sticky="ew")
    start = tk.StringVar(value="0")
    end = tk.StringVar(value="30")
    title = tk.StringVar(value="My recording highlight")
    layout = tk.StringVar(value="fit")
    burn = tk.BooleanVar(value=True)
    auto_upload = tk.BooleanVar(value=False)
    privacy = tk.StringVar(value="private")
    kids = tk.BooleanVar(value=False)
    for text, variable in (("Start", start), ("End", end)):
        ttk.Label(editor, text=text).pack(side="left", padx=(0, 4))
        ttk.Entry(editor, textvariable=variable, width=12).pack(side="left", padx=(0, 10))
    ttk.Label(editor, text="seconds or MM:SS").pack(side="left")
    ttk.Label(frame, text="Title").grid(row=5, column=0, sticky="w")
    ttk.Entry(frame, textvariable=title).grid(row=5, column=1, columnspan=2, sticky="ew", padx=8, pady=6)
    options = ttk.Frame(frame)
    options.grid(row=6, column=0, columnspan=3, sticky="ew")
    ttk.Radiobutton(options, text="Fit full frame", variable=layout, value="fit").pack(side="left")
    ttk.Radiobutton(options, text="Center crop", variable=layout, value="crop").pack(side="left", padx=8)
    ttk.Checkbutton(options, text="Burn transcript captions", variable=burn).pack(side="left")
    ttk.Checkbutton(options, text="Upload after export", variable=auto_upload).pack(side="left", padx=8)
    publish_options = ttk.Frame(frame)
    publish_options.grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)
    ttk.Label(publish_options, text="YouTube visibility").pack(side="left")
    ttk.Combobox(publish_options, textvariable=privacy, values=["private", "unlisted", "public"],
                 state="readonly", width=10).pack(side="left", padx=8)
    ttk.Checkbutton(publish_options, text="Made for kids", variable=kids).pack(side="left")
    actions = ttk.Frame(frame)
    actions.grid(row=8, column=0, columnspan=3, sticky="ew", pady=6)
    connections = ttk.Frame(frame)
    connections.grid(row=9, column=0, columnspan=3, sticky="ew", pady=6)
    jobs = tk.Listbox(frame, exportselection=False, height=5)
    jobs.grid(row=10, column=0, columnspan=3, sticky="nsew", pady=6)
    ttk.Label(frame, text="Exports are 720×1280 MP4. NVIDIA encoding is attempted first, with a CPU fallback. "
              "Uploads queued by you continue while Doxa is open. Reopen the app to resume queued jobs.",
              wraplength=880, style="Muted.TLabel").grid(row=11, column=0, columnspan=3, sticky="ew")

    def refresh():
        nonlocal records, exported
        previous = recording.current()
        selected_job = jobs.curselection()
        selected_id = exported[selected_job[0]]["id"] if selected_job and exported else None
        records = [r for r in library.list_records() if r["type"] == "video"]
        recording.configure(values=[r["name"] for r in records])
        if records:
            recording.current(min(max(previous, 0), len(records) - 1))
        exported = studio.jobs()
        jobs.delete(0, "end")
        for job in exported:
            note = " — check YouTube Studio before retrying" if job["status"] == "uploading" else ""
            jobs.insert("end", f"{job['status']} · {job['title']} · {job['start']:.1f}–{job['end']:.1f}s{note}")
        for index, job in enumerate(exported):
            if job["id"] == selected_id:
                jobs.selection_set(index)

    def chosen_record():
        index = recording.current()
        if index < 0:
            raise ValueError("Add an OBS recording in Media library first.")
        return records[index]

    def background(operation, uses_model=False):
        nonlocal active
        if active or (uses_model and app.busy):
            status.configure(text="Wait for the current operation to finish.")
            return
        active = True
        app._creator_operations = getattr(app, "_creator_operations", 0) + 1
        if uses_model:
            app.busy = True
            app.send_button.configure(state="disabled")
        status.configure(text="Working…")

        def work():
            try:
                result = operation()
                events.put(("done", result, uses_model))
            except Exception as exc:
                events.put(("error", str(exc), uses_model))

        threading.Thread(target=work, daemon=True).start()

    def suggest():
        try:
            record = chosen_record()
            if not app.engine.loaded:
                raise ValueError("Choose and load a coding model first.")
        except ValueError as exc:
            status.configure(text=str(exc))
            return
        background(lambda: ("suggestions", studio.suggest(record["id"], app.engine.generate_json,
                       progress=lambda text: events.put(("progress", text)))), uses_model=True)

    def select_suggestion(_event=None):
        selection = suggestions.curselection()
        if selection:
            item = proposals[selection[0]]
            start.set(str(item["start"]))
            end.set(str(item["end"]))
            title.set(item["title"])
            status.configure(text=item["reason"])

    def render():
        nonlocal current_job
        if active:
            status.configure(text="Wait for the current clip operation to finish.")
            return
        try:
            record = chosen_record()
            upload_after = auto_upload.get()
            if upload_after and not publisher.connected():
                raise ValueError("Connect YouTube first, or turn off Upload after export.")
            current_job = studio.plan(record["id"], timestamp(start.get()), timestamp(end.get()),
                                      title.get(), layout.get(), burn.get())
        except Exception as exc:
            status.configure(text=str(exc))
            return
        job = current_job
        visibility, children = privacy.get(), kids.get()

        def operation():
            output = studio.render(job, lambda text: events.put(("progress", text)))
            if upload_after:
                queue_job(job, visibility, children)
            return ("message", f"Exported: {output}" + (" · queued for YouTube" if upload_after else ""))

        background(operation)

    def queue_job(job, visibility, children):
        if job["status"] != "rendered":
            raise ValueError("Select a rendered clip. Uploaded or interrupted uploads cannot be queued again.")
        studio.transition(job["id"], "rendered", "upload_queued",
                          youtube_visibility=visibility, made_for_kids=children)

    def upload():
        try:
            if not publisher.connected():
                raise ValueError("Connect YouTube first.")
            selection = jobs.curselection()
            if not selection:
                raise ValueError("Select a rendered clip from the export list.")
            queue_job(exported[selection[0]], privacy.get(), kids.get())
            status.configure(text="Queued. Doxa will upload this clip automatically.")
            refresh()
        except Exception as exc:
            status.configure(text=str(exc))

    def connect():
        path = filedialog.askopenfilename(title="Choose Google OAuth Desktop app client JSON",
                                          filetypes=[("OAuth client", "*.json")], parent=window)
        if path:
            background(lambda: (publisher.connect(Path(path)), ("message", "YouTube upload permission connected."))[1])

    def open_clip():
        selection = jobs.curselection()
        if selection:
            job = exported[selection[0]]
            if Path(job["output"]).is_file():
                os.startfile(job["output"])

    def setup_help():
        messagebox.showinfo("Connect YouTube",
            "1. Create or select a project in Google Cloud.\n"
            "2. Enable YouTube Data API v3.\n"
            "3. Configure Google Auth Platform and add your account as a test user if in testing.\n"
            "4. Create an OAuth client: Desktop app. Download its JSON.\n"
            "5. Click Connect YouTube and select that JSON. Sign into your channel.\n\n"
            "Doxa stores the token in Windows Credential Manager. Google Drive authorization "
            "does not grant permission to upload to YouTube.", parent=window)
        webbrowser.open("https://console.cloud.google.com/apis/library/youtube.googleapis.com")

    def cancel_queue():
        selection = jobs.curselection()
        if selection and exported[selection[0]]["status"] == "upload_queued":
            job = exported[selection[0]]
            try:
                studio.transition(job["id"], "upload_queued", "rendered")
                refresh()
            except ValueError as exc:
                status.configure(text=str(exc))

    def retry_upload():
        selection = jobs.curselection()
        if selection:
            job = exported[selection[0]]
            if job["status"] != "upload_failed":
                status.configure(text="Select an upload_failed clip. Check YouTube Studio for a duplicate first.")
                return
            if not messagebox.askyesno("Retry upload", "Confirm you checked YouTube Studio and this clip "
                                       "was not already uploaded. Retry it?", parent=window):
                return
            try:
                studio.transition(job["id"], "upload_failed", "upload_queued",
                                  youtube_visibility=privacy.get(), made_for_kids=kids.get())
                refresh()
            except ValueError as exc:
                status.configure(text=str(exc))

    def poll():
        nonlocal active, proposals
        try:
            while True:
                event = events.get_nowait()
                if event[0] == "progress":
                    status.configure(text=event[1])
                    continue
                active = False
                app._creator_operations = max(0, app._creator_operations - 1)
                if event[2]:
                    app.busy = False
                    app.send_button.configure(state="normal")
                if event[0] == "error":
                    status.configure(text=event[1])
                elif event[1][0] == "suggestions":
                    proposals = event[1][1]
                    suggestions.delete(0, "end")
                    for item in proposals:
                        suggestions.insert("end", f"{item['start']:.1f}–{item['end']:.1f}s · {item['title']}")
                    status.configure(text=f"Found {len(proposals)} candidate moments. Select one, preview, then export.")
                else:
                    status.configure(text=event[1][1])
                refresh()
        except queue.Empty:
            pass
        # Upload completion is handled by the application's persistent queue worker.
        if window.winfo_exists():
            refresh()
            window.after(500, poll)

    def close():
        if active:
            status.configure(text="Processing continues. Close this window after it finishes.")
            return
        window.destroy()

    ttk.Button(frame, text="Refresh", command=refresh).grid(row=2, column=2)
    suggestions.bind("<<ListboxSelect>>", select_suggestion)
    for label, command in (("Suggest highlights", suggest), ("Export clip", render),
                           ("Preview export", open_clip), ("Queue YouTube upload", upload),
                           ("Cancel queued", cancel_queue)):
        ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 6))
    ttk.Button(connections, text="YouTube setup", command=setup_help).pack(side="left", padx=(0, 6))
    ttk.Button(connections, text="Connect YouTube", command=connect).pack(side="left", padx=(0, 6))
    ttk.Button(connections, text="Disconnect YouTube", command=publisher.disconnect).pack(side="left", padx=(0, 6))
    ttk.Button(connections, text="Open YouTube Studio", command=lambda: webbrowser.open("https://studio.youtube.com")).pack(side="left")
    ttk.Button(connections, text="Retry failed upload", command=retry_upload).pack(side="left", padx=6)
    window.protocol("WM_DELETE_WINDOW", close)
    refresh()
    window.after(500, poll)


def pump_uploads(app) -> None:
    """Consume explicitly queued uploads. Do not replay uncertain in-flight uploads."""
    if not app._upload_running and not getattr(app, "_computer_controls", None):
        pending = next((job for job in app.clip_studio.jobs() if job["status"] == "upload_queued"), None)
        if pending:
            try:
                pending = app.clip_studio.transition(pending["id"], "upload_queued", "uploading")
            except ValueError:
                app.after(3000, lambda: pump_uploads(app))
                return
            app._upload_running = True

            def work():
                try:
                    result = YouTubePublisher().upload(
                        Path(pending["output"]), pending["title"], privacy=pending["youtube_visibility"],
                        made_for_kids=pending.get("made_for_kids", False),
                        progress=lambda text: app.events.put(("status", text)),
                    )
                    pending.update(status="uploaded", youtube=result)
                    app.events.put(("status", "Uploaded to YouTube: " + result["url"]))
                except Exception as exc:
                    pending.update(status="upload_failed", error=str(exc))
                    app.events.put(("status", "YouTube upload needs attention: " + str(exc)))
                finally:
                    try:
                        app.clip_studio.save(pending)
                    finally:
                        app._upload_running = False

            threading.Thread(target=work, daemon=True).start()
    app.after(3000, lambda: pump_uploads(app))


def open_remote_panel(app) -> None:
    window = tk.Toplevel(app)
    window.title("Doxa — Remote laptop access")
    window.geometry("760x520")
    window.transient(app)
    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Control your laptop remotely", style="Title.TLabel").pack(anchor="w")
    text = ScrolledText(frame, wrap="word", font=("Segoe UI", 11), height=15)
    text.pack(fill="both", expand=True, pady=12)
    text.insert("end", "Chrome Remote Desktop gives you the whole laptop screen, including Doxa, "
        "Roblox Studio, OBS, and your other applications.\n\n"
        "On this laptop:\n"
        "1. Click Set up remote access and sign into your Google account.\n"
        "2. In Set up remote access, install the Chrome Remote Desktop host when Google prompts you.\n"
        "3. Name the laptop and create your private PIN.\n"
        "4. Keep the laptop powered on, connected to the internet, and awake.\n\n"
        "On your phone or another computer:\n"
        "5. Open remotedesktop.google.com/access and sign into the same Google account.\n"
        "6. Select your laptop and enter its PIN.\n\n"
        "Your screen and controls are available remotely after that setup. This panel does not claim "
        "the connection is active: complete Google's account/host/PIN setup and test from your other device. "
        "Keep your PIN in the remote access service rather than in Doxa's chat or memory.")
    text.configure(state="disabled")
    controls = ttk.Frame(frame)
    controls.pack(fill="x")
    ttk.Button(controls, text="Set up remote access", command=lambda:
               webbrowser.open("https://remotedesktop.google.com/access")).pack(side="left", padx=(0, 8))
    ttk.Button(controls, text="Google setup guide", command=lambda:
               webbrowser.open("https://support.google.com/chrome/answer/1649523")).pack(side="left", padx=(0, 8))
    ttk.Button(controls, text="Windows power settings", command=lambda:
               os.startfile("ms-settings:powersleep")).pack(side="left")
