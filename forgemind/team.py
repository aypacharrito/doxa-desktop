"""Doxa Team: a marketing team of AI workers with the owner as the approval gate (like the "only human in my company"
reels the owner sent on 2026-11-08 — Research → Writers' Room → Your approval → Film → Edit → Shipping → Mailroom →
Analyst, each room with its worker and a live count).

Real jobs only: a room shows a count because a worker produced an artifact (a brief, a script, a receipt), never as
decoration. Research and the Writers' Room and the Analyst use Doxa's brains (Claude with web search for research);
the owner films, posts and enters results (no auto-posting yet — that needs connected accounts and his OK per post);
Edit Bay and Mailroom are marked "not automated yet". Everything is saved under Documents\\Doxa Team\\<campaign> and
lessons go to the shared Doxa Knowledge file.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

WORK_ROOT = Path.home() / "Documents" / "Doxa Team"
ART_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
ART_PROMPTS = """# Doxa HQ characters (make them in Higgsfield, or any image AI)

Save each picture in this folder with the name on the left (png, jpg or webp; portrait 3:4 works best). Doxa HQ shows
it on that island within a few seconds. Delete a file to go back to the built-in robot.

Style for all of them (paste first): original robot character, full body, standing, dark gothic cartoon style, bold black
ink outlines, black / bone-white / blood-red palette with a little mustard yellow, jagged shapes, spooky city at night
behind it, big crescent moon, dramatic pose, high contrast, 3:4 portrait, no text, no logos.

- prime.png — Doxa, the commander: tall slim robot in a long black coat with a high collar, white faceplate with a calm
  glowing red eye slit, a staff topped with a glowing crescent, thin cables from its back to floating screens.
- marketing.png — Nova & Quill, the marketing studio: two robots back to back, one with a ghostly guardian spirit rising
  behind it and a camera, the other in a black cap and long coat holding a quill, video thumbnails flying around them.
- stores.png — Scout, the AI Stores warehouse: stocky robot shopkeeper with a striped awning hat, stacks of product
  boxes and printed shirts/mugs, a glowing online-store window behind it, a little shopping cart drone.
- trading.png — Oracle, the trading lab: elegant robot with a white skull mask and three stripes on one side of its head,
  candlestick charts glowing around it, perfectly symmetrical pose (paper money, no real brand logos).
- lab.png — Tinker, the research lab: patched-together mad-scientist robot with stitches and a big bolt through its head,
  bubbling flasks and blueprints of itself on the wall.
