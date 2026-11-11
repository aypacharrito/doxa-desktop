"""What the phone can do, implemented with the desktop app's own parts.

Runs on the phone server's threads. It never touches Tk directly: anything the desktop
window should show goes through app.events, which the Tk loop drains.
"""
from __future__ import annotations

import threading

from .adaptive import should_search_web
from .browser_agent import planner_ready
from .browser_intent import browser_task_from_chat
from .code_mode import code_request
from .calendar_intent import calendar_query_day, is_calendar_request
from .calendar_ui import calendar_now, day_summary, offer_event
from .config import Settings
from .local_tools import clock_reply
from .reels import links_from_history, local_media, reel_links
from .business_connections import business_reply
from .pacifica import quote_request_from_chat
from .phone_bridge import PhoneError
from .products import hunt_request
from .sites_ui import site_request
from .tickets import ticket_request
from .web import research_web


class AppPhoneDelegate:
    def __init__(self, app):
        self.app = app
        self._chat_lock = threading.Lock()
        self._cancel = threading.Event()

    def status(self) -> dict:
        app = self.app
        return {
            "model_loaded": app.engine.loaded,
            "model": app.engine.model_name if app.engine.loaded else "",
            "pc": "PC busy" if app.busy else "PC online",
            "browser_running": app.browser_controller.running,
            "cloud_available": bool(getattr(app, 'cloud', None) and app.cloud.loaded),
            "cloud_budget": app.cloud.budget.summary() if getattr(app, 'cloud', None) else None,
            "claude_budget": app.claude.budget.summary() if getattr(app, 'claude', None) else None,
            "business": app.business_connections.snapshot() if hasattr(app,'business_connections') else {},
        }

    def history(self, limit: int) -> list[dict]:
        return [{"role": m["role"], "content": m["content"][:4000]} for m in self.app.db.recent_messages(limit)]

    def chat(self, text: str) -> dict:
        """Whole answer at once (older phone app). Streams internally."""
        final = {}
        for event in self.chat_stream(text):
            if event["type"] in ("done", "offer"):
                final = event
        if final.get("type") == "offer":
            return {"kind": "browser_offer", "task": final["task"], "reply": final["reply"]}
        return {"kind": "reply", "reply": final.get("reply", "(no answer)"), "note": final.get("note", "")}

    def chat_stream(self, text: str):
        """Validate now (errors become normal HTTP errors), then return a generator of events:
        {"type": "offer"|"token"|"done", ...}. Tokens are yielded the moment the model produces them."""
        app = self.app
        if text.startswith('OpenAI draft: '):
            prompt = text[len('OpenAI draft: '):].strip()
            if not prompt:raise PhoneError(400, 'Enter a draft request.')
            if not getattr(app, 'cloud', None) or not app.cloud.loaded:
                raise PhoneError(503, 'Connect OpenAI in Doxa Autopilot first.')
            return self._cloud_draft(prompt)
        links = reel_links(text) + local_media(text) or links_from_history(text, app.db.recent_messages(8))
        if links:
            # Downloaded and transcribed on the PC; the transcript shows up in chat history here too.
            app.events.put(("ui", lambda: app.start_reels(text, links, source="YOU · PHONE")))
            reply = ("Getting that video on your PC now. The transcript will be in this chat in about "
                     "15–40 seconds; pull to refresh.")
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        from .qr_codes import make_both, phone_reply, qr_request
        if qr_request(text):
            # Both codes, every time. From the phone the key is never replaced (that would cut this phone off).
            try:
                base = (app.phone_access.data.get("public_url", "") if app.phone_access.data.get("use_named_tunnel")
                        else getattr(app.phone_tunnel, "url", "") or "")
                reply = phone_reply(make_both(app.phone_access, base, rotate_if_missing=False))
            except Exception as exc:
                reply = f"I couldn't make both QR codes: {exc}"
            self._record(text, reply)
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        code_ask = code_request(text)
        if code_ask is not None:
            # Runs on the PC with full access; steps show in Tools → Code mode, the result lands in this chat.
            app.events.put(("ui", lambda: app.start_code_job(text, code_ask[1], None, code_ask[0], source="YOU · PHONE")))
            reply = ("Starting Code mode on your PC. It works on its own; the result will be in this chat when it's "
                     "done (pull to refresh).")
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        quote = quote_request_from_chat(text)
        if quote:
            # Never goes to the model. The confirmation card opens on the PC (the Tk loop records the chat).
            app.events.put(("pacifica_offer", text, quote))
            reply = quote.refused or ("I've put the quote request for Pacifica on your PC screen. "
                                      "It's sent only after you press Send there.")
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        niche = hunt_request(text)
        if niche is not None:
            # Runs on the PC (web research + one cloud request); the ranked list lands in this chat's history.
            app.events.put(("ui", lambda: app.start_product_hunt(text, niche, source="YOU · PHONE")))
            reply = ("Hunting for winning products on your PC now" + (f" ({niche})" if niche else "") +
                     ". The ranked list will be in this chat in about a minute; pull to refresh.")
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        ticket_ask = ticket_request(text)
        if ticket_ask is not None:
            # The photo has to be on the PC and the owner covers his license number there before anything is sent.
            app.events.put(("ui", lambda: app.offer_ticket_help(text, ticket_ask, source="YOU · PHONE")))
            reply = ("I've opened Traffic ticket on your PC. Put the ticket photo on the PC, choose it there, cover "
                     "your license number and press Read ticket. Not legal advice; I won't file, pay or send anything.")
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        site_name = site_request(text)
        if site_name is not None:
            # Footage lives on the PC, so the builder opens there.
            app.events.put(("ui", lambda: app.show_website_builder(site_name)))
            reply = ("I've opened the Website builder on your PC" + (f" for {site_name}" if site_name else "") +
                     ". Copy your footage to a folder there, fill in the facts and press Build.")
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        if is_calendar_request(text):
            # The event card opens on the PC; approval stays there. Nothing is added from here.
            connected = app.calendar.connected()
            app.events.put(("ui", lambda: offer_event(app, text, from_phone=True)))
            reply = ("I've put that event on Doxa's screen on your PC. It goes on your calendar only after "
                     "you press Yes there." if connected else
                     "Google Calendar isn't connected yet. Connect it on your PC in Settings → Google Calendar.")
            return iter([{"type": "token", "text": reply}, {"type": "done", "reply": reply, "note": ""}])
        day = calendar_query_day(text, calendar_now(app).date())
        if day:
            return self._calendar_day(text, day)
        task = browser_task_from_chat(text, app.db.recent_messages(8))
        if task:
            return iter([{"type": "offer", "task": task,
                          "reply": "That's a website task. I can do it in my own browser window on your PC."}])
        quick = (business_reply(app,text) if hasattr(app,'business_connections') else None) or clock_reply(text)
        if quick:
            self._record(text, quick)
            return iter([{"type": "token", "text": quick}, {"type": "done", "reply": quick, "note": ""}])
        brain = getattr(app, "brain", None)
        if not (brain.ready(app.settings_data) if brain else app.engine.loaded):
            raise PhoneError(503, "Doxa's model is still loading on your PC. Try again in a moment.")
        return self._stream_answer(text)

    TAKEOVER_WAIT = 20  # seconds a new message waits for the old answer to stop

    def _take_turn(self):
        """A new phone message replaces the one still being answered, like ChatGPT (the owner 2026-11-09 kept getting
        "Doxa is already answering a phone message": an answer whose phone had disconnected, or a long Claude task,
        held the lock). Taken inside the answer generator, so a generator that never starts can't leak the lock."""
        if self._chat_lock.acquire(timeout=1):
            return
        self._cancel.set()  # stop the previous answer (it saves what it had, marked [Stopped])
        if not self._chat_lock.acquire(timeout=self.TAKEOVER_WAIT):
            raise PhoneError(409, "Doxa is still finishing your last message. Tap Stop, or try again in a few seconds.")

    def _cloud_draft(self, prompt):
        self._take_turn()
        try:
            self._cancel.clear()
            yield {'type':'status', 'text':'Preparing with OpenAI within your $5 monthly cap…'}
            answer=''
            for part in self.app.cloud.stream([],prompt,None,[],[],stop_event=self._cancel):
                answer+=part
                yield {'type':'token','text':part}
            if self._cancel.is_set():answer+='\n[Stopped]'
            self._record('OpenAI draft: '+prompt,answer)
            yield {'type':'done','reply':answer,'note':'OpenAI draft · only this request was sent; no actions executed.'}
        finally:
            self._chat_lock.release()
    def _calendar_day(self, text: str, day):
        app = self.app
        if not app.calendar.connected():
            reply = "Google Calendar isn't connected yet. Connect it on your PC in Settings → Google Calendar."
        else:
            yield {"type": "status", "text": "Checking your calendar…"}
            try:
                events, error = app.calendar.events_on(day), None
            except Exception as exc:
                events, error = None, exc
            reply = day_summary(day, events, error, calendar_now(app).date())
        self._record(text, reply)
        yield {"type": "token", "text": reply}
        yield {"type": "done", "reply": reply, "note": ""}

    def _stream_answer(self, text: str):
        app = self.app
        self._take_turn()
        try:
            self._cancel.clear()
            settings = Settings(**app.settings_data.__dict__)
            history = app.db.recent_messages(12)
            memories = app.db.retrieve(text)
            web = []
            if settings.auto_research and should_search_web(text):
                yield {"type": "status", "text": "Checking the web…"}
                try:
                    web = research_web(text, max_results=5, extract_results=3)
                except Exception:
                    web = []
            run_id = app.run_journal.start("[Phone] " + text)
            parts, first = [], True
            try:
                for token in (getattr(app, "brain", None) or app.inference).stream(history, text, settings, memories, web, stop_event=self._cancel):
                    if first:
                        app.run_journal.first_response(run_id)
                        first = False
                    parts.append(token)
                    yield {"type": "token", "text": token}
            except Exception:
                app.run_journal.finish(run_id, "error", "Phone request failed.")
                raise
            app.run_journal.finish(run_id, "stopped" if self._cancel.is_set() else "complete")
            answer = "".join(parts).strip()
            if web:
                sources = "\n\nSources:\n" + "\n".join(f"[{i}] {r.title} — {r.url}" for i, r in enumerate(web, 1))
                answer += sources
                yield {"type": "token", "text": sources}
            if self._cancel.is_set():
                answer = (answer + "\n\n[Stopped]").strip()
            self._record(text, answer or "(no answer)")
            yield {"type": "done", "reply": answer or "(no answer)", "note": app.engine.model_name}
        finally:
            self._chat_lock.release()

    # --- Photos and documents from the phone ----------------------------------------------------------------
    def upload(self, name: str, data_b64: str) -> dict:
        from .attachments import save_upload
        try:
            return save_upload(name, data_b64)
        except ValueError as exc:
            raise PhoneError(400, str(exc)) from None

    # --- Talking to Doxa from the phone: record → text, reply → Doxa's voice ---------------------------------
    def transcribe(self, audio_b64: str, mime: str = "audio/mp4") -> dict:
        import base64
        from .cloud_voice import transcribe_file
        voice = getattr(self.app, "cloud_voice", None)
        if voice is None:
            raise PhoneError(503, "Voice needs OpenAI connected on your PC (Settings → AI brains).")
        try:
            data = base64.b64decode(audio_b64 or "", validate=True)
        except ValueError:
            raise PhoneError(400, "That recording didn't arrive in one piece. Try again.") from None
        ext = {"audio/mp4": "m4a", "audio/m4a": "m4a", "audio/aac": "aac", "audio/webm": "webm",
               "audio/wav": "wav", "audio/mpeg": "mp3", "audio/3gpp": "3gp"}.get(mime, "m4a")
        try:
            return {"text": transcribe_file(voice, data, f"voice.{ext}", mime or "audio/mp4")}
        except ValueError as exc:
            raise PhoneError(503, str(exc)) from None

    def speak(self, text: str) -> dict:
        import secrets
        from .cloud_voice import synthesize
        voice = getattr(self.app, "cloud_voice", None)
        if voice is None:
            raise PhoneError(503, "Voice needs OpenAI connected on your PC.")
        try:
            audio = synthesize(voice, text)
        except ValueError as exc:
            raise PhoneError(503, str(exc)) from None
        speech = getattr(self, "_speech", {})
        while len(speech) >= 6:
            speech.pop(next(iter(speech)))
        key = secrets.token_urlsafe(12)
        speech[key] = audio
        self._speech = speech
        return {"id": key}

    def speech(self, key: str) -> bytes:
        audio = getattr(self, "_speech", {}).get(key)
        if audio is None:
            raise PhoneError(404, "That audio is gone. Ask again.")
        return audio

    # --- Chats like ChatGPT: new chat, past chats --------------------------------------------------------------
    def new_chat(self) -> dict:
        started = self.app.db.new_chat()
        self.app.events.put(("ui", lambda: self.app.show_home() if hasattr(self.app, "show_home") else None))
        return {"ok": True, "started": started}

    def chats(self) -> dict:
        return {"chats": self.app.db.chats(40)}

    def chat_history(self, chat_id: int) -> dict:
        return {"messages": [{"role": m["role"], "content": m["content"][:4000]} for m in self.app.db.chat_messages(chat_id)]}

    # --- Marketing team from the phone: see the line, approve scripts ---------------------------------------
    def team_state(self) -> dict:
        store = getattr(self.app, "team", None)
        if store is None:
            return {"campaign": None, "rooms": [], "counts": {}, "workers": {}, "busy": [], "waiting": []}
        campaign = store.campaign()
        from .team import ROOMS
        rooms = [{"key": k, "room": r, "worker": w, "about": a} for k, r, w, a in ROOMS]
        try:
            models = self.app.team_runner.models()
        except Exception:
            models = {}
        try:
            from .hq_data import ISLANDS, departments
            islands = [{"key": k, "name": n, "worker": w, "about": a} for k, n, w, a in ISLANDS]
            depts = departments(self.app)
        except Exception:
            islands, depts = [], {}
        return {"rooms": rooms, "models": models, "islands": islands, "departments": depts,
                "campaign": campaign and {k: campaign[k] for k in ("id", "name", "goal")},
                "counts": store.counts() if campaign else {}, "workers": store.data.get("workers", {}),
                "platforms": store.platforms() if campaign else {},
                "characters": store.characters(),
                "prime": self.app.prime.view() if getattr(self.app, "prime", None) else None,
                "bots": self._bots(),
                "art": self._art(),
                "chats": self._chats(),
                "busy": sorted(getattr(self.app.team_runner, "busy", [])),
                "waiting": [{k: i.get(k) for k in ("id", "angle", "hook", "script", "cta", "why", "model")}
                            for i in store.items(stage="waiting")] if campaign else []}

    def _art(self):
        from . import island_art
        try:
            islands = island_art.versions()
        except OSError:
            islands = {}
        maker = getattr(self.app, "hq_art", None)
        if maker is None:
            return {"islands": islands}
        return {"running": maker.running, "status": maker.status, "missing": len(maker.missing()), "kind": maker.kind,
                "figures": maker.figures(), "figures_missing": len(maker.missing("figure")), "islands": islands}

    def team_island_art(self, size: str, key: str) -> bytes:
        from . import island_art
        found = island_art.image(key, size)
        if not found:
            raise PhoneError(404, "No art for that island.")
        return found

    def _chats(self):
        try:
            return self.app.island_chat.summary()
        except Exception:
            return {}

    def _bots(self):
        try:
            return self.app.warehouses.overview()
        except Exception:
            return None

    def hq_action(self, name: str, data: dict) -> dict:
        from .hq_data import action
        try:
            return action(self.app, name, data)
        except ValueError as exc:
            raise PhoneError(409, str(exc)) from None

    def team_figure(self, key: str) -> bytes:
        maker = getattr(self.app, "hq_art", None)
        found = maker.figure(key) if maker is not None else None
        if not found:
            raise PhoneError(404, "No 3D figure for that island.")
        return found

    def team_character(self, key: str):
        store = getattr(self.app, "team", None)
        found = store.character(key) if store is not None else None
        if not found:
            raise PhoneError(404, "No picture for that character.")
        return found

    def team_campaign(self, name: str, goal: str, audience: str = "", offer: str = "") -> dict:
        try:
            campaign = self.app.team.create_campaign(name, goal, audience, offer=offer)
        except ValueError as exc:
            raise PhoneError(400, str(exc)) from None
        self.app.events.put(("ui", lambda: getattr(self.app, "team_refresh", lambda: None)()))
        return {"ok": True, "id": campaign["id"]}

    def team_decide(self, item_id: str, approve: bool) -> dict:
        try:
            item = self.app.team.decide(item_id, approve)
        except ValueError as exc:
            raise PhoneError(409, str(exc)) from None
        self.app.events.put(("ui", lambda: getattr(self.app, "team_refresh", lambda: None)()))
        return {"ok": True, "stage": item["stage"]}

    def team_run(self, room: str) -> dict:
        try:
            self.app.team_runner.start(room)
        except ValueError as exc:
            raise PhoneError(409, str(exc)) from None
        return {"ok": True}

    # --- Code mode from the phone ----------------------------------------------------------------------------
    def code_state(self) -> dict:
        runner = getattr(self.app, "code_runner", None)
        if runner is None:
            return {"running": False, "job": None, "engines": {}}
        return runner.state()

    def code_start(self, task: str, engine: str = "auto", fresh: bool = False) -> dict:
        task = (task or "").strip()
        if not 1 <= len(task) <= 20000:
            raise PhoneError(400, "Tell Code mode what to do.")
        if engine not in ("auto", "codex", "claude"):
            raise PhoneError(400, "Unknown engine.")
        done, result = threading.Event(), {}

        def start():
            try:
                result["note"] = self.app.start_code_job(task, task, None, engine, source="YOU · PHONE",
                                                         follow_up=False if fresh else None)
            except Exception as exc:
                result["error"] = str(exc)
            done.set()
        self.app.events.put(("ui", start))
        if not done.wait(20):
            return {"ok": True, "note": "Starting Code mode on your PC…"}
        if "error" in result:
            raise PhoneError(409, result["error"])
        return {"ok": True, "note": result["note"]}

    def code_stop(self) -> dict:
        runner = getattr(self.app, "code_runner", None)
        return {"ok": bool(runner and runner.stop())}

    def screen_jpeg(self, width: int = 1280, quality: int = 55) -> bytes:
        """A live picture of the PC's main screen for the phone's Screen view (view only)."""
        import io
        from PIL import ImageGrab
        width = max(320, min(int(width or 1280), 2560))
        image = ImageGrab.grab()
        if image.width > width:
            image = image.resize((width, max(1, round(image.height * width / image.width))))
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=max(30, min(int(quality or 55), 85)), optimize=True)
        return out.getvalue()

    def push_register(self, token: str) -> dict:
        self.app.phone_access.add_push_token(token)
        return {"ok": True}

    def _record(self, text: str, answer: str) -> None:
        self.app.db.add_message("user", text)
        self.app.db.add_message("assistant", answer)
        self.app.events.put(("phone_chat", text, answer))

    def browser_start(self, task: str) -> dict:
        app = self.app
        if not planner_ready(getattr(app, "brain", None), app.settings_data, app.engine):
            raise PhoneError(503, "Doxa's model is still loading on your PC (or connect Claude/OpenAI).")
        if getattr(app, "_computer_controls", None):
            raise PhoneError(409, "Screen control is running on your PC. Wait for it to finish.")
        app.browser_controller.start(task)
        app.events.put(("status", "Browser task started from your phone"))
        return {"ok": True}

    def browser_state(self) -> dict:
        return self.app.browser_controller.state()

    def browser_respond(self, request_id: str, value) -> bool:
        return self.app.browser_controller.respond(request_id, value)

    def stop(self) -> None:
        self._cancel.set()
        self.app.browser_controller.stop()
        self.app.events.put(("phone_stop",))
