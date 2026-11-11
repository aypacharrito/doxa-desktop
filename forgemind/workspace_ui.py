"""Compact native editors for personal context, routines and measured activity."""
from __future__ import annotations

import tkinter as tk
import queue
import threading
from pathlib import PurePath
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import jarvis_ui as ui
from .workspace import DEFAULT_ROUTINES, clean_routines
from .computer_ui import open_computer_panel
from .growth_ui import open_growth_panel


def window(app, title, geometry="640x630"):
    win = tk.Toplevel(app)
    win.title("Doxa · " + title)
    win.geometry(geometry)
    win.minsize(480, 400)
    win.configure(bg=ui.BG)
    win.transient(app)
    body = tk.Frame(win, bg=ui.BG, padx=26, pady=22)
    body.pack(fill="both", expand=True)
    tk.Label(body, text=title, bg=ui.BG, fg=ui.TEXT, font=("Segoe UI Semibold", 22)).pack(anchor="w", pady=(0, 12))
    return win, body


def note(parent, text):
    tk.Label(parent, text=text, bg=ui.BG, fg=ui.MUTED, font=("Segoe UI", 10),
             anchor="w", justify="left", wraplength=550).pack(fill="x", pady=(0, 12))


def editor(parent, height=12):
    area = ScrolledText(parent, height=height, bg=ui.SURFACE, fg=ui.TEXT, insertbackground=ui.BLUE,
                        relief="flat", borderwidth=0, highlightthickness=0,
                        padx=12, pady=12, wrap="word", font=("Segoe UI", 11))
    area.pack(fill="both", expand=True, pady=(0, 12))
    return area


def _memory_text(parent, *, height):
    """Plain local text with a slim scrollbar that matches the workspace."""
    frame = tk.Frame(parent, bg=ui.BG)
    frame.pack(fill="both", expand=True)
    view = tk.Text(frame, height=height, bg=ui.BG, fg=ui.TEXT, relief="flat",
                   borderwidth=0, highlightthickness=0, wrap="word", padx=2, pady=4,
                   font=("Segoe UI", 10), selectbackground=ui.SELECT, insertwidth=0)
    scroll = ui.ThinScroll(frame, command=view.yview)
    scroll.pack(side="right", fill="y")
    view.configure(yscrollcommand=scroll.set, state="disabled")
    view.pack(side="left", fill="both", expand=True)
    return view


