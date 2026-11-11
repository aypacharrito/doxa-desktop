"""Doxa HQ islands = the owner's money lines and functions (the owner 2026-11-09: "we need islands not all for a specific
thing but different islands for different functions … our main money goals are AI dropshipping stores, like the Etsy
one, and AI trading"). The marketing video line is now one island (Marketing Studio) instead of eight.

`departments(app)` gathers each island's live numbers from what Doxa already has (never fails: a broken source shows
as unavailable). `action(app, name, data)` runs the island buttons. Nothing here posts, sends, spends or trades.
"""
from __future__ import annotations

import re
from pathlib import Path

# key, island name, worker, what it does. The first five are warehouses (the owner 2026-11-09: "every one of these things
# should have a warehouse"), each with a free research bot that keeps working (forgemind/warehouses.py).
ISLANDS = [
    ("stores", "Stores", "Scout", "AI dropshipping, Etsy print-on-demand and Shopify stores: products, designs, listings, store pages."),
    ("trading", "Trading", "Oracle", "Trading research and paper trading with fake money and recorded real prices. No broker, no real orders."),
    ("arbitrage", "Arbitrage", "Flip", "Buy low, sell high with AI: AI services for businesses, online and retail arbitrage, digital assets."),
    ("pacifica", "Insurance", "Shield", "Insurance agency: carriers, leads, faster quotes. Doxa drafts quote requests in your CRM; you send them."),
    ("marketing", "Marketing Studio", "Nova & Quill", "Research, scripts (Doxa approves them), your filming, posting and results — one campaign at a time."),
    ("stenos", "Web Studio", "Scribe", "Web studio: websites and apps for clients, care plans $99 / $249 / $499 a month."),
    ("websites", "Websites", "Builder", "Sites and stores Doxa builds, and where to host them cheaply (own domains, free hosting)."),
    ("reverse", "Reverse Engineering", "Cipher", "Take anything apart to change it: your car's head unit (CarPlay / Android Auto), game mods, any program."),
    ("lab", "Research Lab", "Tinker", "Upgrade ideas for Doxa itself. Doxa approves them and builds the good ones in a safe copy."),
    ("code", "Code Forge", "Smith", "Codex and Claude Code building and fixing things on your laptop."),
    ("knowledge", "Knowledge Vault", "Archive", "The shared lessons every one of your AIs reads before it advises you."),
]
WAREHOUSE_KEYS = ("stores", "trading", "arbitrage", "pacifica", "marketing", "stenos")


def _safe(fn, fallback):
    try:
        return fn()
    except Exception:
        return fallback


def _marketing(app):
    team = app.team
    campaign = team.campaign()
    counts = team.counts() if campaign else {}
    return {"count": counts.get("writers", 0), "label": campaign["name"] if campaign else "No campaign yet",
            "busy": bool(getattr(app.team_runner, "busy", None)), "waiting": counts.get("approval", 0),
            "posts": counts.get("shipping", 0)}


def _stores(app):
    data = app.products.load()
    products = data.get("products", [])
    by = lambda status: [p for p in products if p.get("status") == status]
    sites_root = Path.home() / "Documents" / "Doxa Sites"
    sites = sum(1 for p in sites_root.iterdir() if p.is_dir()) if sites_root.is_dir() else 0
    top = sorted(by("winner") + by("testing") + by("new"), key=lambda p: (p.get("status") != "winner",
                                                                       p.get("status") != "testing", -p.get("score", 0)))
    return {"count": len(products), "hunts": len(data.get("hunts", [])), "testing": len(by("testing")),
            "winners": len(by("winner")), "sites": sites, "busy": bool(getattr(app, "_hunting", False)),
            "top": [{"name": p.get("name", ""), "status": p.get("status", ""), "score": p.get("score", 0)} for p in top[:6]]}


