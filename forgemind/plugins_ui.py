"""Plugins page: your connections on top, then ready-to-add apps you connect with one click (like Claude/ChatGPT).

the owner, 2026-11-10 (screenshot of Claude's Plugins page): "make plugins clean like this … links ready and connections
just quick ready to add". Catalog apps sign in through the browser (`mcp_oauth.sign_in`, in a background thread; the
page polls it); anything else goes through "Add by link" (address + optional token, or a browser sign-in when the
address offers one).
"""
from __future__ import annotations

import threading
import tkinter as tk

from . import jarvis_ui as ui
from . import mcp_oauth
from .plugin_catalog import CATALOG, GROUPS, BY_ID, Plugin, find, match_url

POLL_MS = 300
TILE = 34


def _ink_for(color: str) -> str:
    """White or black letter, whichever reads better on the tile colour."""
    value = color.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 165 else "#ffffff"


def _tile_image(parent, color: str, letter: str, size: int, back: str):
    """Anti-aliased rounded app icon (drawn 4x and scaled down; Tk's own canvas shapes have jagged edges).
    Cached on the Tk root, since an image belongs to one Tk interpreter."""
    root = parent._root()
    cache = root.__dict__.setdefault("_doxa_tiles", {})
    key = (color, letter, size, back)
    if key in cache:
        return cache[key]
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
    except ImportError:
        return None
    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), back)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.26), fill=color)
    font = None
    icon = len(letter) == 1 and 0xE000 <= ord(letter) <= 0xF8FF  # a Windows icon-font glyph instead of a letter
    for name in (("SegoeIcons.ttf", "segmdl2.ttf") if icon else ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf")):
        try:
            font = ImageFont.truetype(name, int(big * 0.46))
            break
        except OSError:
            continue
    if font is not None:
        draw.text((big / 2, big / 2), letter, fill=_ink_for(color), font=font, anchor="mm")
    photo = ImageTk.PhotoImage(image.resize((size, size), Image.LANCZOS), master=root)
    cache[key] = photo
    return photo


def icon_tile(parent, color: str, letter: str, size: int = TILE):
    photo = _tile_image(parent, color, letter, size, parent.cget("bg"))
    if photo is not None:
        label = tk.Label(parent, image=photo, bg=parent.cget("bg"), borderwidth=0)
        label.image = photo
        return label
    canvas = tk.Canvas(parent, width=size, height=size, bg=parent.cget("bg"), highlightthickness=0, borderwidth=0)
    r, s = 8, size - 1
    points = [r, 0, s - r, 0, s, 0, s, r, s, s - r, s, s, s - r, s, r, s, 0, s, 0, s - r, 0, r, 0, 0]
    canvas.create_polygon(points, smooth=True, fill=color, outline=color)
    canvas.create_text(size / 2, size / 2 + 1, text=letter, fill=_ink_for(color), font=(ui.BODY_BOLD, 13))
    return canvas


class PluginsPage:
    def __init__(self, app):
        self.app = app
        self.store = app.plugins
        self.query = ""
        self.group = "All"
        self.jobs: dict[str, dict] = {}
        self.window, content = ui._panel(
            app, "Plugins", "Connect your apps once, then just ask in chat: \"make a payment link for the blue "
                            "jersey\", \"add this lead to my sheet\", \"what's new in Notion\". Sign-ins happen in "
                            "your browser; Doxa keeps the keys in Windows Credential Manager.", size="800x900")
        self._top(content)
        self.form = tk.Frame(content, bg=ui.BG)
        self.body = tk.Frame(content, bg=ui.BG)
        self.body.pack(fill="both", expand=True)
        self.window.bind("<Destroy>", self._closed, add="+")
        self.render()
        self._poll_after = self.window.after(POLL_MS, self._poll)

    # --- top bar -------------------------------------------------------------------------------------------
    def _top(self, content):
        from .calendar_ui import _entry
        bar = tk.Frame(content, bg=ui.BG)
        bar.pack(fill="x", pady=(2, 8))
        box = tk.Frame(bar, bg=ui.SURFACE, padx=10, pady=4)
        box.pack(side="left", fill="x", expand=True)
        tk.Label(box, text=ui.GLYPH.get("search", "⌕"), bg=ui.SURFACE, fg=ui.MUTED, font=(ui.ICONS, 10)).pack(
            side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        entry = _entry(box, self.search_var)
        entry.configure(bg=ui.SURFACE, relief="flat", highlightthickness=0, borderwidth=0)
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        entry.bind("<KeyRelease>", lambda _e: self._search_soon())
        self.search_entry = entry
        hint = tk.Label(entry, text="Search plugins", bg=ui.SURFACE, fg=ui.FAINT, font=(ui.BODY, 10), cursor="xterm")
        hint.place(x=6, rely=0.5, anchor="w")
        hint.bind("<Button-1>", lambda _e: entry.focus_set())
        self.search_var.trace_add("write", lambda *_: hint.place_forget() if self.search_var.get()
                                  else hint.place(x=6, rely=0.5, anchor="w"))
        ui.button(bar, "+  Add by link", self.toggle_form, small=True).pack(side="right", padx=(8, 0))
        chips = tk.Frame(content, bg=ui.BG)
        chips.pack(fill="x", pady=(0, 10))
        self.chips = {}
        for name in ["All", "Connected"] + GROUPS:
            chip = tk.Label(chips, text=name, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY_BOLD, 9), padx=10, pady=4,
                            cursor="hand2")
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda _e, n=name: self.set_group(n))
            self.chips[name] = chip
        self._paint_chips()

    def _paint_chips(self):
        for name, chip in self.chips.items():
            on = name == self.group
            chip.configure(bg=ui.RAISED if on else ui.BG, fg=ui.TEXT if on else ui.MUTED)

    def set_group(self, name):
        self.group = name
        self._paint_chips()
        self.render()

    def _search_soon(self):
        if getattr(self, "_search_after", None):
            self.window.after_cancel(self._search_after)
        self._search_after = self.window.after(150, self._search_now)

    def _search_now(self):
        self._search_after = None
        self.query = self.search_var.get().strip()
        self.render()

    # --- add by link ---------------------------------------------------------------------------------------
    def toggle_form(self):
        if self.form.winfo_ismapped():
            self.form.pack_forget()
            return
        for child in self.form.winfo_children():
            child.destroy()
        from .calendar_ui import _entry
        card = tk.Frame(self.form, bg=ui.SURFACE, padx=16, pady=12)
        card.pack(fill="x")
        tk.Label(card, text="Add any app by its MCP link", bg=ui.SURFACE, fg=ui.TEXT, font=(ui.BODY_BOLD, 11),
                 anchor="w").pack(fill="x")
        tk.Label(card, text="Paste the app's MCP address. If it offers a browser sign-in, Doxa opens it for you; "
                            "otherwise paste its token too.", bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY, 9),
                 anchor="w", justify="left", wraplength=640).pack(fill="x", pady=(2, 8))
        self.label_var, self.url_var, self.token_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for text, var, secret in (("Name", self.label_var, False), ("MCP address (https://…)", self.url_var, False),
                                  ("Token (only if the app gives you one)", self.token_var, True)):
            tk.Label(card, text=text, bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY_BOLD, 9), anchor="w").pack(
                fill="x", pady=(4, 2))
            entry = _entry(card, var)
            if secret:
                entry.configure(show="•")
            entry.pack(fill="x")
        row = tk.Frame(card, bg=ui.SURFACE)
        row.pack(fill="x", pady=(10, 0))
        ui.button(row, "Connect", self.add_custom, active=True, small=True).pack(side="left")
        self.form_message = tk.StringVar()
        tk.Label(row, textvariable=self.form_message, bg=ui.SURFACE, fg=ui.MUTED, font=(ui.BODY, 9),
                 anchor="w").pack(side="left", padx=10)
        self.form.pack(fill="x", pady=(0, 12), before=self.body)

    def add_custom(self):
        url, token = self.url_var.get().strip(), self.token_var.get().strip()
        label = self.label_var.get().strip()
        known = match_url(url)
        if known and not token:
            self.form.pack_forget()
            self.connect(known)
            return
        if token:
            try:
                self.store.add(label, url, token)
            except ValueError as problem:
                self.form_message.set(str(problem))
                return
            self.form.pack_forget()
            self.render()
            return
        try:
            from .plugins import clean_url
            clean_url(url)
        except ValueError as problem:
            self.form_message.set(str(problem))
            return
        self._start_job("custom", label, url, None)
        self.form_message.set("Checking the address…")

    # --- connecting ------------------------------------------------------------------------------------------
    def connect(self, plugin: Plugin):
        if plugin.auth == "open":
            self.store.connect(plugin.name, plugin.url, {"url": plugin.url, "token": ""}, plugin.id)
            self.render()
            return
        self._start_job(plugin.id, plugin.name, plugin.url, plugin)

    def _start_job(self, key, label, url, plugin):
        if key in self.jobs and not self.jobs[key]["done"]:
            return
        job = {"step": "Starting…", "error": "", "done": False, "secret": None, "label": label, "url": url,
               "plugin": plugin, "cancel": threading.Event(), "shown": ""}
        self.jobs[key] = job

        def work():
            try:
                meta = None
                if plugin is None:
                    found = mcp_oauth.probe(url)
                    if found["kind"] == "open":
                        job["secret"] = {"url": url, "token": ""}
                        return
                    if found["kind"] != "oauth":
                        raise mcp_oauth.SignInError("This address needs a token: paste it in the Token box." if
                                                    found["kind"] == "token" else "Couldn't reach that address.")
                    meta = found["meta"]
                job["secret"] = mcp_oauth.sign_in(url, meta, cancel=job["cancel"],
                                                  on_step=lambda text: job.update(step=text))
            except Exception as problem:  # shown on the tile; nothing is saved
                job["error"] = str(problem)[:200]
            finally:
                job["done"] = True

        threading.Thread(target=work, daemon=True, name=f"doxa-plugin-{key}").start()
        self.render()

    def _poll(self):
        if not self.window.winfo_exists():
            return
        changed = False
        for key, job in list(self.jobs.items()):
            if job["done"] and job["secret"] is not None:
                plugin = job["plugin"]
                try:
                    self.store.connect(plugin.name if plugin else job["label"], job["url"], job["secret"],
                                       plugin.id if plugin else "")
                except ValueError as problem:
                    job["error"], job["secret"] = str(problem), None
                    continue
                del self.jobs[key]
                if key == "custom":
                    self.form.pack_forget()
                changed = True
            elif job["done"] and key == "custom" and job["error"]:
                if hasattr(self, "form_message"):
                    self.form_message.set(job["error"])
                del self.jobs[key]
            else:
                text = job["error"] or job["step"]
                if text != job["shown"]:
                    job["shown"] = text
                    if job.get("var") is not None:
                        job["var"].set(text)
                    if key == "custom" and hasattr(self, "form_message"):
                        self.form_message.set(text)
        if changed:
            self.render()
        self._poll_after = self.window.after(POLL_MS, self._poll)

    def _closed(self, event):
        if event.widget is self.window:
            for job in self.jobs.values():
                job["cancel"].set()
            try:
                self.window.after_cancel(self._poll_after)
            except (tk.TclError, AttributeError):
                pass

    # --- drawing -------------------------------------------------------------------------------------------
    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        if self.query or self.group not in ("All", "Connected"):
            found = find(self.query, "" if self.group in ("All", "Connected") else self.group)
            if self.group == "Connected":
                found = [p for p in found if self.store.by_catalog(p.id)]
            mine = self._mine(self.query) if self.group in ("All", "Connected") else []
            if mine:
                self._section("YOUR PLUGINS")
                for item in mine:
                    self._mine_row(item)
            self._section(self.group.upper() if self.group not in ("All", "Connected") else "RESULTS",
                          top=14 if mine else 0)
            if found:
                self._grid(found)
            elif not mine:
                tk.Label(self.body, text="Nothing matches. Try another word, or use Add by link.", bg=ui.BG,
                         fg=ui.FAINT, font=(ui.BODY, 10), anchor="w").pack(fill="x")
            return
        self._section("YOUR PLUGINS")
        mine = self._mine()
        if not mine:
            tk.Label(self.body, text="None yet. Pick an app below and press Connect.", bg=ui.BG, fg=ui.FAINT,
                     font=(ui.BODY, 10), anchor="w").pack(fill="x", pady=(0, 4))
        for item in mine:
            self._mine_row(item)
        self._builtins()
        if self.group == "Connected":
            return
        self._section("POPULAR", top=18)
        self._grid([p for p in CATALOG if p.popular])
        for group in GROUPS:
            rest = [p for p in CATALOG if p.group == group and not p.popular]
            if rest:
                self._section(group.upper(), top=18)
                self._grid(rest)

    def _section(self, text, top=0):
        tk.Label(self.body, text=text, bg=ui.BG, fg=ui.FAINT, font=(ui.BODY_BOLD, 8), anchor="w").pack(
            fill="x", pady=(top, 6))

    def _mine(self, query=""):
        words = query.lower().split()
        return [item for item in self.store.list()
                if all(w in f"{item.get('label', '')} {item.get('host', '')}".lower() for w in words)]

    def _mine_row(self, item):
        plugin = BY_ID.get(item.get("catalog", ""))
        row = tk.Frame(self.body, bg=ui.BG, padx=4, pady=10)
        row.pack(fill="x")
        tk.Frame(self.body, bg=ui.LINE, height=1).pack(fill="x")
        color, letter = (plugin.color, plugin.letter) if plugin else (ui.RAISED, (item.get("label") or "?")[0].upper())
        icon_tile(row, color, letter).pack(side="left", padx=(0, 12))
        text = tk.Frame(row, bg=ui.BG)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=item.get("label", item["name"]), bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 11),
                 anchor="w").pack(fill="x")
        sub = f"Connector · By {plugin.by}" if plugin else f"Connector · {item.get('host', '')}"
        tk.Label(text, text=sub, bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9), anchor="w").pack(fill="x")
        on, expired = item.get("enabled", True), item.get("needs_sign_in", False)

        def remove(name=item["name"]):
            self.store.remove(name)
            self.render()

        def toggle(name=item["name"], on=on):
            self.store.set_enabled(name, not on)
            self.render()
        # one status line + quiet actions (1.38.2): "Connected · Read-only"   Allow changes   Turn off   Remove
        ui.button(row, "Remove", remove, small=True).pack(side="right")
        if expired and plugin:
            ui.button(row, "Sign in again", lambda p=plugin: self.connect(p), small=True).pack(side="right")
        else:
            ui.button(row, "Turn off" if on else "Turn on", toggle, small=True).pack(side="right")
        money = bool(plugin and plugin.money and not expired)
        locked = money and self.store.read_only(item)
        if money:
            ui.button(row, "Allow changes" if locked else "Make read-only",
                      lambda name=item["name"], label=item.get("label", ""), locked=locked:
                      self._toggle_writes(name, label, locked), small=True).pack(side="right")
        status = "Sign-in expired" if expired else ("Connected" if on else "Off")
        if money and on:
            status += " · Read-only" if locked else " · Can make changes"
        color = ui.ERROR if expired or (money and on and not locked) else (ui.GOLD if on else ui.FAINT)
        tk.Label(row, text=status, bg=ui.BG, fg=color, font=(ui.BODY, 9)).pack(side="right", padx=(0, 12))

    def _toggle_writes(self, name, label, locked):
        if locked:
            from tkinter import messagebox
            if not messagebox.askyesno(
                    f"Let Doxa make changes in {label}?",
                    f"Doxa will be able to create products, prices, payment links, customers and other changes in "
                    f"{label} without asking you each time. Refunds and money transfers may still need your OK in "
                    f"{label}'s own dashboard.\n\nIf this is your live account, real customers and real money are "
                    f"involved. Allow changes?", icon="warning", parent=self.window):
                return
        self.store.set_read_only(name, not locked)
        self.render()

    def _builtins(self):
        app = self.app
        rows = []
        claude_on = getattr(app, "claude", None) is not None and app.claude.loaded
        openai_on = getattr(app, "cloud", None) is not None and app.cloud.loaded
        rows.append(("AI brains", "Claude, ChatGPT, Gemini, OpenCode Go and their budgets", "#e2b65e", "A",
                     "Connected" if claude_on or openai_on else "Off", getattr(app, "show_brains", None),
                     claude_on or openai_on))
        calendar_on = False
        try:
            calendar_on = app.calendar.connected()
        except Exception:
            pass
        rows.append(("Google Calendar", "See your day and add events (you approve each one)", "#1a73e8", "G",
                     "Connected" if calendar_on else "Not connected", getattr(app, "show_calendar", None),
                     calendar_on))
        try:
            from . import pacifica, pacifica_ui
            pac_on = pacifica.is_configured(app.settings_data.pacifica_url)
            rows.append(("Pacifica CRM", "Start quote requests from chat", "#0e7c66", "P",
                         "Connected" if pac_on else "Not connected", lambda: pacifica_ui.open_connection(app), pac_on))
        except Exception:
            pass
        phone_on = bool(app.phone_access.data.get("enabled")) if getattr(app, "phone_access", None) else False
        rows.append(("Your phone", "Doxa, Code mode and your PC screen from anywhere", "#3a3a44", "",
                     "On" if phone_on else "Off", getattr(app, "show_phone", None), phone_on))
        self._section("BUILT IN", top=14)
        for title, sub, color, letter, status, action, good in rows:
            row = tk.Frame(self.body, bg=ui.BG, padx=4, pady=10)
            row.pack(fill="x")
            tk.Frame(self.body, bg=ui.LINE, height=1).pack(fill="x")
            icon_tile(row, color, letter).pack(side="left", padx=(0, 12))
            text = tk.Frame(row, bg=ui.BG)
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=title, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 11), anchor="w").pack(fill="x")
            tk.Label(text, text=sub, bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9), anchor="w").pack(fill="x")
            if action:
                ui.button(row, "Manage", action, small=True).pack(side="right")
            tk.Label(row, text=status, bg=ui.BG, fg=ui.GOLD if good else ui.FAINT, font=(ui.BODY_BOLD, 9)).pack(
                side="right", padx=10)

    def _grid(self, plugins):
        grid = tk.Frame(self.body, bg=ui.BG)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="tile")
        grid.columnconfigure(1, weight=1, uniform="tile")
        for index, plugin in enumerate(plugins):
            self._tile(grid, plugin).grid(row=index // 2, column=index % 2, sticky="nsew",
                                          padx=(0, 20) if index % 2 == 0 else (20, 0), pady=2)

    def _tile(self, parent, plugin: Plugin):
        tile = tk.Frame(parent, bg=ui.BG, padx=4, pady=12)
        icon_tile(tile, plugin.color, plugin.letter).pack(side="left", anchor="n", padx=(0, 10))
        action = tk.Frame(tile, bg=ui.BG)  # packed before the text so a long blurb can't squeeze the button
        action.pack(side="right", anchor="n", padx=(8, 0))
        text = tk.Frame(tile, bg=ui.BG)
        text.pack(side="left", fill="both", expand=True)
        saved = self.store.by_catalog(plugin.id)
        connected = bool(saved) and not saved.get("needs_sign_in")
        title = plugin.name + ("  ✓" if connected else "")
        tk.Label(text, text=title, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 11), anchor="w").pack(fill="x")
        tk.Label(text, text=plugin.blurb, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9), anchor="w",
                 justify="left", wraplength=200).pack(fill="x")
        meta = "Connector · By " + plugin.by + (" · no account needed" if plugin.auth == "open" else "")
        tk.Label(text, text=meta, bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 8), anchor="w").pack(fill="x", pady=(2, 0))
        if plugin.money and not connected:
            tk.Label(text, text="Payments: sign in to a test account first", bg=ui.BG, fg=ui.GOLD_DIM,
                     font=(ui.BODY, 8), anchor="w", justify="left", wraplength=200).pack(fill="x")
        job = self.jobs.get(plugin.id)
        if job is not None and not job["done"] or (job is not None and job["error"]):
            job["var"] = tk.StringVar(value=job["error"] or job["step"])
            job["shown"] = job["var"].get()
            tk.Label(text, textvariable=job["var"], bg=ui.BG, fg=ui.ERROR if job["error"] else ui.GOLD,
                     font=(ui.BODY_BOLD, 8), anchor="w", justify="left", wraplength=230).pack(fill="x", pady=(2, 0))
            if job["error"]:
                def retry(p=plugin):
                    self.jobs.pop(p.id, None)
                    self.connect(p)
                ui.button(action, "Try again", retry, small=True).pack()
        elif connected:
            tk.Label(action, text="Connected", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 9)).pack(pady=6)
        else:
            plus = ui.IconButton(action, "add", lambda p=plugin: self.connect(p), size=30)
            plus.pack()
            plus.connect_plugin = plugin.id  # tests find the button by this
        return tile


def open_plugins(app):
    return PluginsPage(app).window
