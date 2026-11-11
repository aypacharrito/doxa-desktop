from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from forgemind import jarvis_ui, learning
from forgemind import workspace_ui
from forgemind.workspace import RunJournal
from forgemind.task_queue import TaskQueue
from forgemind.autopilot import Autopilot
from forgemind.autopilot_ui import open_autopilot
from forgemind.cloud_brain import CloudBrain, CloudBudget
from forgemind.extra_brains import GeminiBrain, KimiBrain, OpenCodeGoBrain
from forgemind.agent import DoxaTools
from forgemind.claude_brain import ClaudeBrain
from forgemind.brain import Brain
from forgemind.business_connections import BusinessConnections, business_reply
from forgemind.task_ui import open_tasks
from forgemind.voice import LocalVoice
from forgemind.local_tools import clock_reply
from forgemind.quick_actions import APPS, parse_command, launch_app, local_brief

from forgemind.adaptive import evolution_goal_from_chat, learning_items, should_search_web
from forgemind.connections import connect_github_repository
from forgemind.clips import ClipStudio
from forgemind.creator_ui import open_creator_panel, open_remote_panel, pump_uploads
from forgemind.computer_ui import open_computer_panel
from forgemind.browser_ui import open_browser_panel
from forgemind.browser_intent import browser_task_from_chat
from forgemind.calendar_connector import GoogleCalendar
from forgemind.calendar_intent import calendar_query_day, is_calendar_request
from forgemind import code_mode, code_mode_ui, products, products_ui, reels, skills, sites_ui, tickets, tickets_ui
from forgemind.code_mode import CodeRunner
from forgemind.screen_agent import ScreenJob
from forgemind.team import TeamRunner, TeamStore
from forgemind import knowledge
from forgemind.plugins import PluginStore
from forgemind import plugins_ui
from forgemind.calendar_ui import answer_day, calendar_now, offer_event, open_calendar_panel
from forgemind import pacifica, pacifica_ui
from forgemind.browser_agent import BrowserSession, OwnerFacts, make_planner
from forgemind.browser_control import BrowserController
from forgemind.phone_bridge import PhoneAccess, PhoneServer, PushNotifier, Tunnel, tunnel_token_get
from forgemind.phone_delegate import AppPhoneDelegate
from forgemind.phone_ui import open_phone_panel
from forgemind.computer import prepare_desktop_dpi
from forgemind.config import DEFAULT_MODEL_NAME, DEFAULT_MODEL_URL, Settings, app_data_dir
from forgemind.database import MemoryDB
from forgemind.engine import LocalEngine
from forgemind.providers import LlamaCppProvider, LocalInference, ModelUsage
from forgemind.growth import GrowthStore
from forgemind.growth_ui import open_growth_panel
from forgemind.indexer import chunk_text, index_files, index_folder
from forgemind.media import MediaLibrary
from forgemind.project_workspace import ProjectWorkspace
from forgemind.research_lab import ResearchLab
from forgemind.research_ui import open_research_panel, pump_research
from forgemind.self_evolve import EvolutionResult, SelfEvolver
from forgemind.training import TrainingLab
from forgemind.web import SearchResult, extract_urls, fetch_urls, research_web


BG = jarvis_ui.BG
PANEL = jarvis_ui.BG
PANEL_2 = jarvis_ui.SURFACE
TEXT = jarvis_ui.TEXT
MUTED = jarvis_ui.MUTED
ACCENT = jarvis_ui.GOLD
BLUE = jarvis_ui.GOLD
ERROR = jarvis_ui.ERROR


