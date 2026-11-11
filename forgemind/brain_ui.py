"""Settings → AI brains: which AIs power Doxa, each one's key and monthly budget, and who works each team room."""
from __future__ import annotations

import tkinter as tk

from . import jarvis_ui as ui

MODES = [("auto", "Auto: local for quick things, cloud for code, plans, research and writing"),
         ("local", "Local only (free, private, works offline)"),
         ("openai", "OpenAI for everything"),
         ("claude", "Claude for everything"),
         ("gemini", "Gemini for everything"),
         ("kimi", "Kimi for everything"),
         ("opencode", "OpenCode Go for everything")]

# Keyed brains pasted here: (attribute on app, title, where to get a key, what it looks like)
KEYED = [("claude", "Claude", "console.anthropic.com → API keys", "starts with sk-ant-"),
         ("gemini", "Gemini", "aistudio.google.com → Get API key (free tier)", "starts with AIza or AQ."),
         ("kimi", "Kimi", "platform.moonshot.ai → API keys (add a little credit first)", "starts with sk-"),
         ("opencode", "OpenCode Go", "opencode.ai → sign in → Zen → subscribe to Go ($10/month) → copy your API key",
          "one key for Kimi, DeepSeek, Qwen and more")]
BUDGETS = [("Claude", "claude", "claude_monthly_cents"), ("OpenAI", "cloud", "cloud_monthly_cents"),
           ("Gemini", "gemini", "gemini_monthly_cents"), ("Kimi", "kimi", "kimi_monthly_cents"),
           ("OpenCode", "opencode", "opencode_monthly_cents")]
TEAM_ROOMS = [("research", "Research"), ("writers", "Writers' Room"), ("analyst", "Analyst")]
TEAM_CHOICES = [("auto", "Automatic (spread across connected AIs)"), ("claude", "Claude"), ("openai", "ChatGPT"),
                ("gemini", "Gemini"), ("kimi", "Kimi"), ("opencode", "OpenCode Go")]
from .team import NAMES
KEYED = [(key, NAMES.get(key, title), where, looks) for key, title, where, looks in KEYED]
TEAM_CHOICES = [(key, NAMES.get(key, title)) for key, title in TEAM_CHOICES]


def connected_label(brain) -> str:
    name = getattr(brain, "model_name", "") or brain.display_name
    if brain.provider_id == "claude":
        name = "Claude Opus 5.5"
    elif name == brain.display_name:
        name = "newest model your key offers"
    return "Connected · " + name