class MemoryBrowser:
    """A local, read-only search view; only an explicitly confirmed pin can be deleted."""

    def __init__(self, app):
        self.app = app
        self.win, body = window(app, "Memory", "880x740")
        self.win.minsize(650, 590)
        self.closed = False
        self.generation = 0
        self.pending = None
        self.poll_timer = None
        self.jobs, self.results = queue.Queue(), queue.Queue()
        self.rows = []
        self.selected = -1
        self.scope = "all"
        note(body, "Find your pinned notes and passages from connected files. Search stays on this device.")
        self.query = tk.StringVar(self.win)
        self.entry = tk.Entry(body, textvariable=self.query, bg=ui.SURFACE, fg=ui.TEXT,
                              insertbackground=ui.BLUE, relief="flat", highlightthickness=0,
                              font=("Segoe UI", 11))
        self.entry.pack(fill="x", ipady=9, pady=(0, 6))
        self.entry.bind("<Escape>", lambda _event: self.query.set(""))
        self.entry.bind("<Down>", lambda _event: self._move(1))
        self.entry.bind("<Return>", lambda _event: self.refresh())
        filters = tk.Frame(body, bg=ui.BG)
        filters.pack(fill="x")
        self.filters = {}
        for scope, label in (("all", "Everything"), ("pinned", "Pinned"), ("files", "Files")):
            control = ui.button(filters, label, lambda value=scope: self._filter(value), small=True)
            control.pack(side="left")
            self.filters[scope] = control
        ui.button(filters, "Refresh", self.refresh, small=True).pack(side="right")
        self.status = tk.StringVar(self.win, "Search words in your notes or file contents.")
        tk.Label(body, textvariable=self.status, bg=ui.BG, fg=ui.MUTED,
                 anchor="w", font=("Segoe UI", 9)).pack(fill="x", pady=(5, 8))
        panes = tk.PanedWindow(body, orient="vertical", bg=ui.BG, sashwidth=8,
                               borderwidth=0, relief="flat", showhandle=False)
        panes.pack(fill="both", expand=True)
        listing = tk.Frame(panes, bg=ui.BG)
        preview = tk.Frame(panes, bg=ui.BG)
        panes.add(listing, minsize=130, height=250, stretch="always")
        panes.add(preview, minsize=120, stretch="always")
        self.listing = _memory_text(listing, height=10)
        self.listing.tag_configure("title", font=("Segoe UI Semibold", 10), foreground=ui.TEXT, spacing1=10)
        self.listing.tag_configure("snippet", foreground=ui.MUTED, spacing3=10)
        self.listing.tag_configure("selected", background=ui.SURFACE_2)
        self.listing.bind("<Up>", lambda _event: self._move(-1))
        self.listing.bind("<Down>", lambda _event: self._move(1))
        self.listing.bind("<Button-1>", self._click_result)
        self.source = tk.Label(preview, text="Select a result to read it here.", bg=ui.BG,
                               fg=ui.BLUE, anchor="w", justify="left", wraplength=780,
                               font=("Segoe UI Semibold", 10))
        self.source.pack(fill="x", pady=(8, 6))
        preview.bind("<Configure>", lambda event: self.source.configure(wraplength=max(250, event.width - 16)))
        self.detail = _memory_text(preview, height=6)
        actions = tk.Frame(preview, bg=ui.BG)
        actions.pack(fill="x")
        self.copy = ui.button(actions, "Copy text", self.copy_selected, small=True)
        self.copy.pack(side="left")
        self.remove = ui.button(actions, "Remove pin", self.remove_selected, small=True)
        self.remove.pack(side="right")
        self._clear_selection()
        footer = tk.Frame(body, bg=ui.BG)
        footer.pack(fill="x", pady=(12, 0))
        for label, action in (("+ Pin a memory", app.add_memory), ("Add files", app.choose_files),
                              ("Connect folder", app.choose_knowledge), ("Back up", app.backup_now)):
            ui.button(footer, label, lambda task=action: self._action(task), small=True).pack(side="left")
        self.query.trace_add("write", self._changed)
        self.win.bind("<Destroy>", self._destroyed, add="+")
        self.worker = threading.Thread(target=self._worker, name="Doxa memory search", daemon=True)
        self.worker.start()
        self.poll_timer = self.win.after(80, self._poll)
        self._filter("all")
        self.entry.focus_set()

    def _action(self, task):
        task()
        if not self.closed:
            self.refresh()

    def _filter(self, scope):
        self.scope = scope
        for value, control in self.filters.items():
            control.configure(fg=ui.BLUE if value == scope else ui.MUTED,
                              bg=ui.SURFACE_2 if value == scope else ui.BG)
        self.refresh()

    def _changed(self, *_args):
        self.generation += 1
        if self.pending is not None:
            self.win.after_cancel(self.pending)
        self.pending = self.win.after(220, self._submit)

    def refresh(self):
        self._changed()
        self.win.after_cancel(self.pending)
        self.pending = None
        self._submit()

    def _submit(self):
        self.pending = None
        if self.closed:
            return
        self.status.set("Searching on this device…")
        self.jobs.put((self.generation, self.query.get().strip(), self.scope))

    def _worker(self):
        # This worker never calls Tk. The queue drops obsolete pending searches.
        while True:
            job = self.jobs.get()
            while job is not None:
                try:
                    job = self.jobs.get_nowait()
                except queue.Empty:
                    break
            if job is None:
                return
            generation, query, scope = job
            try:
                rows = self.app.db.search_memory(query, scope=scope, limit=61)
                self.results.put((generation, rows, None))
            except Exception:
                self.results.put((generation, [], "Couldn’t read local memory. Try Refresh."))

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                generation, rows, error = self.results.get_nowait()
            except queue.Empty:
                break
            if generation == self.generation:
                self._render(rows, error)
        self.poll_timer = self.win.after(80, self._poll)

    def _render(self, rows, error):
        self.rows = rows[:60]
        self._clear_selection()
        self.listing.configure(state="normal")
        self.listing.delete("1.0", "end")
        for tag in self.listing.tag_names():
            if tag.startswith("result_"):
                self.listing.tag_delete(tag)
        if error:
            self.status.set(error)
        elif not rows:
            if self.query.get().strip():
                text = "No matches. Try fewer words or choose Everything."
            elif self.scope == "pinned":
                text = "No pinned memories yet. Pin something you want to keep."
            elif self.scope == "files":
                text = "No indexed files yet. Add files or connect a folder, then Refresh."
            else:
                text = "Nothing saved yet. Pin a memory or connect your files to begin."
            self.status.set(text)
        elif len(rows) > 60:
            self.status.set("First 60 matches · narrow your search to find more.")
        else:
            self.status.set(f"{len(rows)} {'match' if len(rows) == 1 else 'matches'} · saved locally" if self.query.get().strip()
                            else f"{len(rows)} recent notes and file excerpts · type to search")
        for index, row in enumerate(self.rows):
            title = "Pinned memory" if row["kind"] == "pinned" else PurePath(row["source"]).name
            suffix = "  ·  Pin" if row["kind"] == "pinned" else f"  ·  File · Passage {row['ordinal'] + 1}"
            tag = f"result_{index}"
            self.listing.insert("end", title + suffix + "\n", ("title", tag))
            self.listing.insert("end", row["snippet"] + "\n", ("snippet", tag))
        self.listing.configure(state="disabled")
        if self.rows:
            self._select(0)

    def _clear_selection(self):
        self.selected = -1
        self.source.configure(text="Select a result to read it here.")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.configure(state="disabled")
        self.copy.configure(state="disabled")
        self.remove.configure(state="disabled")

    def _click_result(self, event):
        tags = self.listing.tag_names(self.listing.index(f"@{event.x},{event.y}"))
        for tag in tags:
            if tag.startswith("result_"):
                self._select(int(tag[7:]))
                self.listing.focus_set()
                return "break"

    def _move(self, delta):
        if self.rows:
            self._select(max(0, min(len(self.rows) - 1, self.selected + delta)))
            self.listing.focus_set()
        return "break"

    def _select(self, index):
        if not 0 <= index < len(self.rows):
            return
        self.selected = index
        row = self.rows[index]
        self.listing.tag_remove("selected", "1.0", "end")
        positions = self.listing.tag_ranges(f"result_{index}")
        if positions:
            self.listing.tag_add("selected", positions[0], positions[-1])
            self.listing.see(positions[0])
        description = "Pinned memory" if row["kind"] == "pinned" else f"Indexed passage {row['ordinal'] + 1} · {row['source']}"
        self.source.configure(text=description)
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", row["content"])
        self.detail.configure(state="disabled")
        self.copy.configure(state="normal")
        self.remove.configure(state="normal" if row["kind"] == "pinned" else "disabled")

    def copy_selected(self):
        if 0 <= self.selected < len(self.rows):
            self.win.clipboard_clear()
            self.win.clipboard_append(self.rows[self.selected]["content"])
            self.status.set("Copied selected text.")

    def remove_selected(self):
        if not 0 <= self.selected < len(self.rows):
            return
        row = self.rows[self.selected]
        if row["kind"] == "pinned" and messagebox.askyesno("Remove memory", "Remove this pinned memory?", parent=self.win):
            self.app.db.delete_memory(row["id"])
            self.app.refresh_all()
            self.refresh()

    def _destroyed(self, event):
        if event.widget != self.win or self.closed:
            return
        self.closed = True
        for timer in (self.pending, self.poll_timer):
            if timer is not None:
                try:
                    self.win.after_cancel(timer)
                except tk.TclError:
                    pass
        self.jobs.put(None)


