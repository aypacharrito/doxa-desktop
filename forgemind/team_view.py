"""The Team side of Chat | Code | Team: Doxa's marketing HQ (rooms, workers, live counts, your approval gate)."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import jarvis_ui as ui
from .team import ROOMS

STATUS_COLOR = {"working": ui.GOLD, "done": "#5fd39a", "problem": ui.ERROR, "waiting": "#f2b54a"}
AUTOMATED = {"research", "writers", "analyst"}
HUMAN = {"approval", "film", "shipping"}


def _short(text, n=160):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def build(app, parent) -> tk.Frame:
    frame = tk.Frame(parent, bg=ui.BG)
    store, runner = app.team, app.team_runner
    state = {"room": "approval", "sig": None}

    head = tk.Frame(frame, bg=ui.BG)
    head.pack(fill="x", pady=(10, 6))
    title = tk.Label(head, text="", bg=ui.BG, fg=ui.TEXT, font=(ui.DISPLAY, 15), anchor="w")
    title.pack(side="left")
    goal = tk.Label(frame, text="", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 10), anchor="w", justify="left", wraplength=900)
    goal.pack(fill="x")
    classic = tk.Frame(frame, bg=ui.BG)  # the classic cards (shown in the HQ window when the 3D floor can't load)

    def new_campaign():
        name = simpledialog.askstring("New campaign", "Name (e.g. 'Song: Midnight Drive' or 'Cloth roll test')", parent=app)
        if not name:
            return
        target = simpledialog.askstring("New campaign", "One measurable goal (e.g. '1,000 saves before release on Dec 1' "
                                        "or '20 orders in 14 days')", parent=app)
        if not target:
            return
        audience = simpledialog.askstring("New campaign", "Who it's for (optional)", parent=app) or ""
        offer = simpledialog.askstring("New campaign", "Link or offer people should go to (optional)", parent=app) or ""
        try:
            store.create_campaign(name, target, audience, offer=offer)
        except ValueError as exc:
            messagebox.showinfo("New campaign", str(exc), parent=app)
            return
        state["sig"] = None
        refresh()
    ui.link(head, "+ New campaign", new_campaign, color=ui.GOLD).pack(side="right")
    ui.link(head, "Open folder", lambda: _open_folder(), color=ui.MUTED).pack(side="right", padx=14)

    def _open_folder():
        campaign = store.campaign()
        if campaign:
            path = store.folder(campaign)
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))

    # --- the line of rooms ---------------------------------------------------------------------------------
    line = tk.Frame(classic, bg=ui.BG)
    line.pack(fill="x", pady=(12, 8))
    cards, whos = {}, {}
    for index, (key, room, worker, about) in enumerate(ROOMS):
        col, row = index % 4, index // 4
        line.columnconfigure(col, weight=1, uniform="rooms")
        card = tk.Frame(line, bg=ui.SURFACE, padx=14, pady=10, cursor="hand2")
        card.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        top = tk.Frame(card, bg=ui.SURFACE)
        top.pack(fill="x")
        dot = tk.Label(top, text="●", bg=ui.SURFACE, fg=ui.FAINT, font=(ui.BODY, 9))
        dot.pack(side="left")
        tk.Label(top, text=f"{index + 1}. {room}", bg=ui.SURFACE, fg=ui.TEXT, font=(ui.BODY_BOLD, 10)).pack(side="left", padx=(4, 0))
        count = tk.Label(card, text="0", bg=ui.SURFACE, fg=ui.GOLD, font=(ui.DISPLAY, 22), anchor="w")
        count.pack(fill="x")
        who = tk.Label(card, text=worker if worker == "You" else f"{worker} · AI" if key in AUTOMATED else
                       f"{worker} · coming next", bg=ui.SURFACE, fg=ui.MUTED,
                       font=(ui.BODY, 9), anchor="w")
        who.pack(fill="x")
        whos[key] = (who, worker)
        detail = tk.Label(card, text=about, bg=ui.SURFACE, fg=ui.FAINT, font=(ui.BODY, 8), anchor="w", justify="left",
                          wraplength=200)
        detail.pack(fill="x", pady=(2, 0))
        cards[key] = (card, dot, count, detail, about)
        for widget in (card, top, count, who, detail, dot):
            widget.bind("<Button-1>", lambda _e, k=key: select(k))

    # --- the selected room's work ----------------------------------------------------------------------------
    panel_head = tk.Frame(classic, bg=ui.BG)
    panel_head.pack(fill="x", pady=(10, 4))
    panel_title = tk.Label(panel_head, text="", bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 12), anchor="w")
    panel_title.pack(side="left")
    run_button = ui.button(panel_head, "Run", lambda: run(state["room"]), active=True)
    outer = tk.Frame(classic, bg=ui.BG)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=ui.BG, highlightthickness=0, borderwidth=0)
    bar = ui.ThinScroll(outer, command=canvas.yview)
    body = tk.Frame(canvas, bg=ui.BG)
    window_id = canvas.create_window(0, 0, window=body, anchor="nw")
    body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")))
    canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    def run(room):
        try:
            runner.start(room)
        except ValueError as exc:
            messagebox.showinfo("Team", str(exc), parent=app)
        refresh(force=True)

    def select(room):
        state["room"] = room
        refresh(force=True)

    def row(text, sub="", buttons=()):
        box = tk.Frame(body, bg=ui.SURFACE, padx=14, pady=10)
        box.pack(fill="x", pady=3)
        tk.Label(box, text=text, bg=ui.SURFACE, fg=ui.TEXT, font=(ui.BODY_BOLD, 10), anchor="w", justify="left",
                 wraplength=880).pack(fill="x")
        if sub:
            tk.Label(box, text=sub, bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w", justify="left",
                     wraplength=880).pack(fill="x", pady=(3, 0))
        if buttons:
            actions = tk.Frame(box, bg=ui.SURFACE)
            actions.pack(fill="x", pady=(6, 0))
            for label, command, active in buttons:
                ui.button(actions, label, command, small=True, active=active).pack(side="left", padx=(0, 8))
        return box

    def act(fn):
        def go():
            try:
                fn()
            except ValueError as exc:
                messagebox.showinfo("Team", str(exc), parent=app)
            refresh(force=True)
        return go

    def post_dialog(item):
        platform = simpledialog.askstring("Posted", "Which platform? (TikTok, Instagram, YouTube…)", parent=app)
        if not platform:
            return
        link = simpledialog.askstring("Posted", "Paste the post's link (that's the receipt):", parent=app)
        if link:
            act(lambda: store.mark_posted(item["id"], platform, link))()

    def results_dialog(item, index):
        values = {}
        for key in ("views", "likes", "comments", "shares", "saves", "follows", "clicks", "sales", "revenue"):
            value = simpledialog.askstring("Results", f"{key.capitalize()} (leave empty if unknown)", parent=app)
            if value is None:
                return
            if value.strip():
                try:
                    values[key] = float(value.replace(",", ""))
                except ValueError:
                    pass
        act(lambda: store.record_results(item["id"], index, values))()

    def fill_body():
        for child in body.winfo_children():
            child.destroy()
        room = state["room"]
        campaign = store.campaign()
        if not campaign:
            row("Start your first campaign", "Press + New campaign: one song or product, one audience, one measurable "
                "goal. Then Research finds what's working, the Writers' Room drafts scripts, and you approve.")
            return
        items = store.items()
        if room == "research":
            row("Research brief", campaign.get("brief_path") or "Not run yet. Press Run: Nova searches the web for what's "
                "working now, with links (a few minutes, ~$1-3 of Claude).",
                [("Open brief", lambda: os.startfile(campaign["brief_path"]), False)] if campaign.get("brief_path") else ())
            if campaign.get("brief"):
                row("Summary for the writers", _short(campaign["brief"][-1200:], 1200))
        elif room == "writers":
            if not items:
                row("No scripts yet", "Press Run after Research: Quill writes 6 different scripts from the brief.")
            for item in items[-30:]:
                row(f"[{item['stage']}] {item.get('angle', '')}: {item['hook']}", _short(item.get("script"), 300))
        elif room == "approval":
            waiting = [i for i in items if i["stage"] == "waiting"]
            if not waiting:
                row("Nothing waiting on you", "New scripts land here. Nothing gets filmed or posted without your OK.")
            for item in waiting:
                row(f"{item.get('angle', '')}: {item['hook']}",
                    f"{_short(item.get('script'), 600)}\nCTA: {item.get('cta', '')}\nWhy: {_short(item.get('why'), 200)}",
                    [("Approve", act(lambda i=item: store.decide(i["id"], True)), True),
                     ("Reject", act(lambda i=item: store.decide(i["id"], False)), False)])
        elif room == "film":
            approved = [i for i in items if i["stage"] == "approved"]
            if not approved:
                row("Nothing to film yet", "Approved scripts show up here with filming notes.")
            for item in approved:
                row(item["hook"], f"{_short(item.get('script'), 500)}\nFilming: {item.get('film_notes', '')}",
                    [("Mark filmed", act(lambda i=item: store.mark_filmed(i["id"])), True)])
        elif room in ("edit", "shipping"):
            filmed = [i for i in items if i["stage"] in ("filmed", "posted")]
            if not filmed:
                row("Nothing filmed yet", "Film an approved script first.")
            for item in filmed:
                posts = item.get("posts", [])
                sub = f"Caption: {item.get('caption', '')}\n{' '.join('#' + str(t).lstrip('#') for t in item.get('hashtags') or [])}"
                if posts:
                    sub += "\nPosted: " + ", ".join(f"{p['platform']} {p['link']}" for p in posts)
                buttons = [("I posted it…", lambda i=item: post_dialog(i), True)]
                buttons += [(f"Results: {p['platform']}", lambda i=item, n=n: results_dialog(i, n), False)
                            for n, p in enumerate(posts)]
                row(item["hook"], sub, buttons)
        elif room == "mailroom":
            row("Not automated yet", "To read and draft replies to comments and DMs, connect your Instagram/TikTok "
                "accounts in Plugins (Composio or Zapier). Replies would still wait for your OK.")
        elif room == "analyst":
            row("Analysis", campaign.get("analysis") or "Post videos, enter their results, then press Run: Ledger "
                "compares hooks, picks the next experiment and saves lessons for all your AIs.")

    def refresh(force=False):
        if not frame.winfo_exists():
            return
        campaign = store.campaign()
        title.configure(text=f"Marketing team · {campaign['name']}" if campaign else "Marketing team")
        goal.configure(text=f"Goal: {campaign['goal']}" if campaign else "One campaign at a time: one goal, one audience, "
                       "measured. You're the only human on the team.")
        counts = store.counts() if campaign else {}
        workers = store.data.get("workers", {})
        try:
            models = runner.models()
        except Exception:
            models = {}
        for key, (who, name) in whos.items():
            if key in AUTOMATED:  # which AIs staff the room right now, e.g. "Nova · Gemini + Claude"
                who.configure(text=f"{name} · " + (" + ".join(models.get(key) or []) or "no AI connected"))
        for key, (card, dot, count, detail, about) in cards.items():
            worker = workers.get(key, {})
            status = "working" if key in runner.busy else worker.get("status", "")
            if key in HUMAN and counts.get(key):
                status = "waiting"
            dot.configure(fg=STATUS_COLOR.get(status, ui.FAINT))
            count.configure(text=str(counts.get(key, 0)))
            detail.configure(text=_short(worker.get("detail") or about, 110) if key in AUTOMATED else about)
            selected = key == state["room"]
            for widget in (card,) + tuple(card.winfo_children()):
                try:
                    widget.configure(bg=ui.SURFACE_2 if selected else ui.SURFACE)
                except tk.TclError:
                    pass
            for child in card.winfo_children():
                for grandchild in child.winfo_children():
                    grandchild.configure(bg=ui.SURFACE_2 if selected else ui.SURFACE)
        room = state["room"]
        name = dict((k, r) for k, r, _w, _d in ROOMS)[room]
        panel_title.configure(text=name + (" · working…" if room in runner.busy else ""))
        if room in AUTOMATED and campaign:
            run_button.pack(side="right")
            run_button.configure(text="Working…" if room in runner.busy else f"Run {name}",
                                 state="disabled" if room in runner.busy else "normal")
        else:
            run_button.pack_forget()
        sig = (room, campaign and campaign["id"], tuple(sorted(counts.items())), len(store.data["items"]),
               (campaign or {}).get("brief_path"), bool((campaign or {}).get("analysis")))
        if force or sig != state["sig"]:
            state["sig"] = sig
            fill_body()

    def tick():
        if frame.winfo_exists():
            refresh()
            frame.after(1500, tick)
    app.team_refresh = lambda: refresh(force=True)
    classic.pack(fill="both", expand=True)
    refresh(force=True)
    frame.after(1500, tick)
    return frame
