"""Traffic ticket panel (Tools → Traffic ticket, or say "contest this ticket C:\\...\\ticket.jpg").

Photo → (owner covers his license number) → one cloud read → editable card → printable packet in Documents\\Doxa Legal.
Nothing is filed, paid, emailed or mailed: the owner reviews, signs and mails it himself.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from . import jarvis_ui as ui
from . import tickets

PREVIEW = (600, 420)
FIELDS = (("citation_number", "Citation number"), ("court_name", "Court name"), ("court_address", "Court mailing address"),
          ("county", "County"), ("agency", "Issuing agency"), ("violation_date", "Violation date (YYYY-MM-DD)"),
          ("violation_time", "Violation time"), ("location", "Location"), ("due_date", "Due date (YYYY-MM-DD)"),
          ("bail_amount", "Bail amount ($)"), ("defendant_name", "Your full name"),
          ("mailing_address", "Your mailing address"))


def _text_box(parent, height):
    return tk.Text(parent, height=height, wrap="word", bg=ui.SURFACE_2, fg=ui.TEXT, insertbackground=ui.GOLD,
                   relief="flat", borderwidth=6, highlightthickness=1, highlightbackground=ui.LINE,
                   highlightcolor=ui.GOLD_DIM, selectbackground=ui.SELECT, font=(ui.BODY, 10))


def _label(parent, text, top=8):
    tk.Label(parent, text=text, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY_BOLD, 9), anchor="w").pack(fill="x", pady=(top, 2))


def open_helper(app, path: str = "", reason: str = ""):
    from .calendar_ui import _entry
    window, content = ui._panel(
        app, "Traffic ticket",
        "Give Doxa a photo of a California traffic ticket. It reads the details and drafts the paperwork to contest it "
        "by mail (Trial by Written Declaration, form TR-205): a checklist, a TR-205 worksheet and your declaration. "
        "You review, sign and mail it yourself.", size="700x900")
    tk.Label(content, text="Not legal advice. " + tickets.DISCLAIMER, bg=ui.BG, fg=ui.GOLD, font=(ui.BODY, 9),
             anchor="w", justify="left", wraplength=620).pack(fill="x", pady=(0, 8))
    state = {"path": path or "", "boxes": [], "photo": None, "scale": None, "drag": None, "busy": False}
    status = tk.StringVar()
    clouds = app.brain.clouds(app.settings_data) if getattr(app, "brain", None) else []
    engine_name = clouds[0].display_name if clouds else ""

    # --- photo + boxes ------------------------------------------------------------------------------------------
    row = tk.Frame(content, bg=ui.BG)
    row.pack(fill="x", pady=(4, 4))
    path_var = tk.StringVar(value=Path(path).name if path else "No photo chosen")
    canvas = tk.Canvas(content, width=PREVIEW[0], height=80, bg=ui.SURFACE, highlightthickness=1,
                       highlightbackground=ui.LINE, cursor="crosshair")

    def draw():
        canvas.delete("all")
        if state["photo"] is None:
            canvas.configure(height=80)
            canvas.create_text(PREVIEW[0] // 2, 40, text="Choose the ticket photo", fill=ui.FAINT, font=(ui.BODY, 10))
            return
        width, height = state["scale"]
        canvas.configure(height=height)
        canvas.create_image(0, 0, image=state["photo"], anchor="nw")
        for left, top, right, bottom in state["boxes"]:
            canvas.create_rectangle(left * width, top * height, right * width, bottom * height, fill="black",
                                    outline=ui.GOLD)

    def load(chosen):
        state.update(path=chosen, boxes=[], photo=None, scale=None)
        path_var.set(Path(chosen).name if chosen else "No photo chosen")
        if chosen:
            try:
                from PIL import Image, ImageOps, ImageTk
                with Image.open(chosen) as original:
                    image = ImageOps.exif_transpose(original).convert("RGB")
                image.thumbnail(PREVIEW)
                state["photo"] = ImageTk.PhotoImage(image, master=window)
                state["scale"] = image.size
                status.set("Drag a box over your driver's license number (and anything else you don't want sent). "
                           f"Then press Read ticket.")
            except Exception:
                status.set("Doxa can't preview that file. Use a JPG or PNG photo (iPhone HEIC: save it as JPG).")
        draw()

    def choose():
        chosen = filedialog.askopenfilename(parent=window, title="Choose the ticket photo", filetypes=[
            ("Photos", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"), ("All files", "*.*")])
        if chosen:
            load(chosen)

    def press(event):
        if state["scale"]:
            state["drag"] = (event.x, event.y)

    def motion(event):
        if state["drag"] and state["scale"]:
            draw()
            x, y = state["drag"]
            canvas.create_rectangle(x, y, event.x, event.y, fill="black", outline=ui.GOLD)

    def release(event):
        if not (state["drag"] and state["scale"]):
            return
        (x, y), (width, height) = state["drag"], state["scale"]
        state["drag"] = None
        if abs(event.x - x) > 4 and abs(event.y - y) > 4:
            clamp = lambda v, size: min(1.0, max(0.0, v / size))  # noqa: E731
            state["boxes"].append((clamp(min(x, event.x), width), clamp(min(y, event.y), height),
                                   clamp(max(x, event.x), width), clamp(max(y, event.y), height)))
            status.set(f"{len(state['boxes'])} area(s) will be blacked out before the photo is sent.")
        draw()

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", motion)
    canvas.bind("<ButtonRelease-1>", release)
    ui.button(row, "Choose photo", choose, small=True).pack(side="left")
    ui.button(row, "Undo box", lambda: (state["boxes"] and state["boxes"].pop(), draw()), small=True).pack(
        side="left", padx=8)
    tk.Label(row, textvariable=path_var, bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9)).pack(side="left")
    canvas.pack(anchor="w", pady=(4, 2))
    tk.Label(content, text="Location data (GPS) is removed from the photo automatically. Only the photo and your notes "
             "go to " + (engine_name or "the cloud brain") + ", in one request.", bg=ui.BG, fg=ui.FAINT,
             font=(ui.BODY, 9), anchor="w", justify="left", wraplength=620).pack(fill="x")

    _label(content, "YOUR SIDE OF WHAT HAPPENED (optional, used for the declaration)", top=12)
    notes = _text_box(content, 4)
    notes.pack(fill="x")
    if reason:
        notes.insert("1.0", reason)

    actions = tk.Frame(content, bg=ui.BG)
    actions.pack(fill="x", pady=(10, 2))
    tk.Label(content, textvariable=status, bg=ui.BG, fg=ui.GOLD, font=(ui.BODY, 10), anchor="w", justify="left",
             wraplength=620).pack(fill="x", pady=4)

    # --- the card -----------------------------------------------------------------------------------------------
    _label(content, "TICKET DETAILS (check each one against the ticket)", top=12)
    grid = tk.Frame(content, bg=ui.BG)
    grid.pack(fill="x")
    grid.columnconfigure(1, weight=1)
    variables = {}
    for number, (key, label) in enumerate(FIELDS):
        tk.Label(grid, text=label, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w").grid(
            row=number, column=0, sticky="w", padx=(0, 10), pady=2)
        variables[key] = tk.StringVar()
        _entry(grid, variables[key]).grid(row=number, column=1, sticky="ew", pady=2)
    kind = tk.StringVar(value="traffic")
    tk.Label(grid, text="Type", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w").grid(
        row=len(FIELDS), column=0, sticky="w", pady=2)
    ttk.Combobox(grid, textvariable=kind, values=("traffic", "parking", "misdemeanor"), state="readonly",
                 width=14).grid(row=len(FIELDS), column=1, sticky="w", pady=2)
    _label(content, "VIOLATIONS (one per line: VC 22350 — description)")
    violations = _text_box(content, 3)
    violations.pack(fill="x")
    _label(content, "STATEMENT OF FACTS (your declaration — edit freely; fill or delete every [placeholder])")
    statement = _text_box(content, 12)
    statement.pack(fill="x")
    points_var = tk.StringVar()
    tk.Label(content, textvariable=points_var, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w", justify="left",
             wraplength=620).pack(fill="x", pady=(6, 0))
    state["points"] = []

    def fill(ticket: tickets.Ticket):
        for key, _label_text in FIELDS:
            current = getattr(ticket, key)
            if key == "bail_amount":
                current = f"{current:.2f}" if current else ""
            if key == "mailing_address" and not current:
                continue  # never read from the photo; keep what the owner typed
            variables[key].set(current or "")
        kind.set(ticket.kind)
        violations.delete("1.0", "end")
        violations.insert("1.0", tickets.violations_text(ticket.violations))
        statement.delete("1.0", "end")
        statement.insert("1.0", ticket.statement)
        show_points(ticket.defense_points)

    def show_points(points):
        state["points"] = list(points)
        points_var.set(("Worth checking (use only what's true):\n" + "\n".join("• " + p for p in points))
                       if points else "")

    def current() -> tickets.Ticket:
        values = {key: variables[key].get().strip() for key, _label_text in FIELDS}
        values["bail_amount"] = tickets.parse_money(values["bail_amount"])
        for key in ("violation_date", "due_date"):
            values[key] = tickets.parse_date(values[key]) if values[key] else ""
        return tickets.Ticket(**values, kind=kind.get(), violations=tickets.parse_violations(violations.get("1.0", "end")),
                              statement=statement.get("1.0", "end").strip(), defense_points=state["points"])

    def in_background(work, done, start_note):
        if state["busy"]:
            return
        state["busy"] = True
        status.set(start_note)

        def run():
            try:
                result, problem = work(), ""
            except tickets.TicketError as exc:
                result, problem = None, str(exc)
            except Exception as exc:  # budget reached, offline, bad key: say so, keep Doxa running
                result, problem = None, f"That didn't work: {exc}"

            def finish():
                state["busy"] = False
                if window.winfo_exists():
                    status.set(problem) if problem else done(result)
            app.events.put(("ui", finish))
        threading.Thread(target=run, daemon=True, name="doxa-ticket").start()

    def read():
        if not state["path"]:
            status.set("Choose the ticket photo first.")
            return
        if not clouds:
            status.set("Reading a photo needs Claude or OpenAI (Tools → AI brains). You can type the details in below "
                       "and press Make paperwork.")
            return
        path_now, boxes, reason_now = state["path"], list(state["boxes"]), notes.get("1.0", "end").strip()

        def done(ticket):
            fill(ticket)
            extra = f" Couldn't read: {ticket.unclear}." if ticket.unclear else ""
            status.set("Read. Check every field against the ticket, add your name and address, edit the statement, "
                       "then press Make paperwork." + extra)
        in_background(lambda: tickets.read_ticket(app.brain, app.settings_data, path_now, boxes, reason_now),
                      done, f"{engine_name} is reading the ticket… (about 20-40 seconds)")

    def redraft():
        if not clouds:
            status.set("Redrafting needs Claude or OpenAI (Tools → AI brains). You can edit the statement yourself.")
            return
        ticket, reason_now = current(), notes.get("1.0", "end").strip()

        def done(result):
            text, points = result
            statement.delete("1.0", "end")
            statement.insert("1.0", text)
            show_points(points)
            status.set("New statement drafted. Read it carefully: it must be true in every detail.")
        in_background(lambda: tickets.redraft_statement(app.brain, app.settings_data, ticket, reason_now), done,
                      f"{engine_name} is redrafting the statement (only the violation, date, place and your notes "
                      "are sent)…")

    def make():
        ticket = current()
        if not (ticket.citation_number or ticket.violations):
            status.set("Add at least the citation number or the violation first.")
            return
        try:
            packet = tickets.build_packet(ticket)
        except OSError as exc:
            status.set(f"Couldn't save the packet: {exc}")
            return
        state["packet"] = packet
        status.set(f"Saved {packet.name} in Documents\\Doxa Legal. Opening it — print, check, sign, mail.")
        _post(app, tickets.chat_summary(ticket, packet))
        try:
            webbrowser.open(packet.as_uri())
        except Exception:
            pass

    label = f"Read ticket with {engine_name}" if engine_name else "Read ticket"
    ui.button(actions, label, read, active=True).pack(side="left")
    ui.button(actions, "Redraft statement", redraft, small=True).pack(side="left", padx=8)
    ui.button(actions, "Make paperwork", make, small=True).pack(side="left")
    ui.button(actions, "Folder", lambda: _open_folder(status), small=True).pack(side="left", padx=8)
    if not clouds:
        status.set("Claude or OpenAI isn't connected (Tools → AI brains), so type the details in, then Make paperwork.")
    window.ticket_helper = {"load": load, "fill": fill, "current": current, "make": make, "read": read,
                            "state": state, "status": status, "variables": variables, "statement": statement}
    load(path) if path else draw()
    return window


def _post(app, text: str) -> None:
    try:
        app.db.add_message("assistant", text)
        app._append("assistant", "DOXA\n")
        app._append("body", text + "\n\n")
        app.refresh_all()
    except Exception:
        pass  # the packet is saved either way; the chat note is a convenience


def _open_folder(status):
    folder = tickets.output_dir()
    if folder.is_dir():
        os.startfile(folder)  # noqa: S606 - opens Explorer on Doxa's own folder
    else:
        status.set("No packets yet.")