def open_memory(app):
    existing = getattr(app, "_memory_browser", None)
    if existing is not None and not existing.closed:
        existing.win.deiconify()
        existing.win.lift()
        existing.refresh()
        existing.entry.focus_set()
        return existing.win
    app._memory_browser = MemoryBrowser(app)
    return app._memory_browser.win


def open_brief(app):
    win, body = window(app, "Your brief")
    note(body, "Your priorities, projects and writing style. Saved locally and used for your replies. You can edit this whenever things change.")
    tk.Label(body, text="What should I call you?", bg=ui.BG, fg=ui.TEXT, font=("Segoe UI Semibold", 10)).pack(anchor="w")
    name = tk.Entry(body, bg=ui.SURFACE, fg=ui.TEXT, insertbackground=ui.BLUE, relief="flat", font=("Segoe UI", 11))
    name.pack(fill="x", ipady=9, pady=(6, 18))
    name.insert(0, app.settings_data.display_name)
    note(body, "What matters right now, how you work, and how you want Doxa to write:")
    brief = editor(body)
    brief.insert("1.0", app.settings_data.personal_brief)
    def save():
        value, preferred = brief.get("1.0", "end").strip(), name.get().strip()
        if len(value) > 4000 or len(preferred) > 60:
            messagebox.showinfo("Keep your brief focused", "Use up to 4,000 characters for the brief and 60 for your name.", parent=win)
            return
        app.settings_data.personal_brief, app.settings_data.display_name = value, preferred
        app.settings_data.save()
        app.hero_title.configure(text=f"Right here, {preferred}." if preferred else "Ready when you are.")
        app._set_status("Your brief is saved locally. It will be used on your next request.")
        win.destroy()
    ui.button(body, "Save brief", save, active=True).pack(anchor="e")