def _trading(app):
    from .paper_trading import PaperBook
    path = Path(getattr(app.brain.tools, "notes_dir", Path.home() / "Documents" / "Doxa Notes")) / "paper-trading.sqlite3"
    if not path.is_file():
        return {"count": 0, "cash": 10000.0, "realized": 0.0, "positions": {}, "fills": 0}
    report = PaperBook(path).report()
    positions = {s: round(p["quantity"], 4) for s, p in report["positions"].items() if p["quantity"] > 1e-9}
    return {"count": len(report["fills"]), "cash": round(report["cash"], 2), "realized": round(report["realized_pnl"], 2),
            "positions": positions, "fills": len(report["fills"])}


def _websites(app):
    publisher = getattr(app, "publisher", None)
    if publisher is not None:
        view = publisher.view()
        return {"count": len(view["sites"]), "sites": [s["name"] for s in view["sites"]][-8:], "publish": view}
    root = Path.home() / "Documents" / "Doxa Sites"
    sites = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    return {"count": len(sites), "sites": sites[-8:]}


def _lab(app):
    lab = app.upgrades
    store = lab.store
    waiting = store.waiting()
    decided = [p for p in store.data["proposals"] if p["status"] != "waiting"][-6:]
    return {"count": len(waiting), "busy": lab.busy or lab._reviewing, "status": store.data.get("status", ""),
            "auto_on": bool(lab.auto()), "auto": store.data.get("auto") or {},
            "proposals": [{k: p.get(k) for k in ("id", "title", "island", "why", "prompt", "sources", "note")} for p in waiting],
            "recent": [{k: p.get(k) for k in ("title", "status", "note")} for p in reversed(decided)]}


def _code(app):
    state = app.code_runner.state() if getattr(app, "code_runner", None) else {}
    job = state.get("job") or {}
    running = job.get("status") == "running"
    return {"count": 1 if running else 0, "busy": running, "task": (job.get("task") or "")[:300],
            "status": job.get("status", "idle"), "engine": job.get("name", "")}


def _knowledge(app):
    from . import knowledge
    text = Path(knowledge.LESSONS).read_text("utf-8")
    titles = re.findall(r"^### [^·\n]*·[^·\n]*·\s*(.+)$", text, re.M)
    return {"count": len(titles), "latest": titles[-6:][::-1]}


def _insurance(app):
    connected = bool(getattr(app.settings_data, "pacifica_url", ""))
    return {"count": 0, "connected": connected, "address": getattr(app.settings_data, "pacifica_url", "")}


def _bot(app, key):
    return app.warehouses.view(key)


def departments(app) -> dict:
    out = {
        "marketing": _safe(lambda: _marketing(app), {"count": 0, "label": "unavailable"}),
        "stores": _safe(lambda: _stores(app), {"count": 0, "top": []}),
        "trading": _safe(lambda: _trading(app), {"count": 0, "positions": {}}),
        "lab": _safe(lambda: _lab(app), {"count": 0, "proposals": [], "recent": []}),
        "code": _safe(lambda: _code(app), {"count": 0}),
        "knowledge": _safe(lambda: _knowledge(app), {"count": 0, "latest": []}),
        "pacifica": _safe(lambda: _insurance(app), {"count": 0, "connected": False}),
        "reverse": {"count": 0},
        "arbitrage": {"count": 0},
        "stenos": {"count": 0},
        "websites": _safe(lambda: _websites(app), {"count": 0}),
    }
    if getattr(app, "arena", None) is not None:
        out["trading"]["arena"] = _safe(lambda: app.arena.view(), None)
        if out["trading"]["arena"]:
            out["trading"]["count"] = len(out["trading"]["arena"]["alive"])
    from .warehouses import KEYS as BOT_KEYS
    for key in BOT_KEYS:  # every island has its research bot
        bot = _safe(lambda: _bot(app, key), None)
        if bot and key in out:
            out[key]["bot"] = bot
            if key in ("arbitrage", "pacifica", "stenos", "reverse"):
                out[key]["count"] = len(bot.get("findings", []))
            out[key]["busy"] = bool(out[key].get("busy")) or bot["busy"]
    return out