def open_brains(app):
    from .calendar_ui import _entry
    window, content = ui._panel(app, "AI brains",
                                "Doxa can think with several AIs. Quick things stay on your laptop for free; harder work "
                                "goes to Claude, ChatGPT, Gemini, Kimi or OpenCode Go, each with its own monthly budget. Phone numbers "
                                "and emails are masked before anything leaves this PC.", size="680x860")
    status = tk.StringVar()

    def row(title, state, good):
        frame = tk.Frame(content, bg=ui.BG)
        frame.pack(fill="x", pady=3)
        tk.Label(frame, text=title, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 10), width=19, anchor="w").pack(side="left")
        tk.Label(frame, text=state, bg=ui.BG, fg=ui.GOLD if good else ui.MUTED, font=(ui.BODY, 10), anchor="w",
                 justify="left", wraplength=480).pack(side="left", fill="x")

    ui._section(content, "BRAINS", top=4)
    row("Sage (Local)", (f"{app.engine.model_name.replace('.gguf', '')} on your GPU" if app.engine.loaded
                  else "Not loaded (Settings → choose a model)"), app.engine.loaded)
    row(NAMES['openai'], ("Connected · gpt-5.4-mini" if app.cloud.loaded else "Not connected (Tools → Autopilot & app connections)"),
        app.cloud.loaded)

    def keyed(attr, title, where, looks):
        brain = getattr(app, attr, None)
        if brain is None:
            return
        state = tk.StringVar()

        top = tk.Frame(content, bg=ui.BG)
        top.pack(fill="x", pady=(8, 2))
        tk.Label(top, text=title, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 10), width=22, anchor="w").pack(side="left")
        shown = tk.Label(top, textvariable=state, bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 10), anchor="w", justify="left",
                         wraplength=460)
        shown.pack(side="left", fill="x")

        def refresh():
            state.set(connected_label(brain) if brain.loaded else f"Not connected · key from {where} ({looks})")
            shown.configure(fg=ui.GOLD if brain.loaded else ui.MUTED)
        refresh()
        line = tk.Frame(content, bg=ui.BG)
        line.pack(fill="x")
        value = tk.StringVar()
        entry = _entry(line, value)
        entry.configure(show="•")
        entry.pack(side="left", fill="x", expand=True)

        def save_key():
            try:
                brain.save_key(value.get())
                value.set("")
                status.set(f"{title} connected. The key is stored encrypted for your Windows account only.")
            except ValueError as error:
                status.set(str(error))
            except OSError:
                status.set("Couldn't save the key.")
            refresh()
            app.model_label.configure(text=app.brain_label())

        def forget_key():
            brain.forget_key()
            status.set(f"{title} disconnected.")
            refresh()
            app.model_label.configure(text=app.brain_label())
        ui.button(line, "Save", save_key, active=True, small=True).pack(side="left", padx=(8, 0))
        ui.button(line, "Remove", forget_key, small=True).pack(side="left", padx=(6, 0))
    for item in KEYED:
        keyed(*item)

    ui._section(content, "HOW DOXA CHOOSES", top=18)
    mode = tk.StringVar(value=app.settings_data.brain_mode)
    for value, label in MODES:
        tk.Radiobutton(content, text=label, value=value, variable=mode, bg=ui.BG, fg=ui.TEXT, selectcolor=ui.SURFACE_2,
                       activebackground=ui.BG, activeforeground=ui.TEXT, font=(ui.BODY, 10), anchor="w").pack(fill="x")
    prefer = tk.StringVar(value=app.settings_data.cloud_preference)
    tk.Label(content, text="In Auto, try first:", bg=ui.BG, fg=ui.MUTED, font=(ui.BODY, 10), anchor="w").pack(fill="x", pady=(8, 0))
    for value, label in [("claude", "Claude"), ("openai", "OpenAI")]:
        tk.Radiobutton(content, text=label, value=value, variable=prefer, bg=ui.BG, fg=ui.TEXT, selectcolor=ui.SURFACE_2,
                       activebackground=ui.BG, activeforeground=ui.TEXT, font=(ui.BODY, 10), anchor="w").pack(fill="x")
    tk.Label(content, text="Any message can pick a brain: start it with claude:, gpt:, gemini:, kimi:, opencode: or local:",
             bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9), anchor="w").pack(fill="x", pady=(4, 0))

    ui._section(content, "WHO WORKS EACH TEAM ROOM", top=18)
    picks = {}
    labels = dict(TEAM_CHOICES)
    current = getattr(app.settings_data, "team_models", {}) or {}
    for room, title in TEAM_ROOMS:
        line = tk.Frame(content, bg=ui.BG)
        line.pack(fill="x", pady=2)
        tk.Label(line, text=title, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 10), width=14, anchor="w").pack(side="left")
        picks[room] = tk.StringVar(value=labels.get(current.get(room, "auto"), labels["auto"]))
        menu = tk.OptionMenu(line, picks[room], *[label for _v, label in TEAM_CHOICES])
        menu.configure(bg=ui.SURFACE_2, fg=ui.TEXT, activebackground=ui.SURFACE, activeforeground=ui.TEXT,
                       highlightthickness=0, relief="flat", borderwidth=0, font=(ui.BODY, 10), anchor="w", width=36,
                       padx=10, pady=4, indicatoron=False, cursor="hand2")
        menu["menu"].configure(bg=ui.SURFACE_2, fg=ui.TEXT, activebackground=ui.GOLD, activeforeground=ui.BG,
                               font=(ui.BODY, 10), borderwidth=0)
        menu.pack(side="left")
    tk.Label(content, text="Automatic: Gemini searches Google + Claude reads deeply for Research; Kimi + Claude split the "
                           "scripts (OpenCode Go's Kimi first when connected; each script tagged, so the Analyst can see whose hooks win); "
                           "Claude analyses.",
             bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9), anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(2, 0))

    prime_on = tk.BooleanVar(value=getattr(app.settings_data, "team_autopilot", True))
    tk.Checkbutton(content, text="Doxa keeps the team working (starts Research, Writers and Analyst when due; never posts "
                                 "or spends past the budgets below)", variable=prime_on, bg=ui.BG, fg=ui.TEXT,
                   selectcolor=ui.SURFACE_2, activebackground=ui.BG, activeforeground=ui.TEXT, font=(ui.BODY, 10),
                   anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(8, 0))
    hq_start = tk.BooleanVar(value=getattr(app.settings_data, "open_hq_on_start", True))
    tk.Checkbutton(content, text="Open Doxa on the 3D team (Doxa HQ)", variable=hq_start, bg=ui.BG, fg=ui.TEXT,
                   selectcolor=ui.SURFACE_2, activebackground=ui.BG, activeforeground=ui.TEXT, font=(ui.BODY, 10),
                   anchor="w").pack(fill="x", pady=(8, 0))

    ui._section(content, "MONTHLY BUDGETS (DOLLARS)", top=18)
    limits = {}
    for title, attr, field in BUDGETS:
        brain = getattr(app, attr, None)
        if brain is None:
            continue
        spend = brain.budget.summary()
        line = tk.Frame(content, bg=ui.BG)
        line.pack(fill="x", pady=2)
        tk.Label(line, text=title, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY_BOLD, 10), width=10, anchor="w").pack(side="left")
        limits[field] = (tk.StringVar(value=f"{getattr(app.settings_data, field) / 100:.0f}"), brain)
        _entry(line, limits[field][0]).pack(side="left")
        tk.Label(line, text=f"  ${spend['reserved_cents'] / 100:.2f} used in {spend['month']}", bg=ui.BG, fg=ui.MUTED,
                 font=(ui.BODY, 10)).pack(side="left")
    tk.Label(content, text="Claude: chat, research and tools. OpenAI: quick writing, hearing you and Doxa's voice. "
                           "Gemini: Google-search research (free tier first). Kimi: cheap strong drafts. OpenCode Go: flat $10/month, "
                           "so its number is the plan's included usage (about $60), not extra spending. Gemini/Kimi/"
                           "OpenCode spend is estimated from token counts.",
             bg=ui.BG, fg=ui.FAINT, font=(ui.BODY, 9), anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(2, 0))

    def save():
        cents = {}
        for field, (value, _brain) in limits.items():
            try:
                dollars = float(value.get().replace("$", "").strip())
                if not 0 <= dollars <= 500:
                    raise ValueError
            except ValueError:
                status.set("Use monthly budgets in dollars between 0 and 500.")
                return
            cents[field] = int(round(dollars * 100))
        app.settings_data.brain_mode = mode.get()
        app.settings_data.cloud_preference = prefer.get()
        by_label = {label: value for value, label in TEAM_CHOICES}
        app.settings_data.team_models = {room: by_label.get(var.get(), "auto") for room, var in picks.items()}
        app.settings_data.open_hq_on_start = bool(hq_start.get())
        app.settings_data.team_autopilot = bool(prime_on.get())
        for field, value in cents.items():
            setattr(app.settings_data, field, value)
            limits[field][1].budget.limit = value
        try:
            app.settings_data.save()
        except OSError:
            status.set("Couldn't save settings.")
            return
        app.model_label.configure(text=app.brain_label())
        if hasattr(app, "team_refresh"):
            app.team_refresh()
        status.set("Saved.")
    ui.button(content, "Save choices", save, active=True).pack(anchor="w", pady=(10, 6))
    tk.Label(content, textvariable=status, bg=ui.BG, fg=ui.GOLD, font=(ui.BODY, 10), anchor="w", justify="left",
             wraplength=560).pack(fill="x")
    return window