def open_routines(app):
    win, body = window(app, "Routines", "700x700")
    note(body, "Reusable instructions for work you do often. Open one in the composer, add your details, then send. Nothing runs in the background.")
    routines = clean_routines(app.settings_data.routines)
    names = tk.Listbox(body, bg=ui.BG, fg=ui.TEXT, selectbackground=ui.SELECT, selectforeground=ui.TEXT,
                       relief="flat", highlightthickness=0, font=("Segoe UI Semibold", 11), height=5, exportselection=False)
    names.pack(fill="x", pady=(0, 14))
    title = tk.Entry(body, bg=ui.SURFACE, fg=ui.TEXT, insertbackground=ui.BLUE, relief="flat", font=("Segoe UI", 11))
    title.pack(fill="x", ipady=8, pady=(0, 10))
    prompt = editor(body)
    chosen = [None]
    def populate():
        names.delete(0, "end")
        for item in routines:
            names.insert("end", item["name"])
    def select(_event=None):
        selection = names.curselection()
        if not selection:
            return
        chosen[0] = selection[0]
        item = routines[chosen[0]]
        title.delete(0, "end"); title.insert(0, item["name"])
        prompt.delete("1.0", "end"); prompt.insert("1.0", item["prompt"])
    def fresh():
        chosen[0] = None
        names.selection_clear(0, "end")
        title.delete(0, "end"); prompt.delete("1.0", "end")
        title.focus_set()
    def read():
        item = {"name": title.get().strip(), "prompt": prompt.get("1.0", "end-1c")}
        if not item["name"] or not item["prompt"].strip() or len(item["name"]) > 60 or len(item["prompt"]) > 4000:
            messagebox.showinfo("Routine details", "Add a name (up to 60 characters) and instructions (up to 4,000).", parent=win)
            return None
        return item
    def save():
        item = read()
        if not item:
            return
        if chosen[0] is None:
            if len(routines) >= 24:
                messagebox.showinfo("Routines full", "You can keep up to 24 routines. Edit an existing one first.", parent=win)
                return
            routines.append(item); chosen[0] = len(routines) - 1
        else:
            routines[chosen[0]] = item
        app.settings_data.routines = list(routines)
        app.settings_data.save()
        populate(); names.selection_set(chosen[0])
        app._set_status("Routine saved locally")
    def use():
        item = read()
        if not item:
            return
        if app.input.get("1.0", "end").strip():
            messagebox.showinfo("Your draft is still open", "Send or clear your current draft before opening a routine. Your draft has been kept.", parent=win)
            return
        app.input.insert("1.0", item["prompt"])
        app.input.event_generate("<KeyRelease>")
        app.input.focus_set()
        app._set_status("Routine opened. Add your details, then Send.")
        win.destroy()
    controls = tk.Frame(body, bg=ui.BG); controls.pack(fill="x")
    ui.button(controls, "New", fresh, small=True).pack(side="left")
    ui.button(controls, "Save routine", save, small=True).pack(side="left", padx=8)
    ui.button(controls, "Open in composer ↗", use, active=True, small=True).pack(side="right")
    names.bind("<<ListboxSelect>>", select)
    populate()
    if routines:
        names.selection_set(0); select()


def open_activity(app):
    win, body = window(app, "Activity", "760x720")
    note(body, "Actual requests and measured timings on this device. Ready means a response was generated; it does not verify the answer or mean an external action ran.")
    controls=tk.Frame(body,bg=ui.BG)
    controls.pack(side='bottom',fill='x',pady=(8,0))
    view = _memory_text(body, height=10)
    view.tag_configure("title", foreground=ui.TEXT, font=("Segoe UI Semibold", 11), spacing1=12)
    view.tag_configure("detail", foreground=ui.MUTED, font=("Segoe UI", 10), spacing3=10)
    def refresh():
        view.configure(state="normal"); view.delete("1.0", "end")
        usage=getattr(app,'model_usage',None)
        if usage is not None:
            view.insert('end','Local model performance\n','title')
            view.insert('end','API inference spend: $0. Generated does not mean fact-checked.\n','detail')
            for call in usage.recent(8):
                timing=f"{(call['elapsed_ms'] or 0)/1000:.1f}s"
                if call['first_text_ms'] is not None:
                    timing+=f" · first text {call['first_text_ms']/1000:.1f}s"
                view.insert('end',f"{call['model']} · {call['state']} · {timing}\n",'detail')
        runs = app.run_journal.recent()
        if not runs and (usage is None or not usage.recent(1)):
            view.insert("end", "Your next request will appear here.\n", "detail")
        for run in runs:
            view.insert("end", run["title"] + "\n", "title")
            timing = f"{run['elapsed_ms'] / 1000:.1f}s total"
            if run["first_response_ms"] is not None:
                timing += f" · first text {run['first_response_ms'] / 1000:.1f}s"
            view.insert("end", f"{run['stage']} · {timing}\n{run['started_at']}\n" + (run["detail"] + "\n" if run["detail"] else ""), "detail")
        view.configure(state="disabled")
    for index,(label,action) in enumerate([
        ('Refresh activity',refresh),('Computer tasks',lambda:open_computer_panel(app)),
        ('Growth Lab',lambda:open_growth_panel(app)),('Stop background work',app.stop_current_work)
    ]):
        ui.button(controls,label,action,small=True).grid(row=index//2,column=index%2,sticky='w',padx=(0,12))
    refresh()