def island_context(app, key: str) -> str:
    """What an island chat answer gets to know about the island right now (numbers, bot findings, its knowledge file)."""
    import json
    from .warehouses import island_knowledge, KEYS as BOT_KEYS
    parts = []
    if key == "prime":
        depts = departments(app)
        keep = ("count", "label", "busy", "waiting", "status", "cash", "realized")
        lines = [f"- {name}: " + json.dumps({k: v for k, v in depts.get(k2, {}).items() if k in keep})
                 for k2, name, *_ in ISLANDS]
        parts.append("Islands:\n" + "\n".join(lines))
        parts.append("Research bots: " + json.dumps(_safe(lambda: app.warehouses.overview(), {})))
        prime = _safe(lambda: app.prime.view(), {}) or {}
        parts.append("Doxa's log: " + "; ".join(e.get("text", "") for e in (prime.get("log") or [])[-5:]))
        return "\n".join(parts)
    dept = dict(departments(app).get(key, {}))
    bot = dept.pop("bot", None)
    parts.append("Numbers: " + json.dumps(dept, ensure_ascii=False, default=str)[:2500])
    if bot:
        parts.append(f"Research bot {bot['name']}: {bot.get('status', '')}; {bot.get('runs', 0)} runs. Newest findings:\n"
                     + "\n".join(f"- {f['title']}: {f.get('detail', '')[:200]} {f.get('source', '')}"
                                 for f in bot.get("findings", [])[:6]))
        if bot.get("asks"):
            parts.append("Questions already queued for it: " + "; ".join(bot["asks"]))
    if key in BOT_KEYS:
        known, _ = island_knowledge(key, getattr(app.warehouses, "island_dir", None))
        if known:
            parts.append("Island knowledge file (excerpt):\n" + known[:3500])
    return "\n".join(parts)


def action(app, name: str, data: dict) -> dict:
    """The island buttons. Raises ValueError with a plain-English reason."""
    if name == "hunt":
        if getattr(app, "_hunting", False):
            return {"ok": True, "message": "The product hunt is already running."}
        niche = str(data.get("niche", ""))[:80]
        app.events.put(("ui", lambda: app.start_product_hunt("Find winning products for me", niche, source="HQ")))
        return {"ok": True, "message": "Product hunt started. Results land on Store Builder and in chat."}
    if name == "lab_research":
        return {"ok": True, "message": app.upgrades.start(focus=str(data.get("focus", ""))[:500])}
    if name == "site_publish":   # makes a site public: only from the owner pressing Publish
        return {"ok": True, "message": app.publisher.publish(str(data.get("name", ""))[:120])}
    if name == "cloudflare_connect":
        return {"ok": True, "message": app.publisher.connect()}
    if name == "make_art":
        return {"ok": True, "message": app.hq_art.start("figure" if data.get("kind") == "figure" else "portrait")}
    if name == "bot_run":
        return {"ok": True, "message": app.warehouses.run_now(str(data.get("key", "")), str(data.get("topic", ""))[:200])}
    if name == "island_chat":   # the owner's message in an island's chat box
        return {"ok": True, "message": app.island_chat.send(str(data.get("key", "")), str(data.get("text", "")))}
    if name == "island_chat_view":
        return {"ok": True, **app.island_chat.view(str(data.get("key", "")))}
    if name == "bots_pause":
        return {"ok": True, "message": app.warehouses.set_paused(bool(data.get("paused")))}
    if name == "lab_decide":
        proposal = app.upgrades.decide(str(data.get("id", "")), bool(data.get("approve")))
        message = ("Sent to Code mode: it builds and tests a copy of Doxa. You'll see the result in Code Forge and chat."
                   if proposal["status"] == "building" else proposal.get("note") or f"Marked {proposal['status']}.")
        return {"ok": True, "message": message, "status": proposal["status"]}
    raise ValueError("Unknown island action.")