- code.png — Smith, the code forge: lean robot with one arm a giant red-and-black scythe, sparks and lines of code flying.
- knowledge.png — Archive, the knowledge vault: tall librarian robot with glowing book pages orbiting it.
- desk.png — You, the boss: robot with a gold crown and gold visor at a throne-like desk, a red APPROVE stamp in hand.
- stenos.png — Scribe, the Web Studio warehouse: precise court-reporter robot at a small stenotype machine on a stand,
  paper tape curling out, a glowing padlock on its chest (private, runs on the owner's own computer).
- reverse.png — Cipher, the Reverse Engineering island: sly robot with glowing pink goggles and a magnifying glass,
  circuit boards and an opened car dashboard screen, decompiled code floating around.
- pacifica.png — Shield, the Pacifica warehouse: armored guardian robot with a big shield, calm and protective,
  a stack of quote papers and a phone showing a verification code.
- arbitrage.png — Flip, the AI Arbitrage warehouse: sharp dealer robot in a tall black hat with a red band, flipping a
  gold coin over one hand, BUY and SELL price tags floating on either side.
"""

ROOMS = [  # key, room, worker, what it does
    ("research", "Research", "Nova", "Finds what's working now: competitor posts, trends, hooks, with links."),
    ("writers", "Writers' Room", "Quill", "Turns research into distinct angles, hooks and short scripts."),
    ("approval", "Your approval", "You", "Nothing gets filmed or posted without your OK."),
    ("film", "Film Studio", "You", "You film the approved scripts; mark each one filmed."),
    ("edit", "Edit Bay", "Cut", "Not automated yet: captions and cover text are in each script."),
    ("shipping", "Shipping Dock", "You", "Post it, then paste the link: a post only counts with a link."),
    ("mailroom", "Mailroom", "Echo", "Not automated yet: connect Instagram/TikTok in Plugins first."),
    ("analyst", "Analyst", "Ledger", "Reads your results, picks the next experiment, saves lessons."),
]

ART_KEYS = ({"prime", "marketing", "stores", "trading", "arbitrage", "insurance", "reverse", "stenos", "lab", "code",
             "knowledge", "desk", "pacifica"}
            | {key for key, *_ in ROOMS})

RESEARCH_PROMPT = """You are Nova, the research desk of the owner's marketing team.
Campaign: {name}
Goal: {goal}
Audience: {audience}
Platforms: {platforms}
Offer / link: {offer}

Research what is working RIGHT NOW for this goal (search the web, read real pages, use dated sources). Deliver:
1. 8-12 teardowns of real recent posts/creators/campaigns that got unusual attention in this space: link, what the hook
   was (first 2 seconds/line), format, why it worked, what's reusable (the pattern, never their actual content).
2. The 5 strongest hook patterns and 3 formats to test, ranked, each with the evidence behind it.
3. What to avoid (saturated angles, platform rules, claims that get flagged).
4. Open questions and what's unverified.
Be specific and cite links. End with a one-paragraph brief for the Writers' Room."""

WRITERS_PROMPT = """You are Quill, the writers' room of the owner's marketing team. Write {count} short-form video scripts
(15-45 s) for this campaign, from the research brief below.

Campaign: {name} — Goal: {goal} — Audience: {audience} — Platforms: {platforms} — Offer/link: {offer}
the owner's core rules: {rules}

Research brief:
{brief}

Make them genuinely different: at least 3 distinct angles, 2 hooks each. Original work only (patterns, not copies).
Reply with ONLY a JSON array, each item:
{{"angle": "...", "hook": "first line / first 2 seconds, on-screen text too", "script": "beat by beat, with what to
show", "cta": "...", "caption": "post caption", "hashtags": ["..."], "film_notes": "how to film it on a phone",
"why": "which research evidence it builds on"}}"""

ANALYST_PROMPT = """You are Ledger, the analyst of the owner's marketing team. Campaign: {name} — Goal: {goal}.
Posted videos and their real results (missing numbers are unknown, NOT zero):
{results}

1. What worked and what didn't, by hook/angle/format and by which AI wrote it ("written_by") — only claims the
   numbers support; say when there's too little data.
2. ONE next experiment (change one main thing), and which scripts to make next.
3. Up to 3 lessons worth saving for all of the owner's AIs, as JSON at the very end on its own line:
LESSONS: [{{"title": "...", "lesson": "what to do differently and why", "tags": ["marketing"]}}]"""


def slug(text: str) -> str:
    return re.sub(r"[^\w]+", "-", (text or "").lower()).strip("-")[:40] or "campaign"


def _json_array(text: str) -> list:
    first, last = text.find("["), text.rfind("]")
    if first < 0 or last < first:
        raise ValueError("The writers' room didn't return scripts in the expected format.")
    data = json.loads(text[first:last + 1])
    if not isinstance(data, list):
        raise ValueError("Scripts weren't a list.")
    return [item for item in data if isinstance(item, dict) and item.get("hook") and item.get("script")]


class TeamStore:
    """team.json in Doxa's data folder: campaigns, scripts (with stages and receipts) and each worker's status."""

    def __init__(self, path: Path, work_root: Path = WORK_ROOT):
        self.path, self.work_root = Path(path), Path(work_root)
        self.lock = threading.RLock()
        self.data = {"campaigns": [], "items": [], "workers": {}, "active": ""}
        try:
            self.data.update(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
            tmp.replace(self.path)

    # --- campaigns ---------------------------------------------------------------------------------------
    def create_campaign(self, name, goal, audience="", platforms="TikTok, Instagram Reels, YouTube Shorts", offer=""):
        name = " ".join((name or "").split())[:80]
        goal = " ".join((goal or "").split())[:300]
        if not name or not goal:
            raise ValueError("A campaign needs a name and one measurable goal.")
        campaign = {"id": uuid.uuid4().hex[:10], "name": name, "goal": goal, "audience": audience.strip()[:300],
                    "platforms": platforms.strip()[:200], "offer": offer.strip()[:300], "created": time.time(),
                    "brief": "", "brief_path": "", "sources": 0, "analysis": ""}
        with self.lock:
            self.data["campaigns"].append(campaign)
            self.data["active"] = campaign["id"]
            self.save()
        self.folder(campaign).mkdir(parents=True, exist_ok=True)
        return campaign

    def campaign(self, campaign_id=None):
        wanted = campaign_id or self.data.get("active")
        return next((c for c in self.data["campaigns"] if c["id"] == wanted), None)

    def folder(self, campaign) -> Path:
        return self.work_root / slug(campaign["name"])

    def items(self, campaign_id=None, stage=None):
        cid = campaign_id or self.data.get("active")
        return [i for i in self.data["items"] if i["campaign"] == cid and (stage is None or i["stage"] == stage)]

    def item(self, item_id):
        return next((i for i in self.data["items"] if i["id"] == item_id), None)

    # --- the approval gate and receipts (the owner's actions) ----------------------------------------------------
    def decide(self, item_id, approve: bool, note: str = ""):
        with self.lock:
            item = self.item(item_id)
            if not item or item["stage"] != "waiting":
                raise ValueError("That script isn't waiting for approval.")
            item["stage"] = "approved" if approve else "rejected"
            item["note"] = note.strip()[:300]
            item["decided"] = time.time()
            self.save()
        return item

    def mark_filmed(self, item_id, clip=""):
        with self.lock:
            item = self.item(item_id)
            if not item or item["stage"] != "approved":
                raise ValueError("Only approved scripts can be marked filmed.")
            item.update(stage="filmed", clip=clip.strip()[:500], filmed=time.time())
            self.save()
        return item

    def mark_posted(self, item_id, platform, link):
        link = (link or "").strip()
        if not re.match(r"^https?://\S+$", link):
            raise ValueError("Paste the post's link: a post only counts with a receipt.")
        with self.lock:
            item = self.item(item_id)
            if not item or item["stage"] not in ("filmed", "posted"):
                raise ValueError("Film it first, then post it.")
            item.setdefault("posts", []).append({"platform": (platform or "").strip()[:40], "link": link,
                                                 "at": time.time(), "results": {}})
            item["stage"] = "posted"
            self.save()
        return item

    def record_results(self, item_id, post_index, results: dict):
        allowed = ("views", "likes", "comments", "shares", "saves", "follows", "clicks", "sales", "revenue", "watch_pct")
        with self.lock:
            item = self.item(item_id)
            posts = (item or {}).get("posts") or []
            if not 0 <= post_index < len(posts):
                raise ValueError("No such post.")
            for key, value in results.items():
                if key in allowed and value not in (None, ""):
                    posts[post_index]["results"][key] = float(value)
            self.save()
        return item

    # --- worker status ---------------------------------------------------------------------------------------
    def set_worker(self, room, status, detail=""):
        with self.lock:
            self.data["workers"][room] = {"status": status, "detail": detail[:200], "at": time.time()}
            self.save()

    def counts(self, campaign_id=None) -> dict:
        items = self.items(campaign_id)
        campaign = self.campaign(campaign_id) or {}
        by = lambda stage: sum(1 for i in items if i["stage"] == stage)
        posts = [p for i in items for p in i.get("posts", [])]
        return {"research": campaign.get("sources", 0), "writers": len(items), "approval": by("waiting"),
                "film": by("approved"), "edit": by("filmed"), "shipping": len(posts), "mailroom": 0,
                "analyst": sum(1 for p in posts if p["results"])}

    @property
    def art_dir(self) -> Path:
        return self.work_root / "characters"

    def characters(self) -> dict:
        """{room key: file mtime} for the character pictures the owner added (Doxa HQ shows them instead of robots)."""
        folder = self.art_dir
        found = {}
        if folder.is_dir():
            for path in folder.iterdir():
                if path.suffix.lower() in ART_TYPES and path.stem.lower() in ART_KEYS and path.stat().st_size < 15_000_000:
                    found[path.stem.lower()] = int(path.stat().st_mtime)
        return found

    def character(self, key: str):
        """(bytes, mime) of one character picture, or None."""
        key = (key or "").lower()
        if key not in ART_KEYS:
            return None
        for suffix, mime in ART_TYPES.items():
            path = self.art_dir / f"{key}{suffix}"
            if path.is_file() and path.stat().st_size < 15_000_000:
                return path.read_bytes(), mime
        return None

    def ensure_art_folder(self) -> Path:
        self.art_dir.mkdir(parents=True, exist_ok=True)
        prompts = self.art_dir / "HIGGSFIELD PROMPTS.md"
        if not prompts.exists() or "reverse.png" not in prompts.read_text("utf-8", errors="replace"):
            prompts.write_text(ART_PROMPTS, "utf-8")  # first time, or the old room-based version
        return self.art_dir

    def platforms(self, campaign_id=None) -> dict:
        """Posts per platform for the HQ's Shipping Dock: {"tiktok": n, "reels": n, "shorts": n, "other": n}."""
        out = {"tiktok": 0, "reels": 0, "shorts": 0, "other": 0}
        for item in self.items(campaign_id):
            for post in item.get("posts", []):
                name = f"{post.get('platform', '')} {post.get('link', '')}".lower()
                bucket = ("tiktok" if "tiktok" in name else "reels" if re.search(r"insta|reel|\big\b", name)
                          else "shorts" if re.search(r"youtu|short", name) else "other")
                out[bucket] += 1
        return out


# Which models staff each AI room, in order of preference (the owner 2026-11-08: "spread out workflows" across Claude,
# ChatGPT, Gemini and Kimi). Research uses up to two researchers (Gemini sweeps Google Search, Claude reads deeply);
# the Writers' Room splits the scripts between up to two writers so their work can be compared by real results;
# the Analyst is one careful model.
# OpenCode Go (flat $10/month, Kimi inside) writes before pay-per-use Kimi; both are Kimi, so only one of them is used.
STAFF = {
    "research": (["gemini", "claude", "openai", "opencode", "kimi"], 2),
    "writers": (["opencode", "kimi", "claude", "openai", "gemini"], 2),
    "analyst": (["claude", "openai", "opencode", "kimi", "gemini"], 1),
}
NAMES = {"claude": "Astra (Claude)", "openai": "Atlas (OpenAI)", "gemini": "Iris (Gemini)",
         "kimi": "Kiro (Kimi)", "opencode": "Forge (OpenCode Go)"}
SAME = {"opencode": "kimi", "kimi": "opencode"}  # never staff a room with both (same model family twice)


def staff_for(room: str, brains: dict, choice: str = "auto") -> list:
    """[(provider_id, brain)] for a room: the owner's pick (Settings.team_models) when connected, else STAFF order."""
    order, size = STAFF.get(room, ([], 0))
    if choice and choice != "auto" and brains.get(choice) is not None:
        return [(choice, brains[choice])]
    crew = []
    for name in order:
        if brains.get(name) is not None and SAME.get(name) not in [n for n, _ in crew]:
            crew.append((name, brains[name]))
    return crew[:size]


class TeamRunner:
    """Runs the AI rooms in the background (one job per room at a time)."""

    def __init__(self, store: TeamStore, brain_for, notify=None, on_change=None, knowledge_add=None, rules=None,
                 choices=None):
        self.store = store
        self.brain_for = brain_for      # () -> {"claude"|"openai"|"gemini"|"kimi": connected brain}
        self.choices = choices or (lambda: {})  # () -> {room: "auto"|provider id}
        self.notify = notify or (lambda text: None)
        self.on_change = on_change or (lambda: None)
        self.knowledge_add = knowledge_add
        self.rules = rules or (lambda: "")
        self.busy: set[str] = set()

    def start(self, room: str, **options) -> None:
        jobs = {"research": self._research, "writers": self._writers, "analyst": self._analyst}
        if room not in jobs:
            raise ValueError("That room isn't automated yet.")
        if room in self.busy:
            raise ValueError("That room is already working.")
        campaign = self.store.campaign()
        if not campaign:
            raise ValueError("Start a campaign first.")
        self.busy.add(room)
        with self.store.lock:  # Prime's clock: when each room last started for this campaign (manual runs count too)
            self.store.data.setdefault("prime", {}).setdefault("last", {})[f"{campaign['id']}:{room}"] = time.time()
            self.store.save()
        self.store.set_worker(room, "working", "Starting…")
        self.on_change()
        threading.Thread(target=self._run, args=(room, jobs[room], campaign, options), daemon=True,
                         name=f"doxa-team-{room}").start()

    def _run(self, room, job, campaign, options):
        try:
            detail = job(campaign, **options)
            self.store.set_worker(room, "done", detail)
            self.notify(f"Team · {dict((k, n) for k, n, _w, _d in ROOMS)[room]}: {detail}")
        except Exception as exc:
            self.store.set_worker(room, "problem", str(exc)[:200])
            self.notify(f"Team · {room} had a problem: {exc}")
        finally:
            self.busy.discard(room)
            self.on_change()

    def staff(self, room) -> list:
        try:
            brains = self.brain_for() or {}
        except Exception:
            brains = {}
        return staff_for(room, brains, (self.choices() or {}).get(room, "auto"))

    def models(self) -> dict:
        """Room → the models working it right now, e.g. {"research": ["Gemini", "Claude"]} (shown in the HQ)."""
        return {room: [NAMES.get(name, name) for name, _ in self.staff(room)] for room in STAFF}

    def _crew(self, room) -> list:
        crew = self.staff(room)
        if not crew:
            raise ValueError("The team needs an AI brain connected: Claude, ChatGPT, Gemini or Kimi "
                             "(Settings → AI brains).")
        return crew

    def _ask(self, prompt, *, research=False, effort="medium", max_tokens=8000, brain=None, room="research") -> str:
        if brain is None:
            brain = self._crew(room)[0][1]
        agentic = hasattr(brain, "agent_stream")
        system = "You work on the owner's marketing team. Be concrete, cite sources, never invent numbers."
        try:
            rules = self.rules() or ""
        except Exception:
            rules = ""
        if rules:  # every worker, whatever model, follows the shared Doxa Knowledge core rules
            system += "\n\nThe owner's core business rules (shared by all his AIs):\n" + rules[:2500]
        if research and getattr(brain, "provider_id", "") == "gemini":  # Google Search grounding, sources appended
            return "".join(brain.chat_stream(system, [{"role": "user", "content": prompt}], effort=effort,
                                             max_tokens=max_tokens, search=True))
        if research and agentic:
            class NoTools:  # web search + fetch only (server-side); no PC tools for the research desk
                specs = []

                @staticmethod
                def execute(name, data):
                    raise ValueError("No PC tools in research.")
            return "".join(brain.agent_stream(system, [{"role": "user", "content": prompt}], NoTools(), effort="high",
                                              on_status=lambda s: self.store.set_worker("research", "working", s)))
        return "".join(brain.chat_stream(system, [{"role": "user", "content": prompt}], effort=effort,
                                         max_tokens=max_tokens))

    def _research(self, campaign):
        crew, parts, problems = self._crew("research"), [], []
        for name, brain in crew:
            self.store.set_worker("research", "working", f"{NAMES.get(name, name)} is researching…")
            try:
                parts.append((name, self._ask(RESEARCH_PROMPT.format(**campaign), research=True, brain=brain)))
            except Exception as exc:  # one researcher failing (quota, key) doesn't sink the brief
                problems.append(f"{NAMES.get(name, name)}: {exc}")
        if not parts:
            raise ValueError("; ".join(problems))
        text = parts[0][1] if len(parts) == 1 else "\n\n".join(
            f"## Researcher: {NAMES.get(name, name)}\n\n{body}" for name, body in parts)
        folder = self.store.folder(campaign)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now():%Y-%m-%d %H%M} research brief.md"
        path.write_text(f"# Research brief — {campaign['name']}\n\n{text}\n", "utf-8")
        sources = len(set(re.findall(r"https?://[^\s)\]>]+", text)))
        with self.store.lock:
            campaign = self.store.campaign(campaign["id"])
            campaign.update(brief=text[-6000:], brief_path=str(path), sources=campaign.get("sources", 0) + sources)
            self.store.save()
        by = " + ".join(NAMES.get(name, name) for name, _ in parts)
        return f"{sources} sources read by {by}; brief saved." + (f" ({'; '.join(problems)})" if problems else "")

    def _writers(self, campaign, count=6):
        if not campaign.get("brief"):
            raise ValueError("Run Research first: the writers work from its brief.")
        crew, scripts, problems = self._crew("writers"), [], []
        shares = [count // len(crew) + (1 if i < count % len(crew) else 0) for i in range(len(crew))]
        for (name, brain), share in zip(crew, shares):
            if not share:
                continue
            self.store.set_worker("writers", "working", f"{NAMES.get(name, name)} is writing {share} scripts…")
            try:
                text = self._ask(WRITERS_PROMPT.format(count=share, rules=self.rules()[:1500], **campaign),
                                 max_tokens=12000, brain=brain)
                written = [s for s in _json_array(text)[:12] if isinstance(s, dict)]
                if not written:
                    raise ValueError("no scripts in the reply")
                scripts += [dict(s, model=NAMES.get(name, name)) for s in written]
            except Exception as exc:  # one writer failing doesn't sink the room
                problems.append(f"{NAMES.get(name, name)}: {exc}")
        if not scripts:
            raise ValueError("; ".join(problems) or "No scripts came back.")
        folder = self.store.folder(campaign)
        with self.store.lock:
            for script in scripts:
                self.store.data["items"].append({
                    "id": uuid.uuid4().hex[:10], "campaign": campaign["id"], "stage": "waiting", "created": time.time(),
                    **{k: (script.get(k) if not isinstance(script.get(k), str) else script.get(k)[:3000])
                       for k in ("angle", "hook", "script", "cta", "caption", "hashtags", "film_notes", "why", "model")}})
            self.store.save()
        lines = [f"## {i + 1}. {s.get('angle', '')} ({s.get('model', '')})\n**Hook:** {s.get('hook')}\n\n{s.get('script')}\n\n**CTA:** "
                 f"{s.get('cta', '')}\n**Caption:** {s.get('caption', '')}\n**Filming:** {s.get('film_notes', '')}\n"
                 for i, s in enumerate(scripts)]
        (folder / f"{datetime.now():%Y-%m-%d %H%M} scripts.md").write_text("# Scripts\n\n" + "\n".join(lines), "utf-8")
        models = dict.fromkeys(s["model"] for s in scripts)
        by = ", ".join(f"{sum(1 for s in scripts if s['model'] == m)} by {m}" for m in models)
        return f"{len(scripts)} scripts ({by}) waiting for your approval." + (
            f" ({'; '.join(problems)})" if problems else "")

    def _analyst(self, campaign):
        rows = []
        for item in self.store.items(campaign["id"]):
            for post in item.get("posts", []):
                rows.append({"hook": item.get("hook"), "angle": item.get("angle"), "written_by": item.get("model", ""),
                             "platform": post["platform"],
                             "link": post["link"], "results": post["results"]})
        if not rows:
            raise ValueError("Post something and enter its results first.")
        text = self._ask(ANALYST_PROMPT.format(results=json.dumps(rows, ensure_ascii=False, indent=1), **campaign),
                         max_tokens=6000, room="analyst")
        saved = 0
        match = re.search(r"LESSONS:\s*(\[.*\])", text, re.S)
        if match and self.knowledge_add:
            try:
                for lesson in json.loads(match.group(1))[:3]:
                    self.knowledge_add(str(lesson.get("title", ""))[:120], str(lesson.get("lesson", "")),
                                       [str(t) for t in lesson.get("tags", [])], f"Doxa Team analyst · {campaign['name']}")
                    saved += 1
            except (ValueError, TypeError):
                pass
        with self.store.lock:
            current = self.store.campaign(campaign["id"])
            current["analysis"] = text[:8000]
            current["analysed_posts"] = len(rows)  # Prime runs the analyst again only when new results arrive
            self.store.save()
        (self.store.folder(campaign) / f"{datetime.now():%Y-%m-%d %H%M} analysis.md").write_text(text, "utf-8")
        return f"Next experiment ready; {saved} lesson(s) saved for all your AIs."


# --- Doxa: the manager on the command island ----------------------------------------------------------------
# the owner 2026-11-08: "a creative AI island … managing all the other AIs and putting them to work constantly … until we
# make a trillion dollars". Prime keeps the line moving on its own, inside the monthly AI budgets: it starts Research,
# the Writers' Room and the Analyst when they're due. It never posts, sends, spends or approves anything; the approval
# gate, filming and posting stay the owner's.
PRIME_EVERY = 60                  # monitor continuously; paid jobs still obey existing caps
RESEARCH_EVERY = 72 * 3600        # fresh research every 3 days
WRITERS_EVERY = 12 * 3600         # new scripts at most twice a day
KEEP_WAITING = 3                  # write more when fewer than this many scripts wait for the owner
MAX_RUNS_PER_DAY = 12             # the owner 2026-11-09 "don't stop until $1T": each AI's monthly budget still caps spend
MISSION_USD = 1_000_000_000_000   # the mission the owner set: a trillion dollars


class Prime:
    def __init__(self, store: TeamStore, runner: TeamRunner, enabled=lambda: True, clock=time.time, notify=None):
        self.store, self.runner, self.enabled, self.clock = store, runner, enabled, clock
        self.notify = notify or (lambda text: None)

    def _state(self) -> dict:
        state = self.store.data.setdefault("prime", {})
        state.setdefault("last", {})
        state.setdefault("log", [])
        today = time.strftime("%Y-%m-%d", time.localtime(self.clock()))
        if state.get("day") != today:
            state["day"], state["runs"] = today, 0
        return state

    def earned(self, campaign_id=None) -> float:
        return sum(float(p["results"].get("revenue", 0) or 0) for i in self.store.items(campaign_id)
                   for p in i.get("posts", []))

    def decide(self):
        """(room, reason) for the next job, or (None, what Prime is waiting on)."""
        campaign = self.store.campaign()
        if not campaign:
            return None, "Waiting for your first campaign (Team → + New campaign, or tell Doxa in chat)."
        if self.runner.busy:
            return None, "The team is working: " + ", ".join(sorted(self.runner.busy)) + "."
        if not self.runner.staff("research"):
            return None, "No AI connected: add a key in Settings → AI brains."
        last = self._state()["last"]
        now = self.clock()
        ago = lambda room: now - last.get(f"{campaign['id']}:{room}", 0)
        if not campaign.get("brief") or ago("research") > RESEARCH_EVERY:
            return "research", "the research brief is missing or more than 3 days old"
        counts = self.store.counts()
        if counts.get("approval", 0) < KEEP_WAITING and ago("writers") > WRITERS_EVERY:
            return "writers", f"only {counts.get('approval', 0)} script(s) waiting for you"
        with_results = counts.get("analyst", 0)
        if with_results > campaign.get("analysed_posts", 0):
            return "analyst", f"{with_results - campaign.get('analysed_posts', 0)} post(s) have new results"
        todo = [f"{counts.get('approval', 0)} script(s) to approve" if counts.get("approval") else "",
                f"{counts.get('film', 0)} to film" if counts.get("film") else "",
                f"{counts.get('edit', 0)} filmed and waiting to post" if counts.get("edit") else ""]
        todo = [t for t in todo if t]
        return None, "Everything's moving. " + ("Waiting on you: " + ", ".join(todo) + "." if todo else
                                                 "Next research run in under 3 days.")

    def tick(self):
        """One check. Starts at most one room; returns what it did or why not."""
        with self.store.lock:
            state = self._state()
        if not self.enabled():
            note = "Paused (Settings → AI brains → Doxa keeps the team working)."
        elif state.get("runs", 0) >= MAX_RUNS_PER_DAY:
            note = f"Done for today ({MAX_RUNS_PER_DAY} jobs started): saving budget until tomorrow."
        else:
            room, why = self.decide()
            note = why
            if room:
                worker, name = next((w, n) for k, n, w, _ in ROOMS if k == room)
                try:
                    self.runner.start(room)
                except ValueError as exc:
                    note = f"Couldn't start {name}: {exc}"
                else:
                    note = f"Sent {worker} to {name}: {why}."
                    with self.store.lock:
                        state["runs"] = state.get("runs", 0) + 1
                        state["log"] = (state["log"] + [{"at": self.clock(), "text": note}])[-30:]
                    self.notify("Doxa: " + note)
        with self.store.lock:
            state["note"], state["checked"] = note, self.clock()
            self.store.save()
        return note

    def view(self) -> dict:
        """What the HQ's command island shows."""
        with self.store.lock:
            state = self._state()
            return {"on": bool(self.enabled()), "note": state.get("note", "Starting up…"),
                    "log": [dict(x) for x in state.get("log", [])[-8:]], "runs": state.get("runs", 0),
                    "max_runs": MAX_RUNS_PER_DAY, "earned": round(self.earned(), 2), "mission": MISSION_USD}
