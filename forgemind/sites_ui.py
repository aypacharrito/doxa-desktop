"""Website builder panel (Tools → Website builder, or say "build a website for <business>")."""
from __future__ import annotations

import re
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, ttk

from . import jarvis_ui as ui
from . import sites

SITE_REQUEST = re.compile(
    r"\b(?:build|make|create|design|do)\b(?:\s+(?:me|us))?\s+(?:a\s+|an\s+)?(?:new\s+)?(?:web\s*site|site|landing page)"
    r"(?:\s+for\s+(?P<name>[^.?!\n]{2,80}))?", re.I)


def site_request(text: str) -> str | None:
    """"build a website for Casa Luna" -> "Casa Luna"; "make me a website" -> ""; anything else -> None."""
    match = SITE_REQUEST.search(text or "")
    if not match:
        return None
    return (match.group("name") or "").strip(" ,'\"")


def _text(parent, height):
    return tk.Text(parent, height=height, wrap="word", bg=ui.SURFACE_2, fg=ui.TEXT, insertbackground=ui.GOLD,
                   relief="flat", borderwidth=6, highlightthickness=1, highlightbackground=ui.LINE,
                   highlightcolor=ui.GOLD_DIM, font=(ui.BODY, 11))


def open_builder(app, name: str = ""):
    from .calendar_ui import _entry
    window, content = ui._panel(app, "Website builder",
                                "Film the business (storefront, walk in, slow pan, the work), put the clips and photos "
                                "in one folder, fill in the facts, and press Build. You get the site, a laptop-and-phone "
                                "preview to show the owner, and a proposal with a shot list.", size="660x820")
    values = {key: tk.StringVar(value=default) for key, default in
              [("name", name), ("kind", ""), ("city", ""), ("phone", ""), ("address", ""), ("folder", ""),
               ("style", "cinematic")]}

    def label(text):
        tk.Label(content, text=text, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY_BOLD, 9), anchor="w").pack(fill="x", pady=(10, 2))

    for key, text in [("name", "Business name"), ("kind", "What kind of business (e.g. Mexican restaurant, barbershop)"),
                      ("city", "City"), ("phone", "Phone"), ("address", "Street address")]:
        label(text)
        _entry(content, values[key]).pack(fill="x")
    label("Hours (one line each, e.g. Mon–Fri 9am–6pm)")
    hours = _text(content, 3)
    hours.pack(fill="x")
    label("What they're known for (in the owner's words)")
    offer = _text(content, 3)
    offer.pack(fill="x")
    label("Anything else (languages, parking, specials)")
    notes = _text(content, 2)
    notes.pack(fill="x")
    label("Look")
    ttk.Combobox(content, textvariable=values["style"], values=list(sites.STYLES), state="readonly").pack(anchor="w")
    label("Footage and photos folder")
    row = tk.Frame(content, bg=ui.BG)
    row.pack(fill="x")
    tk.Label(row, textvariable=values["folder"], bg=ui.BG, fg=ui.TEXT, font=(ui.BODY, 10), anchor="w").pack(
        side="left", fill="x", expand=True)
    ui.button(row, "Choose folder…", lambda: values["folder"].set(
        filedialog.askdirectory(parent=window, title="Folder with the business's footage") or values["folder"].get()),
              small=True).pack(side="right")
    cloud = getattr(app, "cloud", None)
    use_ai = tk.BooleanVar(value=bool(cloud and cloud.loaded))
    ttk.Checkbutton(content, variable=use_ai,
                    text=("Write the copy with OpenAI (1 request from Doxa's $5/month budget)" if cloud and cloud.loaded
                          else "OpenAI isn't connected (Tools → Autopilot); copy will be written from your facts"),
                    state="normal" if cloud and cloud.loaded else "disabled").pack(anchor="w", pady=(14, 4))
    status = tk.StringVar(value="")
    tk.Label(content, textvariable=status, bg=ui.BG, fg=ui.GOLD, font=(ui.BODY, 10), anchor="w", justify="left",
             wraplength=560).pack(fill="x", pady=6)

    def build():
        brief = sites.SiteBrief(name=values["name"].get().strip(), kind=values["kind"].get().strip(),
                                city=values["city"].get().strip(), phone=values["phone"].get().strip(),
                                address=values["address"].get().strip(), hours=hours.get("1.0", "end").strip(),
                                offer=offer.get("1.0", "end").strip(), notes=notes.get("1.0", "end").strip(),
                                style=values["style"].get(), media_folder=values["folder"].get())
        if not brief.name:
            status.set("Enter the business name.")
            return
        build_button.configure(state="disabled")
        brain = cloud if (use_ai.get() and cloud and cloud.loaded) else None

        def work():
            try:
                result = sites.build_site(brief, brain=brain,
                                          progress=lambda m: app.events.put(("ui", lambda m=m: status.set(m))))
                app.events.put(("ui", lambda: finished(result)))
            except Exception as exc:  # show the reason; the panel stays open to fix the input
                app.events.put(("ui", lambda exc=exc: (status.set(f"Couldn't build it: {exc}"),
                                                       build_button.configure(state="normal"))))
        threading.Thread(target=work, daemon=True, name="doxa-site").start()

    def finished(result):
        build_button.configure(state="normal")
        status.set(f"Done{' (copy by OpenAI)' if result.used_ai else ''}. Opening the preview…")
        webbrowser.open(result.preview.as_uri())
        note = (f"Website for {result.folder.name} is ready.\nPreview to show the owner: {result.preview}\n"
                f"Site files (upload this folder to any web host): {result.folder}\nProposal + shot list: {result.pitch}")
        app.db.add_message("assistant", note)
        app._append("assistant", "DOXA\n")
        app._append("body", note + "\n\n")
        app.refresh_all()

    build_button = ui.button(content, "Build the website", build, active=True)
    build_button.pack(anchor="w", pady=(8, 20))
    return window
