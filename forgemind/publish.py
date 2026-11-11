"""Doxa's own "Vercel": publish the sites Doxa builds to Cloudflare (the owner 2026-11-09: "can Doxa make something like
Vercel where we can actually host websites?").

Doxa is the control panel; Cloudflare's free Workers static-assets hosting serves the site (unlimited static requests,
a free <name>.<account>.workers.dev address; a custom domain can be attached in Cloudflare later). Publishing uses
Cloudflare's official CLI (wrangler, run through npx) with the owner's own Cloudflare sign-in: he presses "Connect
Cloudflare" once and approves it on Cloudflare's page (Doxa never sees a password). Only folders inside
Documents\\Doxa Sites can be published, and only when the owner presses Publish (it makes the site public).
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path

SITES = Path.home() / "Documents" / "Doxa Sites"
WRANGLER = ["npx", "--yes", "wrangler@4"]
URL = re.compile(r"https://[a-z0-9.-]+\.workers\.dev", re.I)


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40].strip("-")
    return "doxa-" + (text or "site")


def run(args, timeout=300, cwd=None):
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, shell=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), encoding="utf-8", errors="replace")
    return done.returncode, (done.stdout or "") + (done.stderr or "")


class Publisher:
    def __init__(self, sites: Path | None = None, runner=None, clock=time.time):
        self.sites = Path(sites or SITES)
        self.runner = runner or (lambda args, timeout=300, cwd=None: run(["cmd", "/c", *args], timeout, cwd))
        self.clock = clock
        self.state = {"connected": None, "checked": 0.0, "busy": "", "status": ""}
        self.lock = threading.Lock()

    # --- Cloudflare sign-in ---------------------------------------------------------------------------------------
    def refresh(self, force=False):
        """Check the sign-in in the background (wrangler whoami takes a few seconds), at most every 10 minutes."""
        if not force and self.clock() - self.state["checked"] < 600:
            return
        self.state["checked"] = self.clock()

        def check():
            try:
                code, out = self.runner(WRANGLER + ["whoami"], timeout=120)
                self.state["connected"] = code == 0 and "not authenticated" not in out.lower() and (
                    "logged in" in out.lower() or "account id" in out.lower())
            except Exception:
                self.state["connected"] = False
        threading.Thread(target=check, daemon=True, name="doxa-cloudflare-check").start()

    def connect(self) -> str:
        """Opens Cloudflare's sign-in page in the browser; the owner approves it there."""
        def login():
            try:
                self.state["status"] = "Waiting for you to approve Doxa on Cloudflare's page…"
                code, out = self.runner(WRANGLER + ["login"], timeout=600)
                self.state["status"] = "Cloudflare connected." if code == 0 else "Cloudflare sign-in didn't finish."
            except Exception as exc:
                self.state["status"] = f"Cloudflare sign-in failed: {str(exc)[:120]}"
            self.refresh(force=True)
        threading.Thread(target=login, daemon=True, name="doxa-cloudflare-login").start()
        return "Opening Cloudflare's sign-in page in your browser. Approve it there, then come back and press Publish."

    # --- publishing -------------------------------------------------------------------------------------------------
    def sites_list(self) -> list[dict]:
        out = []
        if self.sites.is_dir():
            for folder in sorted(p for p in self.sites.iterdir() if p.is_dir()):
                info = {}
                try:
                    info = json.loads((folder / "site.json").read_text("utf-8"))
                except (OSError, ValueError):
                    pass
                out.append({"name": folder.name, "url": info.get("published_url", ""), "published": info.get("published_at", 0),
                            "ready": (folder / "index.html").is_file()})
        return out

    def publish(self, name: str) -> str:
        folder = (self.sites / name).resolve()
        if self.sites.resolve() not in folder.parents or not folder.is_dir():
            raise ValueError("Only sites inside Documents\\Doxa Sites can be published.")
        if not (folder / "index.html").is_file():
            raise ValueError(f"{name} has no index.html yet. Build it first.")
        with self.lock:
            if self.state["busy"]:
                raise ValueError(f"Already publishing {self.state['busy']}.")
            self.state["busy"] = name
        self.state["status"] = f"Publishing {name}…"
        threading.Thread(target=self._publish, args=(folder,), daemon=True, name="doxa-publish").start()
        return f"Publishing {name} to Cloudflare. The address shows up here in about a minute."

    def _publish(self, folder: Path):
        try:
            code, out = self.runner(WRANGLER + ["deploy", "--assets", str(folder), "--name", slug(folder.name),
                                                "--compatibility-date", "2026-11-01"], timeout=600, cwd=str(folder.parent))
            match = URL.search(out)
            if code != 0 or not match:
                if "login" in out.lower() or "authenticat" in out.lower():
                    self.state["connected"] = False
                    self.state["status"] = "Connect Cloudflare first (one-time sign-in)."
                else:
                    self.state["status"] = "Publishing failed: " + " ".join(out.split())[-240:]
                return
            url = match.group(0)
            info_path = folder / "site.json"
            try:
                info = json.loads(info_path.read_text("utf-8"))
            except (OSError, ValueError):
                info = {}
            info.update(published_url=url, published_at=self.clock(), host="cloudflare-workers")
            info_path.write_text(json.dumps(info, indent=2), "utf-8")
            self.state["connected"] = True
            self.state["status"] = f"{folder.name} is live: {url}"
        except Exception as exc:
            self.state["status"] = f"Publishing failed: {str(exc)[:160]}"
        finally:
            self.state["busy"] = ""

    def view(self) -> dict:
        self.refresh()
        return {"connected": self.state["connected"], "busy": self.state["busy"], "status": self.state["status"],
                "sites": self.sites_list()}