class ForgeMindApp(tk.Tk):
    def __init__(self) -> None:
        prepare_desktop_dpi()
        super().__init__()
        self.title("Doxa")
        self.geometry("1180x790")
        self.minsize(900, 650)
        self.configure(bg=BG)
        self.settings_data = Settings.load()
        self.db = MemoryDB()
        self.run_journal = RunJournal(app_data_dir() / 'activity.sqlite3')
        self.task_queue = TaskQueue(app_data_dir() / 'task-queue.sqlite3')
        self._migrate_oversized_history()
        self._load_starter_knowledge()
        self.engine = LocalEngine()
        self.model_usage = ModelUsage(app_data_dir() / 'model-usage.sqlite3')
        self.model_usage.recover()
        self.inference = LocalInference(LlamaCppProvider(self.engine), self.model_usage)
        self.cloud = CloudBrain(app_data_dir(), limit_cents=self.settings_data.cloud_monthly_cents)
        # Separate monthly allowances: $20 OpenAI + $20 Claude (the owner, 2026-11-05).
        self.claude = ClaudeBrain(app_data_dir(), CloudBudget(app_data_dir() / "claude-budget.sqlite3",
                                                              self.settings_data.claude_monthly_cents))
        # Gemini + Kimi (2026-11-08): more brains to spread the team's work; each has its own key and cap.
        self.gemini = GeminiBrain(app_data_dir(), CloudBudget(app_data_dir() / "gemini-budget.sqlite3",
                                                              self.settings_data.gemini_monthly_cents),
                                  model=self.settings_data.gemini_model, price=(0.3, 2.5))
        self.kimi = KimiBrain(app_data_dir(), CloudBudget(app_data_dir() / "kimi-budget.sqlite3",
                                                          self.settings_data.kimi_monthly_cents),
                              model=self.settings_data.kimi_model, price=(0.6, 2.5))
        self.opencode = OpenCodeGoBrain(app_data_dir(), CloudBudget(app_data_dir() / "opencode-budget.sqlite3",
                                                                    self.settings_data.opencode_monthly_cents),
                                        model=self.settings_data.opencode_model, price=(0.6, 2.5))
        self.brain = Brain(self.inference, self.cloud, self.claude, self.model_usage, LocalEngine.build_context)
        self.brain.extra = {"gemini": self.gemini, "kimi": self.kimi, "opencode": self.opencode}
        self.code_runner = CodeRunner(app_data_dir(), claude_key=self.claude.api_key, budget=self.claude.budget)
        self.screen_job = ScreenJob(self.claude, notify=lambda text: self.events.put(("status", "Screen: " + text[:120])),
                                    on_done=lambda job: self.events.put(("ui", lambda: self._post_screen(job))),
                                    protected_rect=self._doxa_rect)
        self.team = TeamStore(app_data_dir() / "team.json")
        from forgemind.opportunity_desk import OpportunityDesk
        self.opportunity_desk = OpportunityDesk(app_data_dir())
        self.team_runner = TeamRunner(
            self.team, brain_for=self._team_brain, notify=lambda text: self.events.put(("status", text[:160])),
            on_change=lambda: self.events.put(("ui", lambda: getattr(self, "team_refresh", lambda: None)())),
            knowledge_add=lambda title, lesson, tags, source: knowledge.add(title, lesson, tags, source),
            rules=knowledge.core_rules, choices=lambda: self.settings_data.team_models)
        from forgemind.team import Prime, PRIME_EVERY
        self.prime = Prime(self.team, self.team_runner, enabled=lambda: self.settings_data.team_autopilot,
                           notify=lambda text: self.events.put(("status", text[:160])))
        self._prime_every = PRIME_EVERY
        # Research Lab: researches upgrades to Doxa itself; each becomes a Code mode prompt that waits for the owner's OK.
        from forgemind.upgrades import UpgradeLab, UpgradeStore
        self.upgrades = UpgradeLab(
            UpgradeStore(app_data_dir() / "upgrades.json"), brains=self._team_brain,
            build=lambda task: self.brain.tools.execute("build_doxa_capability", {"task": task}),
            notify=lambda text: self.events.put(("status", text[:160])),
            auto=lambda: self.settings_data.doxa_approves_upgrades, can_build=self._code_free)
        # Warehouses: one free research bot per money line, taking turns all day (forgemind/warehouses.py).
        from forgemind.warehouses import WarehouseBots
        self.warehouses = WarehouseBots(app_data_dir() / "warehouses.json", brains=self._free_brains,
                                        propose=self.upgrades.store.add)
        # A chat box on every HQ island: ask anything, queue research for its bot, or queue a build (forgemind/island_chat.py)
        from forgemind.island_chat import IslandChat
        from forgemind.hq_data import ISLANDS as _HQ_ISLANDS, island_context
        self.island_chat = IslandChat(
            app_data_dir() / "island-chats.json", brain_for=self._island_brain,
            islands={"prime": ("Command", "Doxa", "Runs everything and sends every AI to work."),
                     **{k: (n, w, a) for k, n, w, a in _HQ_ISLANDS}},
            context=lambda key: island_context(self, key),
            queue_research=lambda key, question: self.warehouses.ask(key, question),
            queue_build=lambda key, title, prompt: self.upgrades.queue_david(title, prompt, island=key,
                                                                              source="the owner (island chat)"))
        # Doxa's own "Vercel": publish Doxa Sites to Cloudflare's free hosting (forgemind/publish.py)
        from forgemind.publish import Publisher
        self.publisher = Publisher()
        # HQ robot art drawn by ChatGPT's image model when the owner presses "Make robot art" (forgemind/hq_art.py)
        from forgemind.hq_art import ArtMaker
        self.hq_art = ArtMaker(self._openai_key, self.cloud.budget, self.team.art_dir,
                               notify=lambda text: self.events.put(("status", text[:160])))
        # Trading arena: paper bots that die if they don't make money (forgemind/trading_arena.py). Paper only.
        from forgemind.trading_arena import TradingArena
        self.arena = TradingArena(app_data_dir() / "trading-arena.json",
                                  notify=lambda text: self.events.put(("status", text[:160])))
        self._bots_running = False
        self.plugins = PluginStore(app_data_dir() / "plugins.json")
        self.brain.plugins = self.plugins  # Claude in chat can use connected apps (Gmail, Slack, … via MCP)
        self.mode = self.settings_data.lane if self.settings_data.lane in ("chat", "work") else "chat"
        self.brain.tools = DoxaTools(self)  # Claude in chat can use web search and every Tools item
        self.brain.on_status = lambda message: self.events.put(("status", message))
        self.products = products.HuntStore(app_data_dir())  # Product hunter history + the owner's verdicts
        self._hunting = False
        self.business_connections = BusinessConnections(app_data_dir())
        self.autopilot = Autopilot(self)
        self.evolver = SelfEvolver(Path(__file__).parent)
        self.training_lab = TrainingLab()
        self.project_workspace = ProjectWorkspace()
        self.media_library = MediaLibrary()
        self.growth = GrowthStore()
        self.growth.recover(self.evolver)
        self.research_lab = ResearchLab()
        self.research_lab.recover()
        self._research_session = None
        self._research_reported = {run["id"] for run in self.research_lab.runs()}
        self._growth_task_id = None
        self._growth_restart_pending = False
        self._last_activity = time.monotonic()
        self._next_growth_plan = 0.0
        self.clip_studio = ClipStudio(self.media_library)
        self._upload_running = False
        self._creator_operations = 0
        self._computer_controls = None
        self._computer_panel = None
        self._browser_task = None
        self._browser_panel = None
        self.calendar = GoogleCalendar()  # tokens: Windows Credential Manager only
        self._calendar_panel = None
        self._calendar_card = None
        self._closing = False
        self.events: queue.Queue[tuple] = queue.Queue()
        self.voice = LocalVoice(self.events.put)
        self.voice.followup = bool(self.settings_data.voice_conversation)
        from forgemind.cloud_voice import CloudVoice
        self.cloud_voice = CloudVoice(self.cloud)
        self.cloud_voice.enabled = bool(self.settings_data.cloud_voice)
        # Natural voice + accurate hearing through OpenAI; the Windows voice / local transcript when unavailable.
        self.voice.tts = lambda text, stop: self.cloud_voice.speak(text, stop)
        self.voice.refine = lambda audio: self.cloud_voice.transcribe(audio)
        self.voice.device = self.settings_data.voice_device or None
        browser_root = app_data_dir() / "browser"
        self.phone_access = PhoneAccess(app_data_dir() / "phone.json")
        self.notifier = PushNotifier(self.phone_access)
        self.browser_controller = BrowserController(
            lambda: BrowserSession(browser_root / "browser-profile"),
            lambda: make_planner(self.brain, self.settings_data, self.engine),  # Claude/OpenAI if connected
            facts=OwnerFacts(browser_root / "owner-facts.json"),
            search=lambda query: __import__("forgemind.web", fromlist=["search_web"]).search_web(query, max_results=5),
            root=browser_root / "runs",
            on_finish=self._browser_finished,
            on_request=self._browser_needs_owner)
        self.phone_server = PhoneServer(AppPhoneDelegate(self), self.phone_access)
        self.phone_tunnel = None
        self._phone_panel = None
        self._start_phone_access()
        self._cancel_answer = threading.Event()
        self._voice_turn = False
        self._voice_dispatch = False
        self.busy = False
        self.evolving = False
        self._stop_evolution = threading.Event()
        self._answer_parts: list[str] = []
        self._last_web: list[SearchResult] = []
        self._memory_ids: list[int] = []
        self._resume_checked = False
        self._build_style()
        self._build_ui()
        self.bind_all("<KeyPress>", lambda _event: self._touch_activity(), add="+")
        self.bind_all("<ButtonPress>", lambda _event: self._touch_activity(), add="+")
        self.refresh_all()
        self.after(50, self._drain_events)
        if not self.settings_data.voice_quiet_v135:   # 2026-11-09: "Doxa responds randomly": always-on listening off once
            self.settings_data.voice_quiet_v135 = True
            self.settings_data.voice_enabled = False
            try:
                self.settings_data.save()
            except OSError:
                pass
        if self.settings_data.voice_enabled:
            self.after(1500, self.voice.enable)  # the owner turned always-on listening on in Voice check
        self.after(3000, lambda: pump_uploads(self))
        self.after(3000, self._growth_tick)
        self.after(10000, self.autopilot.tick)
        self.after(90000, self._product_tick)
        self.after(500, lambda: pump_research(self))
        self.after(5000, self._prime_tick)  # start supervision promptly; paid jobs stay budgeted
        if getattr(self.settings_data, "open_hq_on_start", True):
            self.after(800, self.show_team_hq)
        if self.settings_data.local_learning_enabled:
            self.after(1500, lambda: learning.when_ready(self))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.settings_data.model_path and Path(self.settings_data.model_path).is_file():
            self._load_model(self.settings_data.model_path)
        else:
            self._welcome()

    def _load_starter_knowledge(self) -> None:
        starter = Path(__file__).parent / "starter_knowledge"
        if starter.is_dir():
            index_folder(self.db, starter)

    def _store_knowledge_text(self, text: str, label: str) -> Path:
        imports = app_data_dir() / "imports"
        imports.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safe_label = "".join(char if char.isalnum() or char in "-_" else "-" for char in label).strip("-")
        path = imports / f"{stamp}-{safe_label or 'pasted-knowledge'}.md"
        path.write_text(text, encoding="utf-8")
        stat = path.stat()
        self.db.replace_document(path, stat.st_mtime_ns, stat.st_size, chunk_text(text))
        return path

    def _migrate_oversized_history(self) -> None:
        for row in self.db.long_messages():
            path = self._store_knowledge_text(row["content"], f"chat-message-{row['id']}")
            self.db.replace_message_content(
                row["id"],
                f"[Oversized {row['role']} message imported as searchable knowledge: {path.name}]",
            )

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        jarvis_ui.style_ttk(self)  # one dark-gold theme for every panel

    def _build_ui(self) -> None:
        jarvis_ui.build(self)

    def _welcome(self) -> None:
        self._set_status("Choose your local GGUF model in Settings to begin.")

    def show_conversation(self):
        self.input.focus_set()

    def show_home(self):
        if self.busy:
            self._set_status("Your current task is still running. Stop it before changing views.")
            return
        self.set_mode(self.settings_data.lane if self.settings_data.lane in ("chat", "work") else "chat")
        self.db.new_chat()  # New chat really starts over: Doxa forgets this conversation's context
        jarvis_ui.show_hero(self)
        jarvis_ui.set_view(self, "Home")
        self.refresh_all()

    def show_computer(self):
        return open_computer_panel(self)

    def show_browser(self, task=""):
        return open_browser_panel(self, task)

    def _browser_needs_owner(self, pending):
        title = {"ask": "Doxa has a question", "confirm": "Doxa needs your OK",
                 "hand_off": "Your turn at the PC"}.get(pending["kind"], "Doxa needs you")
        body = pending["text"] or pending["title"]
        self.notifier.send(title, body, {"screen": "task", "request": pending["id"]})

    def _browser_finished(self, result):
        self.events.put(("browser_done", result))
        status = (result or {}).get("status")
        title = "Done" if status == "completed" else "Browser task stopped"
        self.notifier.send(f"Doxa · {title}", (result or {}).get("message", "")[:180], {"screen": "task"})

    def start_reels(self, text: str, links: list[str], source: str = "YOU") -> None:
        """Download each link, transcribe it on this PC and post the transcript in chat."""
        question = reels.question_about(text)
        count = f"{len(links)} videos" if len(links) > 1 else "that video"
        if all(reels.is_local(item) for item in links):
            note = (f"Transcribing {count} on this PC now. I'll post each transcript here; "
                    "about 10-30 seconds per minute of video.")
        else:
            note = (f"Getting {count} now: I'll save it as MP4, transcribe it on this PC and post the transcript "
                    "here. Short reels take about 15-40 seconds" + (" each, one after another." if len(links) > 1
                                                                    else "."))
        self.db.add_message("user", text)
        self.db.add_message("assistant", note)
        self._append("user", source + "\n")
        self._append("body", text + "\n\n")
        self._append("assistant", "DOXA\n")
        self._append("body", note + "\n\n")
        self.refresh_all()

        def work():
            total = len(links)
            for number, url in enumerate(links, 1):
                prefix = f"Video {number} of {total}: " if total > 1 else ""
                try:
                    result = reels.process(url, self.media_library,
                                           progress=lambda message, p=prefix: self.events.put(("status", p + message)))
                    reply = reels.chat_summary(result)
                except reels.ReelError as exc:
                    reply = f"{url}\n{exc}"
                except Exception as exc:  # keep Doxa running whatever a site returns
                    reply = f"{url}\nSomething went wrong with that video: {exc}"
                self.events.put(("ui", lambda reply=reply: self._post_reel(reply)))
            if question:
                self.events.put(("ui", lambda: self._ask_about_reels(question)))
        threading.Thread(target=work, daemon=True, name="doxa-reels").start()

    def _post_reel(self, reply: str) -> None:
        self.db.add_message("assistant", reply)
        self._append("assistant", "DOXA\n")
        self._append("body", reply + "\n\n")
        self._set_status("Reel transcript ready")
        self.refresh_all()

    def _ask_about_reels(self, question: str) -> None:
        """The owner asked something besides the link: answer it now that the transcript is in chat."""
        if self.busy or self.input.get("1.0", "end").strip():
            self._set_status("Transcript ready · ask your question about it now")
            return
        self.input.insert("1.0", question + " (about the reel transcript above)")
        self.send()

    def offer_quote(self, text: str, draft, source: str = "YOU") -> None:
        """Pacifica quote request: show the confirmation card; send only when the owner presses Send."""
        if draft.refused:
            note = draft.refused
        elif not pacifica.is_configured(self.settings_data.pacifica_url):
            note = ("I can start that quote request in Pacifica once it's connected. Open Settings → "
                    "Pacifica connection and add your CRM address and integration token.")
        else:
            note = ("Here's the quote request for Pacifica. Check the card and press Send to Pacifica — "
                    "I won't send it until you do.")
        self.db.add_message("user", text)
        self.db.add_message("assistant", note)
        self._append("user", source + "\n")
        self._append("body", text + "\n\n")
        self._append("assistant", "DOXA\n")
        self._append("body", note + "\n\n")
        if self._voice_turn and self.voice.enabled:
            self.voice.speak(note if draft.refused else "Check the quote request card, then press Send.")
        self.refresh_all()
        if draft.refused:
            return
        if not pacifica.is_configured(self.settings_data.pacifica_url):
            pacifica_ui.open_connection(self)
            return
        pacifica_ui.confirm_quote(self, draft, self._send_quote)

    def _send_quote(self, draft) -> None:
        """Runs after the owner pressed Send on the card. The HTTP call is on a worker thread."""
        client = pacifica.PacificaClient(self.settings_data.pacifica_url)
        self._set_status("Sending the quote request to Pacifica…")

        def work():
            try:
                client.create_quote_request(draft)
                self.events.put(("pacifica_done", True,
                                 f"Done — the quote request for {draft.customer_name} is in Pacifica for you to review."))
            except pacifica.PacificaError as exc:
                self.events.put(("pacifica_done", False, f"Pacifica: {exc} Nothing was created."))
        threading.Thread(target=work, daemon=True, name="pacifica-quote").start()

    def show_phone(self):
        return open_phone_panel(self)

    def show_calendar(self):
        return open_calendar_panel(self)

    def _start_phone_access(self):
        """Resume phone access on launch if the owner turned it on."""
        if not self.phone_access.data.get("enabled"):
            return
        try:
            self.phone_server.start()
            token = tunnel_token_get() if self.phone_access.data.get("use_named_tunnel") else ""
            if token and self.phone_access.data.get("public_url"):
                self.phone_tunnel = Tunnel(self.phone_access.port)
                self.phone_tunnel.start_named(token, self.phone_access.data["public_url"])
            elif not self.phone_access.data.get('use_named_tunnel'):
                self.phone_tunnel = Tunnel(self.phone_access.port)
                self.phone_tunnel.start_quick()
                self.events.put(('status', 'Phone connection restarting. Quick-link address changes; use Phone access for the current link.'))
        except Exception as exc:  # phone access must never stop Doxa from opening
            self.events.put(("status", f"Phone access needs attention: {exc}"))

    def show_skills(self):
        return jarvis_ui.open_skills(self)

    def show_tools(self):
        return jarvis_ui.open_tools(self, self.tool_groups())

    def tool_groups(self):
        return [
            # Browsing, research, opening apps, files and code all happen from chat now (the owner 2026-11-06:
            # "doxa should just do all this from the jump in chat"); these are the screens chat can't replace.
            ("Make things", [
                ("Product hunter", "Winning products to test, with hooks, suppliers and profit math.",
                 self.show_product_hunter),
                ("Website builder", "A site for a local business from footage you film.", self.show_website_builder),
                ("Traffic ticket", "Photo of a CA ticket → contest-by-mail paperwork (TR-205).",
                 self.show_ticket_helper),
                ("Media library", "Your videos, reels, transcripts and frames.", self.open_media_library)]),
            ("Your day", [
                ("Daily brief", "Your priorities and what changed.", self.show_local_brief),
                ("Autopilot", "Daily leads and growth reviews on your cloud budget.", self.show_autopilot)]),
            ("Doxa", [
                ("Login vault", "Encrypted local site logins; passwords stay out of chat.", self.show_login_vault),
                ("AI brains", "Claude, ChatGPT and the local model; budgets.", self.show_brains),
                ("Voice", "Your mic, the voice, and what Doxa hears.", self.show_voice_check),
                ("Phone", "Doxa, Code mode and your screen on your phone.", self.show_phone)]),
        ]

    def run_skill(self, key: str) -> None:
        """A checklist skill answers instantly; a prompt skill fills the message box for the owner to finish."""
        skill = skills.get(key)
        if skill.kind == "answer":
            if self.busy:
                self._set_status("Finish or stop the current answer first.")
                return
            self.db.add_message("user", skill.title)
            self.db.add_message("assistant", skill.text)
            self._append("user", "YOU\n")
            self._append("body", skill.title + "\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", skill.text + "\n\n")
            self.refresh_all()
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", skill.text)
        self.input.focus_set()
        start = skill.text.find("[")
        if start >= 0:  # select the first [placeholder] so typing replaces it
            end = skill.text.find("]", start) + 1
            self.input.tag_remove("sel", "1.0", "end")
            self.input.tag_add("sel", f"1.0+{start}c", f"1.0+{end}c")
            self.input.mark_set("insert", f"1.0+{end}c")
        self.input.event_generate("<KeyRelease>")  # hide the "Ask Doxa anything…" hint
        self._set_status(f"{skill.title}: fill in the [brackets], then press Send.")

    def show_quick_actions(self):
        jarvis_ui.tools_window(self, "Quick actions", [
            ("Open " + label, lambda name=name: self.run_quick_action(name)) for name, label in APPS.items()
        ] + [("Morning brief", self.show_local_brief), ("Browser task…", self.show_browser),
              ("Google Calendar…", self.show_calendar),
              ("Phone access…", self.show_phone),
              ("Screen control…", self.show_computer)])

    def run_quick_action(self, name):
        if self.busy:
            self._set_status("Finish or stop the current task before opening another app.")
            return
        run_id = self.run_journal.start("Open " + APPS[name])
        try:
            reply = launch_app(name)
            self.run_journal.finish(run_id, "complete", reply)
            self._set_status(reply)
        except (OSError, ValueError) as exc:
            reply = str(exc)
            self.run_journal.finish(run_id, "error", reply)
            self._set_status(reply, error=True)
        return reply

    def show_local_brief(self, user_text: str = ""):
        """Today's events are read off the Tk thread so the window never waits on Google."""
        voice = self._voice_turn
        if not self.calendar.connected():
            return self._render_brief(None, user_text, voice)
        self._set_status("Reading today's calendar…")
        day = calendar_now(self).date()

        def work():
            try:
                events = self.calendar.events_on(day)
            except Exception as exc:
                events = str(exc)
            self.events.put(("ui", lambda: self._render_brief(events, user_text, voice)))
        threading.Thread(target=work, daemon=True).start()
        return None

    def _render_brief(self, calendar_events, user_text: str = "", voice: bool = False):
        rows = self.run_journal.recent(100)
        for row in rows:
            row["local_date"] = datetime.fromisoformat(row["started_at"]).astimezone().date().isoformat()
        reply = local_brief(self.settings_data, self.db.counts(), rows, today=datetime.now().date().isoformat(),
                            calendar=calendar_events)
        self._append("assistant", "YOUR BRIEF\n")
        self._append("body", reply + "\n\n")
        if user_text:
            self.db.add_message("user", user_text)
            self.db.add_message("assistant", reply)
            if voice and self.voice.enabled:
                self.voice.speak(reply.split("\n\n")[0])
            self.refresh_all()
        self._set_status("Ready")
        return reply

    def show_history(self):
        if self.busy:
            self._set_status("Finish or stop the current answer before opening saved history.")
            return
        jarvis_ui.show_chat(self)
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        for item in self.db.recent_messages(30):
            self._append("user" if item["role"] == "user" else "assistant",
                         "YOU\n" if item["role"] == "user" else "DOXA\n")
            self._append("body", item["content"] + "\n\n")

    def show_memory(self):
        workspace_ui.open_memory(self)

    def show_research(self):
        jarvis_ui.tools_window(self, "Research", [
            ("Start ongoing local model experiments", lambda: learning.start(self)),
            ("Pause model experiments", lambda: learning.pause(self)),
            ("Ask a research question", self.prepare_research),
            ("Neural Research Lab", lambda: open_research_panel(self)),
            ("Reviewed training examples", self.open_training_lab),
            ("Project workspace", self.open_project_workspace),
            ("Media library", self.open_media_library)])

    def show_activity(self):
        workspace_ui.open_activity(self)

    def show_tasks(self):
        return open_tasks(self)

    def show_autopilot(self):
        return open_autopilot(self)

    def show_code_mode(self, task: str = "", folder: str = ""):
        """Code lives in the main window now (Chat | Code switch at the top)."""
        self.set_mode("code")
        if folder:
            self.code_folder_var.set(folder)
        if task:
            self.input.delete("1.0", "end")
            self.input.insert("1.0", task)
        self.input.focus_set()

    def open_chat(self, chat_id: int) -> None:
        """Show a past chat from the sidebar (read-only; typing starts in the current chat)."""
        messages = self.db.chat_messages(chat_id)
        self.set_mode(self.mode if self.mode in ("chat", "work") else self.settings_data.lane)
        jarvis_ui.show_chat(self)
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._append("muted", "Earlier chat · new messages go to your current chat (New chat starts fresh)\n\n")
        for message in messages:
            self._append("user" if message["role"] == "user" else "assistant",
                         "YOU\n" if message["role"] == "user" else "DOXA\n")
            self._append("body", message["content"] + "\n\n")

    def set_mode(self, mode: str) -> None:
        """Chat | Work | Code switch: one message box. Chat and Work share the conversation (Chat = the model on this PC,
        Work = the paid AIs, 1.38); Code shows Code mode."""
        if mode == "team":
            return self.show_team_hq()  # old shortcuts still open the independent HQ
        self.mode = mode if mode in ("code", "work") else "chat"
        if self.mode in ("chat", "work") and self.settings_data.lane != self.mode:
            self.settings_data.lane = self.mode
            try:
                self.settings_data.save()
            except OSError:
                pass
        frames = {"conversation": self._conversation, "code": self.code_frame, "team": getattr(self, "team_frame", None)}
        showing = "code" if self.mode == "code" else "conversation"
        for name, frame in frames.items():
            if frame is not None and name != showing:
                frame.grid_remove()
        frames[showing].grid()
        if self.mode == "team" and getattr(self, "team_refresh", None):
            self.team_refresh()
            if getattr(self, "team_show_3d", None):  # the Team tab is the 3D floor (embedded), classic view on request
                self.team_show_3d()
        jarvis_ui.paint_mode(self, self.mode)

    def show_plugins(self):
        return plugins_ui.open_plugins(self)

    def show_login_vault(self):
        from forgemind.login_vault_ui import open_vault
        return open_vault(self)

    def show_team_hq(self):
        from forgemind.hq_window import open_hq_window
        try:
            self.team.ensure_art_folder()  # Documents\Doxa Team\characters + the Higgsfield prompts
        except OSError:
            pass
        return open_hq_window(self)

    def start_code_job(self, text: str, task: str, folder=None, engine: str = "auto", source: str = "YOU",
                       post: bool = True, follow_up=None) -> str:
        """Code mode (the owner 2026-11-06: full access). Starts Codex / Claude Code in the background; steps go to the
        status line and the Code mode panel, the result is posted in chat. Raises ValueError when it can't start."""
        engine = engine if engine in ("codex", "claude") else self.settings_data.code_engine
        folder = str(folder) if folder else None  # callers may pass a Path (build_doxa_capability did)
        try:
            job = self.code_runner.start(task, folder, engine, self.settings_data.code_job_max_usd,
                                         on_step=lambda step: self.events.put(("status", "Code mode: " + step[:120])),
                                         on_done=lambda job: self.events.put(("ui", lambda: self._post_code(job))),
                                         follow_up=follow_up)
            plan = "on your " + ("ChatGPT" if job.engine == "codex" else "Claude") + " plan" if job.subscription \
                else "on Doxa's Claude key"
            how = f"Continuing your {job.name} chat" if job.continued else f"Code mode started with {job.name}"
            note = (f"{how} ({plan}) in {job.folder}. It has full access and works on its own; I'll post the result "
                    "here when it's done (Tools → Code mode and the phone show each step and have Stop).")
        except ValueError as exc:
            if not post:
                raise
            note = str(exc)
        if post:
            self.db.add_message("user", text)
            self.db.add_message("assistant", note)
            self._append("user", source + "\n")
            self._append("body", text + "\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", note + "\n\n")
            self.refresh_all()
        return note

    def _hq_url(self):
        """Doxa HQ's local address with a private per-start key (None when the local server can't start)."""
        import secrets
        if not getattr(self.phone_server, "running", False):
            try:
                self.phone_server.start(port=self.phone_access.port)
            except Exception as exc:
                self._set_status(f"Doxa HQ needs Doxa's local server: {exc}")
                return None
        if not getattr(self, "_hq_key", None):
            self._hq_key = secrets.token_urlsafe(24)
            self.phone_access.local_keys.add(self._hq_key)
        return f"http://127.0.0.1:{self.phone_access.port}/hq.html#k={self._hq_key}"

    def embed_hq(self, host, on_state):
        """Doxa HQ inside the Team tab (forgemind/embed_web.py); started once per run."""
        from forgemind.embed_web import EmbeddedPage, profile_dir
        page = getattr(self, "_hq_page", None)
        if page is not None and (page.embedded or page.process is not None):
            return page
        url = self._hq_url()
        if not url:
            on_state("Doxa's local server didn't start, so the 3D team can't load.")
            return None
        self._hq_page = EmbeddedPage(host, url, profile_dir(app_data_dir()), on_state=on_state)
        self._hq_page.start()
        return self._hq_page

    def open_hq(self):
        """Doxa HQ: the team as a 3D floor (phone_web/hq.html), in its own app window (Edge app mode)."""
        import shutil
        import subprocess
        url = self._hq_url()
        if not url:
            return
        edge = shutil.which("msedge") or next((p for p in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).is_file()), None)
        try:
            if edge:
                subprocess.Popen([edge, f"--app={url}", "--window-size=1400,880"])
            else:
                import webbrowser
                webbrowser.open(url)
        except OSError as exc:
            self._set_status(f"Couldn't open Doxa HQ: {exc}")

    def _prime_tick(self):
        try:
            self.prime.tick()
            self.opportunity_desk.tick(self)
            from forgemind.self_build import maybe_build
            threading.Thread(target=lambda: maybe_build(self), daemon=True, name='doxa-capability-check').start()
            if self.settings_data.team_autopilot and self.upgrades.due() and self._team_brain():
                self.upgrades.start()  # once a week: fresh upgrade ideas wait in the Research Lab for approval
            if not self._bots_running:  # off the Tk thread (the bots and the reviewer only start threads, but stay safe)
                self._bots_running = True
                threading.Thread(target=self._bots_tick, daemon=True, name="doxa-bots-tick").start()
        except Exception as exc:  # Prime must never take Doxa down
            self._set_status(f"Doxa: {exc}")
        finally:
            self.after(self._prime_every * 1000, self._prime_tick)

    def _bots_tick(self):
        try:
            if self.settings_data.warehouse_bots:
                self.warehouses.tick()
            self.upgrades.david_tick()   # the owner's own requests from island chats build first
            self.upgrades.review_tick()
            self._approve_scripts()
            self.arena.tick()
            self.hq_art.auto_tick()    # the 3D figures, once, after the portraits (the owner asked for them)
            self._daily_briefing()
        except Exception as exc:
            self.events.put(("status", f"Doxa bots: {str(exc)[:120]}"))
        finally:
            self._bots_running = False

    def _island_brain(self, private: bool = False):
        """Island chats: the strongest connected cloud brain (Claude first); "private:" messages only the local model."""
        from forgemind.warehouses import LocalBotBrain
        if private:
            return LocalBotBrain(self.engine) if self.engine.loaded else None
        clouds = self.brain.clouds(self.settings_data)
        if clouds:
            return clouds[0]
        return next(iter(self._free_brains().values()), None)

    def _free_brains(self):
        """Brains that cost the owner nothing extra: OpenCode Go (his flat $10/month plan's included usage), Gemini's free
        tier (inside its own $5 safety cap) and the local model on his GPU (only for private warehouses like Web Studio).
        GitHub's free models were retired by GitHub on 2026-07-30."""
        brains = {name: brain for name, brain in (("opencode", self.opencode), ("gemini", self.gemini)) if brain.loaded}
        if self.engine.loaded:
            from forgemind.warehouses import LocalBotBrain
            brains["local"] = LocalBotBrain(self.engine)
        return brains

    def _daily_briefing(self):
        """Every morning (after 7 AM): the best findings from every island's research bot, posted in chat (so the
        phone has it too) and saved in Documents\\Doxa Notes. Keeps the owner up to date without asking."""
        now = datetime.now()
        state = self.warehouses.data
        if now.hour < 7 or state.get("briefing_day") == now.strftime("%Y-%m-%d"):
            return
        body = self.warehouses.digest(since=time.time() - 24 * 3600)
        state["briefing_day"] = now.strftime("%Y-%m-%d")
        self.warehouses.save()
        if not body:
            return
        arena = self.arena.data.get("status", "")
        text = f"Good morning. Your {now:%A} briefing from the team:\n{body}" + (f"\n\nTrading arena: {arena}" if arena else "")
        try:
            folder = Path.home() / "Documents" / "Doxa Notes"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"Daily briefing {now:%Y-%m-%d}.md").write_text(text, "utf-8")
        except OSError:
            pass

        def post():
            self.db.add_message("assistant", text)
            self._append("assistant", "DOXA · BRIEFING\n")
            self._append("body", text + "\n\n")
            try:
                self.notifier.send("Doxa briefing", body.split("\n")[0][:120])
            except Exception:
                pass
        self.events.put(("ui", post))

    def _approve_scripts(self):
        """Doxa approves the team's scripts itself (the owner 2026-11-09: "remove my desk, I want Doxa to approve
        everything"). They're drafts for the owner to film; nothing is posted."""
        if not self.settings_data.doxa_approves_upgrades or not self.team.campaign():
            return
        approved = 0
        for item in self.team.items(stage="waiting"):
            try:
                self.team.decide(item["id"], True, "Approved by Doxa")
                approved += 1
            except ValueError:
                pass
        if approved:
            self.events.put(("status", f"Doxa approved {approved} script(s): ready to film."))
            self.events.put(("ui", lambda: getattr(self, "team_refresh", lambda: None)()))

    def show_qr_codes(self, source="YOU"):
        """Both QR codes, every time: download the app + pair Doxa with the phone (forgemind/qr_codes.py)."""
        from forgemind.qr_codes import make_both
        try:
            base = (self.phone_access.data.get("public_url", "") if self.phone_access.data.get("use_named_tunnel")
                    else getattr(self.phone_tunnel, "url", "") or "")
            both = make_both(self.phone_access, base)
        except Exception as exc:
            self._set_status(f"QR codes: {exc}")
            return None
        window = tk.Toplevel(self)
        window.title("Doxa · your two QR codes")
        window.configure(bg="#06080C")
        window._images = []
        for column, (title, png, link) in enumerate((("1. Download the Doxa app", both["app_png"], both["app_url"]),
                                                    ("2. Pair Doxa with your phone", both["pair_png"], "Scan with the Doxa app"))):
            image = tk.PhotoImage(file=png)
            scale = max(1, image.width() // 300)
            image = image.subsample(scale, scale)
            window._images.append(image)
            tk.Label(window, text=title, fg="#E8C26A", bg="#06080C", font=("Segoe UI", 13, "bold")).grid(row=0, column=column, padx=24, pady=(18, 6))
            tk.Label(window, image=image, bg="#06080C").grid(row=1, column=column, padx=24)
            tk.Label(window, text=link if column == 1 else "Phone camera → open the link → install", fg="#9a958c",
                     bg="#06080C", font=("Segoe UI", 9), wraplength=300).grid(row=2, column=column, padx=24, pady=(6, 18))
        if both["rotated"]:
            tk.Label(window, text="A new pairing code was made: phones paired before need to scan code 2.", fg="#e5383b",
                     bg="#06080C", font=("Segoe UI", 9)).grid(row=3, column=0, columnspan=2, pady=(0, 14))
        return both

    def _openai_key(self) -> str:
        from forgemind.windows_credentials import windows_key
        path = app_data_dir() / "openai-key.dpapi"
        if not path.is_file():
            raise ValueError("Connect ChatGPT (OpenAI) in Settings → AI brains first.")
        return windows_key(path.read_bytes(), False).decode("utf-8")

    def _code_free(self):
        job = getattr(self.code_runner, "job", None)
        return not (job and getattr(job, "status", "") == "running")

    def _team_brain(self):
        """Every connected cloud brain; team.STAFF decides who works which room."""
        return {name: brain for name, brain in (("claude", self.claude), ("openai", self.cloud),
                                                ("gemini", self.gemini), ("kimi", self.kimi),
                                                ("opencode", self.opencode)) if brain.loaded}

    def cloud_brains(self):
        return [b for b in (self.claude, self.openai_brain, self.gemini, self.kimi, self.opencode) if b.loaded]

    def _doxa_rect(self):
        """Doxa's own window on screen, which screen control never clicks (None when minimized)."""
        try:
            if self.state() == "iconic":
                return None
            x, y = self.winfo_rootx(), self.winfo_rooty()
            return (x, y, x + self.winfo_width(), y + self.winfo_height())
        except Exception:
            return None

    def start_screen_task(self, task: str, source: str = "YOU", post: bool = True) -> str:
        """Claude uses the laptop's mouse and keyboard for `task` (forgemind/screen_agent.py)."""
        try:
            self.screen_job.start(task)
            note = ("Working on your laptop screen now. I'll post what happened here. Moving the mouse or typing "
                    "pauses me; Ctrl+Alt+F12 stops me. You can watch from your phone's Screen view.")
        except ValueError as exc:
            if not post:
                raise
            note = str(exc)
        if post:
            self.db.add_message("user", task)
            self.db.add_message("assistant", note)
            self._append("user", source + "\n")
            self._append("body", task + "\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", note + "\n\n")
            self.refresh_all()
        return note

    def _post_screen(self, job) -> None:
        reply = job.report()
        self.db.add_message("assistant", reply)
        self._append("assistant", "DOXA\n")
        self._append("body", reply + "\n\n")
        self._set_status("Screen control: " + (job.result or {}).get("status", "done"))
        try:
            self.notifier.send("Doxa · screen control", reply[:180], {"screen": "chat"})
        except Exception:
            pass
        self.refresh_all()

    def _post_code(self, job) -> None:
        reply = job.report()
        try:  # phone notification (Doxa phone app with push registered)
            self.notifier.send(f"Doxa · Code mode {job.status}", (job.summary or reply)[:180], {"screen": "code"})
        except Exception:
            pass
        self.db.add_message("assistant", reply)
        self._append("assistant", "DOXA\n")
        self._append("body", reply + "\n\n")
        self._set_status("Code mode " + job.status)
        self.refresh_all()

    def show_ticket_helper(self, path: str = "", reason: str = ""):
        return tickets_ui.open_helper(self, path, reason)

    def offer_ticket_help(self, text: str, ask, source: str = "YOU") -> None:
        """"contest this ticket <photo>": open the Traffic ticket panel with the photo; nothing is sent until the
        owner presses Read ticket (so he can black out his license number first)."""
        if ask.path:
            note = ("Opening Traffic ticket with your photo. Drag a box over your driver's license number, then press "
                    "Read ticket. I'll fill in the details and draft the TR-205 packet for you to check, sign and mail. "
                    "Not legal advice; I won't file, pay or send anything.")
        else:
            note = ("Opening Traffic ticket. Choose the photo of your ticket (or put its file path in your message), "
                    "cover your license number, then press Read ticket. Not legal advice; I won't file, pay or send "
                    "anything.")
        self.db.add_message("user", text)
        self.db.add_message("assistant", note)
        self._append("user", source + "\n")
        self._append("body", text + "\n\n")
        self._append("assistant", "DOXA\n")
        self._append("body", note + "\n\n")
        self.show_ticket_helper(ask.path, ask.reason)
        self.refresh_all()

    def show_product_hunter(self, niche: str = ""):
        return products_ui.open_hunter(self, niche)

    def start_product_hunt(self, text: str, niche: str = "", source: str = "YOU") -> bool:
        """Web research + one cloud-brain request in the background; the ranked products are posted in chat."""
        if self._hunting:
            self._set_status("A product hunt is already running.")
            return False
        clouds = self.brain.clouds(self.settings_data)
        if not clouds:
            note = ("Product hunting needs Claude or OpenAI. Connect one in Tools → AI brains (a hunt uses about "
                    "5-15¢ of your monthly cloud budget), then ask again.")
        else:
            note = (f"Hunting for winning products{' in ' + niche if niche else ''}: searching what's trending, then "
                    f"{clouds[0].display_name} picks and scores the best ones to test. About a minute.")
        self.db.add_message("user", text)
        self.db.add_message("assistant", note)
        self._append("user", source + "\n")
        self._append("body", text + "\n\n")
        self._append("assistant", "DOXA\n")
        self._append("body", note + "\n\n")
        self.refresh_all()
        if not clouds:
            return False
        self._hunting = True

        def work():
            try:
                result = products.hunt(self.brain, self.settings_data, self.products, niche,
                                       progress=lambda message: self.events.put(("status", message)))
                reply = products.chat_summary(result)
            except products.HuntError as exc:
                reply = str(exc)
            except Exception as exc:  # budget reached, offline, bad key: say so, keep Doxa running
                reply = f"The product hunt didn't finish: {exc}"
            self.events.put(("ui", lambda: self._post_hunt(reply)))
        threading.Thread(target=work, daemon=True, name="doxa-products").start()
        return True

    def _post_hunt(self, reply: str) -> None:
        self._hunting = False
        self.db.add_message("assistant", reply)
        self._append("assistant", "DOXA\n")
        self._append("body", reply + "\n\n")
        self._set_status("Product hunt ready")
        self.refresh_all()

    def _product_tick(self) -> None:
        """Daily hunt: once a day after 8:30 when Doxa is idle and a cloud brain is connected."""
        try:
            now = datetime.now()
            today = now.date().isoformat()
            if (self.settings_data.product_hunt_daily and now.strftime("%H:%M") >= "08:30" and not self._hunting
                    and not self.busy and time.monotonic() - self._last_activity >= 120
                    and not getattr(self.voice, "speaking", False) and self.brain.clouds(self.settings_data)
                    and self.products.auto_due(today)):
                self.products.mark_auto(today)  # once a day even if this hunt fails
                self.start_product_hunt("Daily product hunt", "", source="AUTOPILOT")
        except Exception:
            pass
        if not self._closing:
            self.after(300000, self._product_tick)

    def show_website_builder(self, name: str = ""):
        return sites_ui.open_builder(self, name)

    def show_experiments(self):
        from forgemind.experiments import open_studio
        return open_studio(self)

    def show_brief(self):
        workspace_ui.open_brief(self)

    def show_routines(self):
        workspace_ui.open_routines(self)

    def show_settings(self):
        jarvis_ui.settings_window(self, [
            ("Doxa", [
                ("Plugins", "Gmail, Calendar, Pacifica, VYRA and any app you connect.", self.show_plugins),
                ("AI brains", "Claude, ChatGPT and the local model, with monthly budgets.", self.show_brains),
                ("Voice", "Your mic, the voice, and what Doxa hears.", self.show_voice_check),
                ("Phone", "Doxa, Code mode and your PC screen on your phone.", self.show_phone),
                ("Autopilot", "Daily leads and growth reviews on your cloud budget.", self.show_autopilot)]),
            ("Local model", [
                ("Choose a model file", "Use a GGUF model you already have.", self.choose_model),
                ("Download the recommended model", "Qwen3.5 9B for this PC.", self.download_model)]),
            ("Your data", [
                ("Backup folder", "Where Doxa copies its backups.", self.choose_backup),
                ("Pinned memories", "Remove something Doxa remembers.", self._delete_memory_dialog),
                ("Clear conversation history", "Start the chat history over.", self.clear_chat)])])

    def _delete_memory_dialog(self):
        window = tk.Toplevel(self)
        window.title("Doxa · Manage pinned memories")
        window.configure(bg=BG)
        view = tk.Listbox(window, bg=PANEL_2, fg=TEXT, width=75, height=15, relief="flat")
        view.pack(fill="both", expand=True, padx=20, pady=20)
        records = self.db.list_memories()
        for item in records: view.insert("end", item["content"])
        def remove():
            selected = view.curselection()
            if selected and messagebox.askyesno("Remove memory", "Remove this pinned memory?", parent=window):
                self.db.delete_memory(records[selected[0]]["id"])
                self.refresh_all()
                window.destroy()
        ttk.Button(window, text="Remove selected memory", command=remove).pack(pady=(0, 20))

    def prepare_research(self):
        self.input.delete("1.0", "end")
        self.input.insert("1.0", "Research ")
        self.input.focus_set()

    def toggle_dictation(self):
        """The chat box mic: click, talk, click again; the words land in the type box (nothing is sent)."""
        from forgemind.dictation import Dictation
        if getattr(self, "dictation", None) is None:
            def put_text(text):
                def apply():
                    current = self.input.get("1.0", "end").rstrip()
                    self.input.delete("1.0", "end")
                    self.input.insert("1.0", (current + " " + text).strip() if current else text)
                    hint = getattr(self, "_composer_hint", None)
                    if hint is not None:
                        hint.place_forget()
                    self.input.focus_set()
                self.events.put(("ui", apply))

            def status(text):
                self.events.put(("status", text))
                self.events.put(("ui", self._paint_mic))
            self.dictation = Dictation(device=self.settings_data.voice_device or None, cloud_voice=self.cloud_voice,
                                       on_text=put_text, on_status=status)
        if self.voice.enabled and not self.dictation.recording:
            self.voice.disable()                      # one listener at a time; always-on resumes after
            self._resume_wake = True
        try:
            self.dictation.toggle()
        except Exception as exc:
            self._set_status(f"Microphone problem: {str(exc)[:120]}")
        if not self.dictation.recording and getattr(self, "_resume_wake", False) and self.settings_data.voice_enabled:
            self._resume_wake = False
            self.after(2500, self.voice.enable)
        self._paint_mic()

    def _paint_mic(self):
        button = getattr(self, "mic_button", None)
        if button is not None and getattr(self, "dictation", None) is not None:
            button.lit = self.dictation.recording or self.dictation.busy
            button._paint()

    def toggle_voice(self):
        if self.voice.enabled:
            self.voice.disable()
        else:
            self.voice.enable()
        self.settings_data.voice_enabled = self.voice.enabled  # remembered across restarts
        try:
            self.settings_data.save()
        except OSError:
            pass

    def stop_jarvis(self):
        self._cancel_answer.set()
        if getattr(self, "mode", "chat") == "code" and getattr(self, "code_runner", None):
            self.code_runner.stop()
        if getattr(self, "screen_job", None):
            self.screen_job.stop()
        if getattr(self, "_computer_controls", None):
            self._computer_controls.cancel()
        if getattr(self, "browser_controller", None):
            self.browser_controller.stop()
        self._voice_turn = False
        self.voice.interrupt()  # stop talking, keep listening for "Doxa" (the mic button turns listening off)

    def show_voice_check(self):
        from forgemind.voice_ui import open_voice_check
        return open_voice_check(self)

    def _voice_event(self, event):
        kind, value = event
        if kind == "voice_state":
            self.voice_label.configure(text=value)
            self.live_voice.configure(text=value + " · " + self._audio_note())
            self.wave.active = self.voice.enabled or self.voice.speaking
            self.voice_hint.configure(text='Say “Doxa”, then your request. Stop or Esc interrupts; the mic button turns listening off.\n' + self._audio_note()[:1].upper() + self._audio_note()[1:] + '.'
                                      if self.voice.enabled else 'Turn on the microphone to enable local wake-word listening.\nAudio stays on this device.')
            self.mic_button.configure(text="Mic on" if getattr(getattr(self, "dictation", None), "recording", False) else "Mic off",
                                      fg=BLUE if self.voice.enabled else TEXT)
        elif kind == "voice_error":
            self.voice_label.configure(text="Voice needs attention")
            self.live_voice.configure(text=value + (" Retrying in 10 seconds." if self.settings_data.voice_enabled else ""))
            self.mic_button.configure(text="Mic off")
            self.wave.active = False
            if self.settings_data.voice_enabled:  # always-on: a mic that dropped out (unplugged, sleep) comes back
                self.after(10000, lambda: (self.voice.enable() if self.settings_data.voice_enabled
                                           and not self.voice.enabled else None))
        elif kind == "voice_wake":
            self.voice_label.configure(text="I'm listening.")
            self.live_voice.configure(text="Listening for your next sentence · 15 seconds")
            self._touch_activity()
            self.after(15200, self._wake_timeout)
        elif kind == "voice_stop":
            self.stop_jarvis()
        elif kind == "voice_command":
            if not self.voice.enabled: return
            self._touch_activity()
            if self.busy:
                self.live_voice.configure(text="Still working · use Stop or Esc to interrupt.")
                return
            if self.input.get("1.0", "end").strip():
                self.live_voice.configure(text="A typed draft is open. Send or clear it before speaking a new request.")
                return
            self._voice_turn = True
            self._voice_dispatch = True
            self.input.insert("1.0", value)
            try: self.send()
            finally: self._voice_dispatch = False

    def _wake_timeout(self):
        if self.voice.enabled and not self.busy and not self.voice.speaking and self.voice.router.clock() >= self.voice.router.until:
            self.voice_label.configure(text='Sleeping · say “Doxa”')
            self.live_voice.configure(text='Sleeping · say “Doxa” · ' + self._audio_note())

    def _append(self, tag: str, text: str) -> None:
        jarvis_ui.show_chat(self)
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.configure(text=text, foreground=ERROR if error else TEXT)
        if self.busy:
            self.progress.pack(fill="x", pady=(10, 0))
        else:
            self.progress.pack_forget()

    def refresh_all(self) -> None:
        counts = self.db.counts()
        self.stats_label.configure(
            text=f"{counts['documents']:,} files · {counts['chunks']:,} searchable chunks\n"
                 f"{counts['memories']:,} pinned · {counts['learnings']:,} learned items · "
                 f"{counts['messages']:,} chat messages\n"
                 f"{len(self.settings_data.knowledge_sources):,} read-only connected sources"
        )
        self.model_label.configure(text=self.brain_label())
        if getattr(self, "lane_pill", None) is not None:  # e.g. the PC's model finished loading after start
            self.lane_pill.configure(text=jarvis_ui.lane_text(self, self.mode))
        jarvis_ui.refresh_recents(self)
        if hasattr(self, 'capability_label'):
            self.capability_label.configure(text='Screen vision ready' if self.media_library.vision_ready else 'Screen vision · setup needed')
        self.memory_list.delete(0, "end")
        self._memory_ids = []
        for row in self.db.list_memories():
            preview = row["content"].replace("\n", " ")
            self.memory_list.insert("end", preview[:70] + ("…" if len(preview) > 70 else ""))
            self._memory_ids.append(row["id"])

    def choose_model(self) -> None:
        path = filedialog.askopenfilename(title="Choose a GGUF model", filetypes=[("GGUF models", "*.gguf"), ("All files", "*.*")])
        if path:
            self._load_model(path)

    def use_previous_brain(self):
        path=app_data_dir()/'models'/'qwen2.5-coder-7b-instruct-q4_k_m.gguf'
        if path.is_file():
            self._load_model(str(path))
        else:
            self._set_status('The previous model is not installed on this computer.',error=True)

    def _load_model(self, path: str) -> None:
        if self._research_session is not None and self._research_session.device == 'cuda':
            self._set_status("Pause the research lab before loading the chat model")
            return
        if self.busy:
            return
        self.busy = True
        self.send_button.configure(state="disabled")
        self._set_status("Loading model into GPU…")

        def work() -> None:
            try:
                self.engine.load(path, self.settings_data.context_size)
                self.events.put(("model_loaded",))
            except Exception as exc:
                self.events.put(("error", f"Could not load model: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def download_model(self) -> None:
        if self.busy: return
        from forgemind.model_library import obtain, NAME
        target=app_data_dir()/'models'/NAME
        if not target.exists() and not messagebox.askyesno('Recommended local brain','Download Qwen3.5 9B Q4_K_M (5.68 GB)? It runs on your device after download. Your current model is preserved.'):
            return
        self.busy=True
        self.send_button.configure(state='disabled')
        self._set_status('Verifying / downloading the recommended local model…')
        def work():
            try:
                path=obtain(target.parent,lambda value:self.events.put(('progress',value)))
                self.events.put(('downloaded',str(path)))
            except Exception as exc:
                self.events.put(('error','Model download: '+str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def choose_knowledge(self) -> None:
        if self.busy:
            return
        path = filedialog.askdirectory(title="Choose a code or document folder")
        if not path:
            return
        self.settings_data.knowledge_folder = path
        if path not in self.settings_data.knowledge_sources:
            self.settings_data.knowledge_sources.append(path)
        self.settings_data.save()
        self.busy = True
        self._set_status("Scanning files…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def work() -> None:
            try:
                result = index_folder(self.db, Path(path), lambda name: self.events.put(("index_file", name)))
                self.events.put(("indexed", *result))
            except Exception as exc:
                self.events.put(("error", f"Indexing failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def choose_files(self) -> None:
        if self.busy:
            return
        paths = filedialog.askopenfilenames(
            title="Choose files Doxa may read",
            filetypes=[
                (
                    "Documents and code",
                    "*.txt *.md *.pdf *.docx *.xlsx *.pptx *.py *.js *.ts *.tsx *.json *.yaml *.yml *.csv *.sql",
                ),
                ("All files", "*.*"),
            ],
        )
        if not paths:
            return
        for path in paths:
            if path not in self.settings_data.knowledge_sources:
                self.settings_data.knowledge_sources.append(path)
        self.settings_data.save()
        self.busy = True
        self._set_status("Reading selected files…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def work() -> None:
            try:
                result = index_files(
                    self.db,
                    [Path(path) for path in paths],
                    lambda name: self.events.put(("index_file", name)),
                )
                self.events.put(("indexed", *result))
            except Exception as exc:
                self.events.put(("error", f"File connection failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def connect_github(self) -> None:
        if self.busy:
            return
        repository_url = simpledialog.askstring(
            "Connect GitHub read-only",
            "Paste a GitHub repository URL. Doxa downloads a read-only snapshot; it cannot push changes.\n\n"
            "Example: https://github.com/owner/project",
            parent=self,
        )
        if not repository_url:
            return
        self.busy = True
        self._set_status("Connecting to GitHub read-only…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def work() -> None:
            try:
                snapshot = connect_github_repository(
                    repository_url,
                    progress=lambda status: self.events.put(("status", status)),
                )
                result = index_folder(
                    self.db,
                    snapshot,
                    lambda name: self.events.put(("index_file", name)),
                )
                self.events.put(("github_connected", repository_url, str(snapshot), *result))
            except Exception as exc:
                self.events.put(("error", f"GitHub connection failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def open_training_lab(self) -> None:
        window = tk.Toplevel(self)
        window.title("Doxa Training Lab — Neural Weight Starter")
        window.geometry("820x690")
        window.minsize(680, 570)
        window.configure(bg=BG)
        window.transient(self)

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        frame.rowconfigure(6, weight=1)

        ttk.Label(frame, text="Neural Weight Training Starter", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text=(
                "Save examples that you personally approve. Doxa can validate and export them for "
                "future LoRA/QLoRA training. This does not silently train on chats or internet pages, and it "
                "does not change the loaded model until a trained adapter passes evaluation."
            ),
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(7, 12))

        status = ttk.Label(frame, text="", wraplength=760)
        status.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(frame, text="Instruction or question").grid(row=3, column=0, sticky="w")
        instruction = ScrolledText(
            frame, height=7, wrap="word", bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=("Segoe UI", 10), padx=9, pady=9,
        )
        instruction.grid(row=4, column=0, sticky="nsew", pady=(4, 10))

        ttk.Label(frame, text="Ideal answer you reviewed and want it to learn").grid(row=5, column=0, sticky="w")
        ideal = ScrolledText(
            frame, height=9, wrap="word", bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=("Segoe UI", 10), padx=9, pady=9,
        )
        ideal.grid(row=6, column=0, sticky="nsew", pady=(4, 12))

        controls = ttk.Frame(frame)
        controls.grid(row=7, column=0, sticky="ew")

        def refresh_training_status(message: str = "") -> None:
            report = self.training_lab.validate_dataset()
            readiness = "ready for a trial" if report["ready_for_trial"] else "building dataset"
            text = f"{report['valid_examples']} reviewed examples · {readiness}"
            if message:
                text += f"\n{message}"
            status.configure(text=text)

        def save_example() -> None:
            try:
                self.training_lab.add_reviewed_example(
                    instruction.get("1.0", "end").strip(),
                    ideal.get("1.0", "end").strip(),
                )
            except ValueError as exc:
                messagebox.showinfo("Training example", str(exc), parent=window)
                return
            instruction.delete("1.0", "end")
            ideal.delete("1.0", "end")
            refresh_training_status("Saved locally as reviewed training data.")

        def validate_examples() -> None:
            report = self.training_lab.validate_dataset()
            details = [
                f"Valid examples: {report['valid_examples']}",
                f"Ready for trial: {'yes' if report['ready_for_trial'] else 'not yet'}",
            ]
            details.extend(report["errors"])
            details.extend(report["warnings"])
            messagebox.showinfo("Dataset check", "\n\n".join(details), parent=window)

        def export_examples() -> None:
            target = filedialog.asksaveasfilename(
                title="Export reviewed training data",
                defaultextension=".jsonl",
                filetypes=[("JSON Lines", "*.jsonl")],
                initialfile="forgemind-reviewed-training.jsonl",
                parent=window,
            )
            if target:
                path = self.training_lab.export_chat_jsonl(Path(target))
                refresh_training_status(f"Exported: {path}")

        def create_plan() -> None:
            path = self.training_lab.create_lora_plan(
                self.settings_data.model_path,
                vram_mb=8188,
                context_size=min(self.settings_data.context_size, 2048),
            )
            messagebox.showinfo(
                "LoRA plan created",
                f"Saved a hardware-aware training plan:\n\n{path}\n\n"
                "This is a plan, not a training run. The current GGUF is an inference file; a compatible "
                "original training checkpoint and trainer are still required.",
                parent=window,
            )

        ttk.Button(controls, text="Save reviewed example", style="Accent.TButton", command=save_example).pack(
            side="left", padx=(0, 7)
        )
        ttk.Button(controls, text="Validate dataset", command=validate_examples).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Export dataset", command=export_examples).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Create LoRA plan", command=create_plan).pack(side="left")
        refresh_training_status()

    def open_project_workspace(self) -> None:
        window = tk.Toplevel(self)
        window.title("Doxa Project Workspace")
        window.geometry("900x700")
        window.minsize(720, 570)
        window.configure(bg=BG)
        window.transient(self)
        local_events: queue.Queue[tuple] = queue.Queue()

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)

        ttk.Label(frame, text="Controlled Project Workspace", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text=(
                "Doxa reads the selected project, creates a separate candidate copy, and excludes "
                "common secrets and generated dependency folders. Changes can reach the original only after "
                "checks pass and you explicitly approve them."
            ),
            style="Muted.TLabel",
            wraplength=850,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(7, 10))
        status = ttk.Label(frame, text="No project candidate yet.", wraplength=850)
        status.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        controls = ttk.Frame(frame)
        controls.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        diff_view = ScrolledText(
            frame, wrap="none", bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=("Consolas", 9), padx=9, pady=9,
        )
        diff_view.grid(row=4, column=0, sticky="nsew")
        diff_view.insert("1.0", "Create a candidate, then edit its separate files before running checks.\n")
        diff_view.configure(state="disabled")

        def show_diff() -> None:
            diff_view.configure(state="normal")
            diff_view.delete("1.0", "end")
            diff_view.insert("1.0", self.project_workspace.unified_diff())
            diff_view.configure(state="disabled")

        def refresh_status(message: str = "") -> None:
            state = self.project_workspace.load_state()
            if not state:
                status.configure(text=message or "No project candidate yet.")
                return
            changed = len(self.project_workspace.changed_files())
            status.configure(
                text=(
                    f"Source: {state['source']}\nCandidate: {state['candidate']}\n"
                    f"Changed files: {changed} · Checks: "
                    f"{'passed' if state.get('checks_passed') else 'not passed'}"
                    + (f"\n{message}" if message else "")
                )
            )

        def choose_project() -> None:
            selected = filedialog.askdirectory(title="Choose the Pacifica or another project folder", parent=window)
            if not selected:
                return
            status.configure(text="Mapping, copying, and indexing the selected project…")

            def work() -> None:
                try:
                    project_map = self.project_workspace.repository_map(Path(selected))
                    state = self.project_workspace.create_candidate(Path(selected))
                    indexed = index_folder(self.db, Path(selected))
                    local_events.put(("created", project_map, state, indexed))
                except Exception as exc:
                    local_events.put(("error", str(exc)))

            threading.Thread(target=work, daemon=True).start()

        def open_candidate() -> None:
            state = self.project_workspace.load_state()
            if not state:
                messagebox.showinfo("Project workspace", "Create a candidate first.", parent=window)
                return
            subprocess.Popen(["explorer", str(Path(state["candidate"]))])

        def run_checks() -> None:
            status.configure(text="Running detected checks inside the candidate copy…")

            def work() -> None:
                try:
                    local_events.put(("checked", self.project_workspace.run_checks()))
                except Exception as exc:
                    local_events.put(("error", str(exc)))

            threading.Thread(target=work, daemon=True).start()

        def apply_candidate() -> None:
            if not messagebox.askyesno(
                "Apply verified candidate",
                "Apply the displayed, verified candidate changes to the original project? A rollback backup will be created.",
                parent=window,
            ):
                return
            try:
                backup = self.project_workspace.apply_candidate(approved=True)
                refresh_status(f"Applied with rollback backup: {backup}")
                show_diff()
            except Exception as exc:
                messagebox.showerror("Candidate not applied", str(exc), parent=window)

        def rollback_project() -> None:
            if not messagebox.askyesno(
                "Rollback project", "Restore the most recently applied project candidate?", parent=window
            ):
                return
            try:
                restored = self.project_workspace.rollback_last()
                refresh_status(f"Restored {len(restored)} files from the latest backup.")
                show_diff()
            except Exception as exc:
                messagebox.showerror("Rollback failed", str(exc), parent=window)

        ttk.Button(controls, text="Choose project", style="Accent.TButton", command=choose_project).pack(
            side="left", padx=(0, 7)
        )
        ttk.Button(controls, text="Open candidate folder", command=open_candidate).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Refresh diff", command=lambda: (show_diff(), refresh_status())).pack(
            side="left", padx=(0, 7)
        )
        ttk.Button(controls, text="Run checks", command=run_checks).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Apply verified", command=apply_candidate).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Rollback", command=rollback_project).pack(side="left")

        def poll() -> None:
            try:
                while True:
                    event = local_events.get_nowait()
                    if event[0] == "created":
                        project_map, _state, indexed = event[1], event[2], event[3]
                        refresh_status(
                            f"Mapped {project_map['file_count']} files and {project_map['test_files']} test files; "
                            f"indexed {indexed[0]} files into searchable knowledge."
                        )
                        show_diff()
                        self.refresh_all()
                    elif event[0] == "checked":
                        result = event[1]
                        refresh_status("Checks passed." if result["passed"] else "Checks failed; inspect the log below.")
                        diff_view.configure(state="normal")
                        diff_view.delete("1.0", "end")
                        diff_view.insert("1.0", "\n\n".join(result["logs"]))
                        diff_view.configure(state="disabled")
                    elif event[0] == "error":
                        refresh_status("Operation failed.")
                        messagebox.showerror("Project workspace", event[1], parent=window)
            except queue.Empty:
                pass
            if window.winfo_exists():
                window.after(100, poll)

        refresh_status()
        show_diff()
        window.after(100, poll)

    def open_media_library(self) -> None:
        window = tk.Toplevel(self)
        window.title("Doxa Media Library")
        window.geometry("900x680")
        window.minsize(720, 540)
        window.configure(bg=BG)
        window.transient(self)
        local_events: queue.Queue[tuple] = queue.Queue()
        record_ids: list[str] = []

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)

        ttk.Label(frame, text="Screenshots and OBS Recordings", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text=(
                "Selected media stays in its original location and is treated as read-only. Doxa stores "
                "only generated metadata, transcripts, sampled frames, and OCR text in its own data folder. "
                "Recording transcription runs locally; the first run downloads the selected speech model."
            ),
            style="Muted.TLabel",
            wraplength=850,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(7, 10))
        status = ttk.Label(frame, text="Ready", wraplength=850)
        status.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        controls = ttk.Frame(frame)
        controls.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        media_list = tk.Listbox(
            frame, bg=PANEL_2, fg=TEXT, selectbackground=jarvis_ui.SELECT, relief="flat",
            font=("Segoe UI", 10), activestyle="none",
        )
        media_list.grid(row=4, column=0, sticky="nsew")

        def refresh_records(message: str = "") -> None:
            records = self.media_library.list_records()
            record_ids.clear()
            media_list.delete(0, "end")
            for record in records:
                record_ids.append(record["id"])
                duration = record.get("metadata", {}).get("duration_seconds")
                detail = f" · {duration / 60:0.1f} min" if isinstance(duration, (int, float)) and duration else ""
                media_list.insert(
                    "end", f"{record['type'].upper()} · {record['name']}{detail} · {record.get('status', 'added')}"
                )
            status.configure(text=message or f"{len(records)} media items")

        def add_media() -> None:
            paths = filedialog.askopenfilenames(
                title="Choose screenshots, audio, or OBS recordings",
                filetypes=[
                    ("Supported media", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mkv *.mov *.webm *.avi *.m4v *.wmv"),
                    ("All files", "*.*"),
                ],
                parent=window,
            )
            if not paths:
                return
            added = 0
            errors: list[str] = []
            for path in paths:
                try:
                    record = self.media_library.add(Path(path))
                    knowledge = self.media_library.knowledge_document(record["id"])
                    stat = knowledge.stat()
                    self.db.replace_document(knowledge, stat.st_mtime_ns, stat.st_size, chunk_text(knowledge.read_text(encoding="utf-8")))
                    added += 1
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            refresh_records(f"Added {added} media items." + (f" {len(errors)} could not be added." if errors else ""))
            self.refresh_all()

        def selected_record() -> dict | None:
            selection = media_list.curselection()
            if not selection:
                messagebox.showinfo("Media library", "Select a media item first.", parent=window)
                return None
            return self.media_library.get(record_ids[selection[0]])

        def analyze_selected() -> None:
            if self.busy:
                status.configure(text="Wait for the current model operation to finish.")
                return
            record = selected_record()
            if not record:
                return
            status.configure(text=f"Processing {record['name']} locally…")
            uses_vision = record["type"] in {"image", "video"} and self.media_library.vision_ready
            previous_model = self.settings_data.model_path if self.engine.loaded else ""
            self.busy = True
            self.send_button.configure(state="disabled")

            def work() -> None:
                notes: list[str] = []
                failure = ""
                try:
                    if uses_vision:
                        local_events.put(("progress", "Switching from the coding model to the local vision model…"))
                        self.engine.unload()
                    if record["type"] in {"audio", "video"}:
                        transcript = self.media_library.transcribe(
                            record["id"], progress=lambda text: local_events.put(("progress", text))
                        )
                        notes.append(f"Transcript: {transcript}")
                    if record["type"] == "video":
                        frames = self.media_library.sample_video_frames(record["id"])
                        notes.append(f"Sampled {len(frames)} frames for future vision analysis.")
                    if record["type"] in {"image", "video"} and self.media_library.vision_ready:
                        analysis = self.media_library.analyze_visual(
                            record["id"], progress=lambda text: local_events.put(("progress", text))
                        )
                        notes.append(f"Local vision produced {len(analysis)} characters of visual analysis.")
                    elif record["type"] == "image":
                        try:
                            text = self.media_library.ocr_image(record["id"])
                            notes.append(f"Read {len(text)} characters of visible text.")
                        except RuntimeError as exc:
                            notes.append(str(exc))
                    knowledge = self.media_library.knowledge_document(record["id"])
                    stat = knowledge.stat()
                    self.db.replace_document(
                        knowledge, stat.st_mtime_ns, stat.st_size,
                        chunk_text(knowledge.read_text(encoding="utf-8", errors="replace")),
                    )
                except Exception as exc:
                    failure = str(exc)
                finally:
                    if uses_vision and previous_model and Path(previous_model).is_file():
                        try:
                            local_events.put(("progress", "Reloading the coding model…"))
                            self.engine.load(previous_model, self.settings_data.context_size)
                        except Exception as exc:
                            failure = (failure + " " if failure else "") + f"The coding model could not reload: {exc}"
                if failure:
                    local_events.put(("error", failure))
                else:
                    local_events.put(("complete", record["name"], notes))

            threading.Thread(target=work, daemon=True).start()

        def download_vision() -> None:
            if self.media_library.vision_ready:
                messagebox.showinfo("Local vision", "The local screenshot vision model is already installed.", parent=window)
                return
            if not messagebox.askyesno(
                "Download local vision",
                "Download the Qwen2.5-VL 3B vision model and projector (about 2.8 GB)?\n\n"
                "This lets Doxa inspect screenshots and sampled OBS video frames locally.",
                parent=window,
            ):
                return
            status.configure(text="Starting the local vision download…")

            def work() -> None:
                try:
                    self.media_library.download_vision_models(
                        progress=lambda text: local_events.put(("progress", text))
                    )
                    local_events.put(("vision_downloaded",))
                except Exception as exc:
                    local_events.put(("error", f"Vision download failed: {exc}"))

            threading.Thread(target=work, daemon=True).start()

        def open_source() -> None:
            record = selected_record()
            if record:
                subprocess.Popen(["explorer", "/select,", record["source"]])

        ttk.Button(controls, text="Add media", style="Accent.TButton", command=add_media).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Analyze selected", command=analyze_selected).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Download local vision", command=download_vision).pack(side="left", padx=(0, 7))
        ttk.Button(controls, text="Show source file", command=open_source).pack(side="left")

        def poll() -> None:
            try:
                while True:
                    event = local_events.get_nowait()
                    if event[0] == "progress":
                        status.configure(text=event[1])
                    elif event[0] == "complete":
                        self.busy = False
                        self.send_button.configure(state="normal")
                        refresh_records(f"Finished {event[1]}. " + " ".join(event[2]))
                        self.refresh_all()
                    elif event[0] == "vision_downloaded":
                        refresh_records("Local screenshot vision is installed and ready.")
                    elif event[0] == "error":
                        self.busy = False
                        self.send_button.configure(state="normal")
                        status.configure(text="Media processing failed.")
                        messagebox.showerror("Media processing", event[1], parent=window)
            except queue.Empty:
                pass
            if window.winfo_exists():
                window.after(100, poll)

        refresh_records()
        window.after(100, poll)

    def choose_backup(self) -> None:
        path = filedialog.askdirectory(
            title="Choose a Google Drive folder for Doxa backups"
        )
        if not path:
            return
        self.settings_data.backup_folder = path
        self.settings_data.save()
        self.backup_now()

    def backup_now(self) -> None:
        if not self.settings_data.backup_folder:
            messagebox.showinfo(
                "Choose a backup folder",
                "Click “Google Drive backup” and select a folder inside Google Drive for desktop.",
            )
            return
        try:
            target = self.db.backup_to(Path(self.settings_data.backup_folder) / "ForgeMindBackups")
            self._set_status(f"Backed up: {target.name}")
        except Exception as exc:
            self._set_status(f"Backup failed: {exc}", error=True)

    def add_memory(self) -> None:
        value = simpledialog.askstring(
            "Pin a memory", "What should Doxa remember?\nExample: My backend uses FastAPI and PostgreSQL.", parent=self
        )
        if value:
            self.db.add_memory(value)
            self.refresh_all()

    def delete_memory(self) -> None:
        selection = self.memory_list.curselection()
        if selection:
            self.db.delete_memory(self._memory_ids[selection[0]])
            self.refresh_all()

    def clear_chat(self) -> None:
        if not messagebox.askyesno(
            "Clear chat history",
            "Clear saved conversation messages? Indexed documents and pinned memories will remain.",
            parent=self,
        ):
            return
        self.db.clear_messages()
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._welcome()
        jarvis_ui.show_hero(self)
        jarvis_ui.set_view(self, "Home")
        self.refresh_all()
        self._set_status("Chat history cleared")

    def send(self) -> None:
        if not self._voice_dispatch: self._voice_turn = False
        text = self.input.get("1.0", "end").strip()
        if not text or self.busy:
            return
        if getattr(self, "mode", "chat") == "code" and not self._voice_dispatch:
            # Code tab: the message is the job (or a follow-up in the same Codex / Claude Code chat).
            fresh = self.code_fresh_var.get()
            asked = code_mode.code_request(text)
            engine, task = asked if asked else (self.code_engine_var.get(), text)
            self.input.delete("1.0", "end")
            self.start_code_job(text, task, self.code_folder_var.get().strip() or None, engine,
                                follow_up=False if fresh else None)
            self.code_fresh_var.set(False)
            return
        command = parse_command(text)
        if command:
            if command.kind == "computer":
                open_computer_panel(self, command.target)
                self._set_status("Task prepared in Screen control. Review it, then Start task.")
                self.input.delete("1.0", "end")
                self._voice_turn = False
                return
            if command.kind == "brief":
                self.show_local_brief(text)
                self.input.delete("1.0", "end")
                self._voice_turn = False
                return
            reply = self.run_quick_action(command.target)
            if reply:
                self.db.add_message("user", text)
                self.db.add_message("assistant", reply)
                if command.kind == "open":
                    self._append("user", "YOU\n")
                    self._append("body", text + "\n\n")
                    self._append("assistant", "DOXA\n")
                    self._append("body", reply + "\n\n")
                self.input.delete("1.0", "end")
                if self._voice_turn and self.voice.enabled:
                    self.voice.speak(reply)
                self._voice_turn = False
                self.refresh_all()
            return
        from forgemind.qr_codes import qr_request
        if qr_request(text):
            # "QR codes" / "pair my phone" / "download the app": BOTH codes every time, no model call.
            self.input.delete("1.0", "end")
            both = self.show_qr_codes()
            note = ("Here are both QR codes: 1. download the Doxa app, 2. pair Doxa with your phone. They're also in "
                    "Documents\\Doxa Notes\\QR codes." if both else "I couldn't make the QR codes: see the status line.")
            self.db.add_message("user", text)
            self.db.add_message("assistant", note)
            self._append("user", "YOU\n")
            self._append("body", text + "\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", note + "\n\n")
            self._voice_turn = False
            self.refresh_all()
            return
        code_ask = code_mode.code_request(text)
        if code_ask is not None:
            # "code: …", "codex: …", "claude code: …", "reverse engineer …": straight to Code mode, no model call.
            self.input.delete("1.0", "end")
            self.start_code_job(text, code_ask[1], None, code_ask[0])
            self._voice_turn = False
            return
        links = (reels.reel_links(text) + reels.local_media(text)
                 or reels.links_from_history(text, self.db.recent_messages(8)))  # "download them"
        if links:
            # Reel/short-video links: download, transcribe locally and post the transcript (no model needed).
            self.input.delete("1.0", "end")
            self.start_reels(text, links)
            self._voice_turn = False
            return
        quote = pacifica.quote_request_from_chat(text)
        if quote:
            # Checked before browser tasks ("make a quote ..." would match those too). Deterministic, no model:
            # the customer's details never go into a prompt.
            self.input.delete("1.0", "end")
            self.offer_quote(text, quote)
            self._voice_turn = False
            return
        ticket_ask = tickets.ticket_request(text)
        if ticket_ask is not None:
            # "contest this ticket C:\...\ticket.jpg": the Traffic ticket panel; one cloud read only after Read ticket.
            self.input.delete("1.0", "end")
            self.offer_ticket_help(text, ticket_ask)
            self._voice_turn = False
            return
        niche = products.hunt_request(text)
        if niche is not None:
            # "find winning products for pets": web research + one cloud request, results posted in chat.
            self.input.delete("1.0", "end")
            self.start_product_hunt(text, niche)
            self._voice_turn = False
            return
        site_name = sites_ui.site_request(text)
        if site_name is not None:
            # "build a website for Casa Luna": open the builder with the name filled in (no model needed).
            self.input.delete("1.0", "end")
            note = ("Opening the Website builder" + (f" for {site_name}" if site_name else "") + ". Add the facts and "
                    "the folder with your footage, then press Build. You'll get the site, a preview to show the owner, "
                    "and a proposal with a shot list.")
            self.db.add_message("user", text)
            self.db.add_message("assistant", note)
            self._append("user", "YOU\n")
            self._append("body", text + "\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", note + "\n\n")
            self.show_website_builder(site_name)
            self._voice_turn = False
            self.refresh_all()
            return
        if is_calendar_request(text):
            # Calendar requests open the event card; nothing is written until the owner presses Yes.
            self.input.delete("1.0", "end")
            offer_event(self, text)
            self._voice_turn = False
            return
        calendar_day = calendar_query_day(text, calendar_now(self).date())
        if calendar_day:
            self.input.delete("1.0", "end")
            answer_day(self, text, calendar_day)
            self._voice_turn = False
            return
        tool_name = text.strip().casefold().removeprefix("open ").removeprefix("show ").removeprefix("the ").rstrip(".!")
        for _, entries in self.tool_groups():
            for name, _, launch in entries:
                if tool_name == name.casefold():
                    self.input.delete("1.0", "end")
                    launch()
                    self._set_status("Opened " + name)
                    return
        browser_task = browser_task_from_chat(text, self.db.recent_messages(8))
        if browser_task and not self.engine.loaded and any(word in text.lower() for word in ("research", "look through", "search", "browse websites")):
            self._public_research_from_chat(text)
            return
        if browser_task:
            try:
                self.browser_controller.start(browser_task)
                note = "Started the website task. Browser task shows progress and any requests for your input."
            except (RuntimeError, ValueError) as error:
                note = "Browser task could not start: " + str(error)
            self.db.add_message("user", text)
            self.db.add_message("assistant", note)
            self.input.delete("1.0", "end")
            self._append("user", "YOU\n")
            self._append("body", text + "\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", note + "\n\n")
            self.show_browser(browser_task)
            if self._voice_turn and self.voice.enabled:
                self.voice.speak(note)
            self._voice_turn = False
            self.refresh_all()
            return
        local_answer=business_reply(self,text) or clock_reply(text)
        if local_answer:
            self.db.add_message('user',text)
            self.db.add_message('assistant',local_answer)
            self.input.delete('1.0','end')
            self._append('user','YOU\n')
            self._append('body',text+'\n\n')
            self._append('assistant','DOXA\n')
            self._append('body',local_answer+'\n\n')
            if self._voice_turn and self.voice.enabled:
                self.voice.speak(local_answer)
            self._voice_turn=False
            self.refresh_all()
            return
        if self._voice_dispatch and (text.lower().startswith("computer:") or evolution_goal_from_chat(text)):
            self._voice_turn = False
            self._set_status("Review this action in the text box, then click Send to start it.")
            return
        if text.lower().startswith("computer:"):
            open_computer_panel(self, text.split(":", 1)[1].strip())
            self.input.delete("1.0", "end")
            return
        if not self.brain.ready(self.settings_data):
            messagebox.showinfo("Load a model", "Download the starter model, choose a GGUF model, or connect a cloud "
                                "brain in Tools → AI brains first.")
            return
        lowered = text.lower()
        if self.settings_data.adaptive_learning:
            for content, kind, confidence in learning_items(text):
                self.db.add_learning(content, kind=kind, confidence=confidence)
        evolution_goal = (
            evolution_goal_from_chat(text, self.db.recent_messages(8))
            if self.settings_data.auto_evolve_from_chat else None
        )
        if evolution_goal:
            self.db.add_message("user", text)
            self.input.delete("1.0", "end")
            self.start_evolution(evolution_goal)
            return
        if len(text) >= 12000:
            path = self._store_knowledge_text(text, "pasted-knowledge")
            urls = extract_urls(text, max_urls=25)
            notice = (
                f"Imported the oversized message as searchable knowledge: {path.name}. "
                "It was split into manageable chunks."
            )
            if urls:
                notice += f" I found {len(urls)} links and am opening their pages now."
            else:
                notice += " Ask a shorter question about it now."
            self.db.add_message("user", f"[Imported oversized message: {path.name}]")
            self.db.add_message("assistant", notice)
            self.input.delete("1.0", "end")
            self._append("user", "YOU — LARGE KNOWLEDGE IMPORT\n")
            self._append("body", text[:800] + "\n[…full text stored in the knowledge index…]\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", notice + "\n\n")
            self.refresh_all()
            if urls:
                self.busy = True
                self.send_button.configure(state="disabled")
                self._set_status(f"Opening {len(urls)} supplied links…")

                def import_links() -> None:
                    try:
                        results = fetch_urls(urls, max_urls=25)
                        stored = 0
                        for result in results:
                            if not result.evidence:
                                continue
                            self._store_knowledge_text(
                                f"# {result.title}\n\nURL: {result.url}\n\n{result.evidence}",
                                "web-page",
                            )
                            stored += 1
                        self.events.put(("links_imported", stored, len(urls)))
                    except Exception as exc:
                        self.events.put(("error", f"Link import failed: {exc}"))

                threading.Thread(target=import_links, daemon=True).start()
            return
        memory_prefix = next((p for p in ("remember:", "remember that ", "teach:") if lowered.startswith(p)), None)
        if memory_prefix:
            memory = text[len(memory_prefix):].strip()
            if not memory:
                messagebox.showinfo("Nothing to remember", "Add the information after Remember: or Teach:")
                return
            self.db.add_message("user", text)
            self.db.add_memory(memory)
            confirmation = f"Saved as a pinned memory: {memory}"
            self.db.add_message("assistant", confirmation)
            self.input.delete("1.0", "end")
            self._append("user", "YOU\n")
            self._append("body", text + "\n\n")
            self._append("assistant", "DOXA\n")
            self._append("body", confirmation + "\n\n")
            self.refresh_all()
            return
        self._cancel_answer.clear()
        history = self.db.recent_messages(12)
        self.db.add_message("user", text)
        self.input.delete("1.0", "end")
        self._append("user", "YOU\n")
        self._append("body", text + "\n\n")
        self._append("assistant", "DOXA\n")
        self.busy = True
        self.send_button.configure(state="disabled")
        self._set_status("Thinking locally…")
        self._answer_parts = []
        self._last_web = []
        settings_snapshot = Settings(**self.settings_data.__dict__)
        run_id = self.run_journal.start(text)
        lane = self.mode if getattr(self, "mode", "chat") in ("chat", "work") else None

        def work() -> None:
            try:
                memories = self.db.retrieve(text)
                web: list[SearchResult] = []
                if settings_snapshot.auto_research and should_search_web(text):
                    self.run_journal.stage(run_id, 'Reading public web sources')
                    self.events.put(("status", "Researching current public information…"))
                    try:
                        memory_text = ""
                        if "link" in text.lower() or "url" in text.lower():
                            memory_text = "\n".join(item["content"] for item in memories)
                        web = research_web(
                            text,
                            max_results=5,
                            extract_results=3,
                            source_text=memory_text,
                        )
                    except Exception:
                        self.events.put(("status", "Web search unavailable; answering from local knowledge…"))
                self._last_web = web
                chosen, _, _ = self.brain.pick(text, settings_snapshot, lane)
                where = "on your GPU" if chosen is self.inference else f"with {chosen.display_name}"
                self.events.put(("status", f"Generating {where}…"))
                self.run_journal.stage(run_id, 'Generating locally' if chosen is self.inference else f'Generating with {chosen.display_name}')
                first = True
                for token in self.brain.stream(history, text, settings_snapshot, memories, web,
                                               stop_event=self._cancel_answer, lane=lane):
                    if first:
                        self.run_journal.first_response(run_id)
                        first = False
                    self.events.put(("token", token))
                self.run_journal.finish(run_id, 'stopped' if self._cancel_answer.is_set() else 'complete')
                self.events.put(("answer_done",))
                self.events.put(("ui", self._show_brain_used))
            except Exception as exc:
                self.run_journal.finish(run_id, 'error', 'The request did not complete. See the conversation for details.')
                self.events.put(("error", f"Answer failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _public_research_from_chat(self, text):
        self.input.delete("1.0", "end")
        self.db.add_message("user", text)
        self._append("user", "YOU\n")
        self._append("body", text + "\n\n")
        self._set_status("Reading public websites…")
        self.busy = True
        self.send_button.configure(state="disabled")
        self._cancel_answer.clear()

        def read():
            try:
                pages = research_web(text, max_results=4, extract_results=3)
                excerpts = [f"{p.title}\n{p.url}\n{p.evidence[:900]}" for p in pages if p.evidence.strip()]
                reply = "\n\n".join(excerpts) or "No readable page came back. Give me a specific public URL to check."
            except Exception as error:
                reply = f"The public website lookup failed ({type(error).__name__}). Try a specific public URL."

            def finish():
                if self._cancel_answer.is_set():
                    answer = "Research stopped."
                else:
                    answer = reply
                self.db.add_message("assistant", answer)
                self._append("assistant", "DOXA\n")
                self._append("body", answer + "\n\n")
                self.busy = False
                if self._voice_turn and self.voice.enabled and not self._cancel_answer.is_set():
                    self.voice.speak(answer.split("\n\n")[0])
                self._voice_turn = False
                self.send_button.configure(state="normal")
                self._set_status("Ready")
            self.events.put(("ui", finish))
        threading.Thread(target=read, daemon=True).start()

    def _audio_note(self) -> str:
        cloud = getattr(self, "cloud_voice", None)
        if cloud is not None and cloud.available:
            return "wake word heard on this PC; your request is transcribed by OpenAI"
        return "audio stays on this device"

    def brain_label(self) -> str:
        names = {"auto": "Auto", "local": "Local only", "openai": "OpenAI", "claude": "Claude"}
        mode = names.get(self.settings_data.brain_mode, "Auto")
        clouds = [b.display_name for b in self.cloud_brains()]
        local = self.engine.model_name.replace('.gguf', '') if self.engine.loaded else "local model not loaded"
        if clouds:  # one short line (1.38): the per-AI budgets are in AI brains, so the top bar stays clean
            spent = sum(b.budget.summary()['reserved_cents'] for b in self.cloud_brains()) / 100
            return f"AI spend this month ${spent:.2f}"
        return f"{mode} · {local}"

    @property
    def openai_brain(self):
        return self.cloud

    def _show_brain_used(self) -> None:
        last = self.brain.last
        if last.get("provider") != "local":
            self._set_status(f"Answered by {last['name']} ({last.get('note', '')})")
        self.model_label.configure(text=self.brain_label())
        if getattr(self, "lane_pill", None) is not None:  # a brain that ran out shows the next one
            self.lane_pill.configure(text=jarvis_ui.lane_text(self, self.mode))

    def show_brains(self):
        from forgemind.brain_ui import open_brains
        return open_brains(self)

    def _touch_activity(self) -> None:
        self._last_activity = time.monotonic()

    def _growth_tick(self) -> None:
        self.growth_label.configure(text="AUTO GROWTH ON · 60s idle" if self.growth.preference("enabled")
                                    else "AUTO GROWTH PAUSED")
        idle = time.monotonic() - self._last_activity >= 60
        if self._growth_restart_pending:
            if idle and not self.busy and not self._upload_running and not self._creator_operations:
                self._restart_app()
                return
        elif (idle and self.growth.preference("enabled") and not self.busy and not self.voice.enabled and getattr(self,'_research_session',None) is None
              and self.engine.loaded and not self._creator_operations and not self.input.get("1.0", "end").strip()):
            task = self.growth.claim()
            if task:
                self.start_evolution(task["goal"] + "\n\nVERIFICATION TARGET: " + task["acceptance"], growth_task_id=task["id"])
            elif not self.growth.active() and time.monotonic() >= self._next_growth_plan:
                self._plan_growth()
        self.after(3000, self._growth_tick)

    def _plan_growth(self, force: bool = False) -> None:
        if self.busy or not self.engine.loaded or (not force and not self.growth.preference("enabled")):
            return
        self._next_growth_plan = time.monotonic() + 300
        self.busy = True
        self.send_button.configure(state="disabled")
        self._set_status("Planning small upgrades from source and previous outcomes…")

        def work():
            try:
                count = self.growth.propose(self.engine, self.evolver._manifest())
                self.events.put(("growth_planned", count, ""))
            except Exception as exc:
                self.events.put(("growth_planned", 0, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def start_evolution(self, goal: str | None = None, growth_task_id: int | None = None) -> None:
        if self.busy:
            return
        if not self.engine.loaded:
            messagebox.showinfo("Load a model", "A local model must be loaded before Doxa can evolve.")
            return
        if goal is None:
            return
        goal = (goal or "").strip()
        if not goal:
            return
        self._growth_task_id = growth_task_id
        self._append("user", "EVOLUTION GOAL\n")
        self._append("body", goal + "\n\n")
        self._append("assistant", "DOXA EVOLVER\n")
        self._append(
            "body",
            "Starting a persistent research, build, repair, test, and review campaign…\n",
        )
        self.busy = True
        self.evolving = True
        self._stop_evolution.clear()
        self.send_button.configure(state="disabled")
        self._set_status("Starting evolution cycle…")
        auto_apply = self.settings_data.auto_apply_verified

        def work() -> None:
            try:
                result = self.evolver.run_until_verified(
                    goal,
                    self.engine,
                    use_research=True,
                    auto_apply=auto_apply,
                    max_attempts=self.settings_data.max_evolution_attempts,
                    progress=lambda text: self.events.put(("status", text)),
                    should_stop=self._stop_evolution.is_set,
                )
                self.events.put(("evolution_done", result))
            except Exception as exc:
                self.events.put(("error", f"Evolution failed: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    def stop_current_work(self) -> None:
        self.autopilot.configure({'enabled': False})
        if self.autopilot.active:
            self._cancel_answer.set()
        if self._research_session is not None:
            self._research_session.stop()
        self.growth.configure(enabled=False)
        if self._computer_controls is not None:
            self._computer_controls.cancel()
            self._set_status("Computer task stop requested")
            return
        if not self.evolving:
            self._set_status("Automatic growth paused")
            return
        self._stop_evolution.set()
        self._set_status("Stopping after the current model operation…")

    def rollback_evolution(self) -> None:
        if self.busy:
            return
        if not messagebox.askyesno(
            "Rollback update", "Restore the files from the most recent self-development backup?", parent=self
        ):
            return
        try:
            summary = self.evolver.rollback_last()
            self._append("assistant", "EVOLUTION ROLLBACK\n")
            self._append("body", summary + "\n\nRestart Doxa to activate the restored version.\n\n")
            self._set_status("Rollback restored; restart required")
        except Exception as exc:
            self._set_status(f"Rollback failed: {exc}", error=True)

    def _restart_app(self) -> None:
        script = Path(__file__).resolve()
        subprocess.Popen([sys.executable, str(script)], cwd=script.parent,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._on_close()

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind.startswith("voice_"):
                    self._voice_event(event)
                elif kind == "token":
                    self._answer_parts.append(event[1])
                    self._append("body", event[1])
                elif kind == "status":
                    self._set_status(event[1])
                elif kind == "ui":
                    event[1]()  # a background job's result, applied on the Tk thread
                elif kind == "phone_chat":
                    self._append("user", "YOU · PHONE\n")
                    self._append("body", event[1] + "\n\n")
                    self._append("assistant", "DOXA\n")
                    self._append("body", event[2] + "\n\n")
                    self.refresh_all()
                elif kind == "phone_stop":
                    self.stop_jarvis()
                    self._set_status("Stopped from your phone")
                elif kind == "browser_done":
                    result = event[1] or {}
                    label = {"completed": "Done", "needs_input": "Needs you", "stopped": "Stopped",
                             "error": "Could not finish"}.get(result.get("status"), result.get("status", ""))
                    summary = f"Browser task · {label}: {result.get('message', '')}"
                    self.db.add_message("user", "[Browser task] " + str(result.get("task", "")))
                    self.db.add_message("assistant", summary)
                    self._append("assistant", "DOXA\n")
                    self._append("body", summary + "\n\n")
                    if self.voice.enabled:
                        self.voice.speak(summary)
                    self._set_status(summary[:120])
                    self.refresh_all()
                elif kind == "pacifica_offer":
                    self.offer_quote(event[1], event[2], source="YOU · PHONE")
                elif kind == "pacifica_status":
                    status_var = getattr(self, "_pacifica_status", None)
                    if status_var is not None:
                        status_var.set(event[1])
                elif kind == "pacifica_done":
                    self.db.add_message("assistant", event[2])
                    self._append("assistant", "DOXA\n")
                    self._append("body", event[2] + "\n\n")
                    self._set_status(event[2][:120], error=event[1] is False)  # None = owner cancelled
                    if self.voice.enabled and event[1]:
                        self.voice.speak("The quote request is in Pacifica.")
                    self.refresh_all()
                elif kind == "growth_planned":
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self._set_status(f"Growth planner queued {event[1]} upgrades" if not event[2]
                                     else "Growth planner needs attention: " + event[2])
                elif kind == "progress":
                    self.progress.configure(value=event[1])
                elif kind == "index_file":
                    self._set_status(f"Indexing: {event[1]}")
                elif kind == "model_loaded":
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self._set_status("Model ready")
                    self.settings_data.model_path = self.engine._path
                    self.settings_data.save()
                    self.progress.configure(value=0)
                    self.refresh_all()
                    if not self._resume_checked:
                        self._resume_checked = True
                        pending_goal = self.evolver.pending_goal()
                        queue_owns_campaign = pending_goal and any(
                            pending_goal.startswith(task["goal"]) for task in self.growth.tasks()
                        )
                        if pending_goal and not queue_owns_campaign and not self.growth.active():
                            self._append("assistant", "DOXA EVOLVER\n")
                            self._append("body", "Resuming an interrupted evolution campaign…\n\n")
                            self.start_evolution(pending_goal)
                elif kind == "downloaded":
                    self.busy = False
                    self.progress.configure(value=100)
                    self._set_status("Download complete; loading model…")
                    self._load_model(event[1])
                elif kind == "indexed":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.busy = False
                    self._set_status(f"Indexed {event[1]} files; {event[2]} unchanged/skipped")
                    self.refresh_all()
                elif kind == "github_connected":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    repository_url, snapshot, indexed, skipped = event[1:]
                    if repository_url not in self.settings_data.github_repositories:
                        self.settings_data.github_repositories.append(repository_url)
                    if snapshot not in self.settings_data.knowledge_sources:
                        self.settings_data.knowledge_sources.append(snapshot)
                    self.settings_data.save()
                    self.busy = False
                    self._set_status(f"GitHub connected: {indexed} files indexed; {skipped} skipped")
                    self.refresh_all()
                elif kind == "links_imported":
                    stored, discovered = event[1], event[2]
                    self.busy = False
                    self.send_button.configure(state="normal")
                    summary = (
                        f"Opened and indexed {stored} of {discovered} supplied links. "
                        "Pages that require a login, reject automated retrieval, or failed to load were skipped."
                    )
                    self.db.add_message("assistant", summary)
                    self._append("assistant", "DOXA INTERNET\n")
                    self._append("body", summary + "\n\n")
                    self._set_status("Ready")
                    self.refresh_all()
                    self.input.focus_set()
                elif kind == "answer_done":
                    answer = "".join(self._answer_parts).strip()
                    source_text = ""
                    if self._last_web:
                        source_text = "\n\nSources:\n" + "\n".join(
                            f"[{i}] {r.title} — {r.url}" for i, r in enumerate(self._last_web, 1)
                        )
                        self._append("muted", source_text)
                    self._append("body", "\n\n")
                    if self._cancel_answer.is_set():
                        self._append("muted", "[Stopped]\n\n")
                    if answer: self.db.add_message("assistant", answer + source_text)
                    if self._voice_turn and not self._cancel_answer.is_set() and self.voice.enabled:
                        self.voice.speak(answer)
                    self._voice_turn = False
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self._set_status("Ready")
                    self.refresh_all()
                    self.input.focus_set()
                elif kind == "evolution_done":
                    result: EvolutionResult = event[1]
                    automatic = self._growth_task_id is not None
                    if automatic:
                        self.growth.finish(self._growth_task_id, result)
                        self._growth_task_id = None
                    self.busy = False
                    self.evolving = False
                    self.send_button.configure(state="normal")
                    changed = ", ".join(result.changed_files) or "none"
                    details = (
                        f"Status: {result.status}\n"
                        f"Verification: {'passed' if result.tests_passed else 'failed'}\n"
                        f"Review score: {result.review_score}/100\n"
                        f"Campaign attempts: {result.attempts}\n"
                        f"Changed files: {changed}\n"
                        f"Summary: {result.summary}\n"
                        f"Audit report: {result.report_path}\n"
                        f"Campaign record: {result.campaign_path}\n"
                    )
                    self._append("body", details + "\n")
                    self.db.add_message("assistant", "Doxa self-development result:\n" + details)
                    if result.applied:
                        self._set_status("Verified update installed; restart required")
                        if automatic:
                            self._growth_restart_pending = True
                            self._set_status("Growth update installed; restarting when idle to load it")
                            continue
                        if messagebox.askyesno(
                            "Verified update installed",
                            "The candidate passed verification and was installed with a rollback snapshot. Restart now?",
                            parent=self,
                        ):
                            self._restart_app()
                            return
                    else:
                        self._set_status(
                            f"Evolution {result.status}",
                            error=result.status in {"rejected", "blocked", "needs_input"},
                        )
                elif kind == "error":
                    if self._growth_task_id is not None:
                        self.growth.finish(self._growth_task_id, {"status": "error", "summary": event[1],
                                                               "tests_passed": False, "applied": False})
                        self._growth_task_id = None
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.busy = False
                    self.evolving = False
                    self.send_button.configure(state="normal")
                    self._set_status(event[1], error=True)
                    self._append("error", f"\n{event[1]}\n\n")
        except queue.Empty:
            pass
        self.after(50, self._drain_events)

    def _on_close(self) -> None:
        self._closing = True
        if getattr(self, "_hq_page", None) is not None:
            self._hq_page.close()
        if getattr(self, 'business_connections', None) is not None:
            self.business_connections.stop.set()
        self._cancel_answer.set()
        self.voice.disable()
        self._stop_evolution.set()
        if self._research_session is not None:
            self._research_session.stop()
            self._research_session.tick()
            if self._research_session.active:
                self._set_status("Saving training checkpoint before closing…")
                self.after(250, self._on_close)
                return
            self._research_session = None
        controller = getattr(self, "browser_controller", None)
        if controller is not None and controller.running:
            controller.stop()
            self._set_status("Stopping the browser task before closing…")
            self.after(200, self._on_close)
            return
        if getattr(self, "phone_tunnel", None) is not None:
            self.phone_tunnel.stop()
        if getattr(self, "phone_server", None) is not None:
            self.phone_server.stop()
        if self._computer_controls is not None:
            self._computer_controls.cancel()
            self._set_status("Stopping computer control before closing…")
            self.after(100, self._on_close)
            return
        if self.settings_data.backup_folder:
            try:
                self.db.backup_to(Path(self.settings_data.backup_folder) / "ForgeMindBackups")
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    ForgeMindApp().mainloop()
