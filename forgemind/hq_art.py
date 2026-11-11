"""HQ robot art made by ChatGPT's image model (the owner 2026-11-09: "use Higgsfield … if not, you can use Astra as in
ChatGPT … I can ask Astra to make stuff too"). the owner presses "Make robot art" in HQ (Command island); Doxa asks
OpenAI's image model for one original portrait per island with Doxa's own OpenAI key (DPAPI, never shown), counts the
cost in the OpenAI budget, and saves them in Documents\\Doxa Team\\characters\\<island>.png, where HQ already looks.
Existing pictures are kept (delete one to make it again).
"""
from __future__ import annotations

import base64
import threading
from pathlib import Path

MODEL = "gpt-image-1"
# 2026-11-09: the owner's first press got HTTP 400 for every picture. The real reason is now shown, and when OpenAI says the
# model or a setting isn't available, Doxa tries the next image model instead of failing 11 times.
MODELS = [  # (model, extra request fields)
    ("gpt-image-1", {"size": "1024x1536", "quality": "medium"}),
    ("gpt-image-1-mini", {"size": "1024x1536", "quality": "medium"}),
    ("dall-e-3", {"size": "1024x1792", "quality": "standard", "response_format": "b64_json"}),
]
SIZE, QUALITY = "1024x1536", "medium"
COST_USD = 0.063                      # gpt-image-1, medium, 1024x1536 (estimate for the budget)
STYLE = ("Original robot character, full body, standing, dramatic heroic pose. Bold 1990s shonen manga action style: "
         "thick black ink outlines, vivid saturated colours (hot pink, electric purple, gold, cyan, lime), strong "
         "shadows, a stylized night city with a huge crescent moon behind it, a checkered black-and-white floor, "
         "dramatic speed lines and floating bold katakana sound effects. Portrait 2:3, character centered with space "
         "around it. No words or logos except the katakana. An original design that doesn't copy any existing character.")
ROBOTS = {
    "prime": "Doxa, the commander of an AI headquarters: tall slim robot in a long black coat with a high collar, white "
             "faceplate with a calm glowing red eye slit, two glowing halo rings orbiting it, cables to floating screens.",
    "stores": "Scout, the store manager: stocky cheerful robot shopkeeper with a pink-and-white striped awning hat, stacks "
              "of product boxes, printed shirts and mugs, a little shopping-cart drone.",
    "trading": "Oracle, the trader: elegant robot with a white skull-like mask and three stripes on one side of its head, "
               "holding a glowing green candlestick chart, gold coins floating, perfectly symmetrical pose.",
    "arbitrage": "Flip, the dealer: sharp robot in a tall black top hat with a red band, flipping a gold coin, BUY and "
                 "SELL tags floating on either side, lime-green glow.",
    "pacifica": "Shield, the guardian of an insurance agency: armored calm robot with a big cyan shield, standing protectively.",
    "reverse": "Cipher, the reverse engineer: sly robot with glowing pink goggles and a magnifying glass, circuit boards and "
               "a car dashboard screen opened up in front of it, lines of decompiled code floating around.",
    "marketing": "Nova, the content star: robot with a camera, a huge translucent magenta guardian spirit rising behind it "
                 "in a fighting pose, video thumbnails flying around.",
    "stenos": "Scribe, the art director of a web design studio: sleek robot in luxury black with bronze accents, a bronze "
              "headset, a glowing stylus, website mockups floating behind it.",
    "websites": "Builder, the web builder: sturdy robot with a yellow hard hat, assembling glowing teal website panels like "
                "building blocks.",
    "lab": "Tinker, the inventor: patched-together mad-scientist robot with stitches and a big bolt through its head, "
           "bubbling acid-green flasks, blueprints of itself.",
    "code": "Smith, the coder: lean robot with one arm a giant red-and-black scythe, sparks and lines of code flying.",
    "knowledge": "Archive, the librarian: tall robot with glowing blue book pages orbiting it, a floating open book.",
}


# 1.37 (the owner 2026-11-09: "when it's done making all the art, make it all 3D … remake the entire headquarters"):
# a second set, one cut-out 3D figure per island with a transparent background. HQ stands them on the islands in place
# of the built-in robots (forgemind/phone_web/hq3d.js `setFigure`). Saved in characters\figures\<island>.png.
FIGURE_MODELS = [m for m in MODELS if m[0] != "dall-e-3"]          # dall-e-3 can't make transparent backgrounds
FIGURE_EXTRA = {"size": "1024x1536", "quality": "high", "background": "transparent", "output_format": "png"}
FIGURE_COST_USD = 0.25                # gpt-image-1, high, 1024x1536 (estimate for the budget)
FIGURE_STYLE = ("Full body, standing on its feet, whole figure in frame with a little space around it, facing the "
                "viewer at a slight three-quarter angle. Rendered as a high-end 3D collectible figure: glossy painted "
                "plastic and metal, soft studio lighting, crisp rim light, rich saturated colours (hot pink, electric "
                "purple, gold, cyan, lime), bold anime-style proportions and a dramatic heroic pose. Fully transparent "
                "background: no floor, no shadow, no scenery, no text. An original design that doesn't copy any "
                "existing character.")
KINDS = {  # kind: (sub-folder, style, models, extra fields, cost, reserve cents, plural)
    "portrait": ("", STYLE, MODELS, None, COST_USD, 10, "robot portraits"),
    "figure": ("figures", FIGURE_STYLE, FIGURE_MODELS, FIGURE_EXTRA, FIGURE_COST_USD, 30, "3D figures"),
}


class ArtMaker:
    def __init__(self, key_lookup, budget, folder: Path, notify=None, transport=None):
        self.key_lookup = key_lookup          # () -> OpenAI key (Doxa's DPAPI file); raises if not connected
        self.budget = budget                  # Doxa's OpenAI CloudBudget
        self.folder = Path(folder)
        self.notify = notify or (lambda text: None)
        self.transport = transport
        self.running = False
        self.status = ""
        self.kind = "portrait"

    def folder_for(self, kind: str = "portrait") -> Path:
        sub = KINDS[kind][0]
        return self.folder / sub if sub else self.folder

    def missing(self, kind: str = "portrait") -> list[str]:
        folder = self.folder_for(kind)
        have = {p.stem.lower() for p in folder.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")}
        return [k for k in ROBOTS if k not in have]

    def figures(self) -> dict:
        """{island: file time} of the 3D figures that exist (HQ reloads one when its time changes)."""
        folder = self.folder_for("figure")
        return {p.stem.lower(): int(p.stat().st_mtime) for p in folder.glob("*.png")
                if p.stem.lower() in ROBOTS} if folder.is_dir() else {}

    def figure(self, key: str):
        path = self.folder_for("figure") / f"{(key or '').lower()}.png"
        if (key or "").lower() not in ROBOTS or not path.is_file() or path.stat().st_size > 15_000_000:
            return None
        return path.read_bytes()

    def start(self, kind: str = "portrait") -> str:
        if kind not in KINDS:
            raise ValueError("Unknown kind of art.")
        if self.running:
            return "Doxa is already making the robot art."
        todo = self.missing(kind)
        plural, cost = KINDS[kind][6], KINDS[kind][4]
        if not todo:
            return (f"Every island already has its {plural[:-1]}. Delete one in Documents\\Doxa Team\\characters"
                    + ("\\figures" if kind == "figure" else "") + " to remake it.")
        self.key_lookup()                     # fail now (plain message) when OpenAI isn't connected
        self.running, self.kind = True, kind
        self.status = f"Making {len(todo)} {plural} with ChatGPT's image AI…"
        threading.Thread(target=self._run, args=(todo, kind), daemon=True, name="doxa-hq-art").start()
        return self.status + f" About ${cost * len(todo):.2f} of the OpenAI budget; they appear in HQ as they finish."

    def auto_tick(self) -> str | None:
        """the owner asked for the 3D figures once the portraits are done: start them once, by itself (never repeats)."""
        marker = self.folder_for("figure") / ".started"
        if self.running or self.missing("portrait") or not self.missing("figure") or marker.exists():
            return None
        try:
            message = self.start("figure")
        except Exception:
            return None                       # OpenAI not connected: try again on a later tick
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(message, "utf-8")
        return message

    @staticmethod
    def _reason(response) -> str:
        try:
            error = response.json().get("error") or {}
            return " ".join(str(error.get("message") or error.get("code") or "").split())[:220]
        except Exception:
            return ""

    def _run(self, todo, kind="portrait"):
        transport = self.transport
        if transport is None:
            import requests as transport
        _sub, style, kind_models, override, cost, reserve, plural = KINDS[kind]
        made, models = 0, list(kind_models)
        folder = self.folder_for(kind)
        try:
            key = self.key_lookup()
            folder.mkdir(parents=True, exist_ok=True)
            for name in todo:
                ident = self.budget.reserve(reserve)
                try:
                    while True:
                        model, extra = models[0]
                        if override:
                            extra = {**override, **({"quality": "high"} if model != "dall-e-3" else {})}
                        response = transport.post("https://api.openai.com/v1/images/generations", timeout=300,
                                                  headers={"Authorization": "Bearer " + key},
                                                  json={"model": model, "prompt": ROBOTS[name] + " " + style, "n": 1, **extra})
                        reason = "" if response.ok else self._reason(response)
                        # a model this account can't use (or a setting it doesn't take): try the next model
                        if (not response.ok and response.status_code in (400, 403, 404) and len(models) > 1
                                and any(w in reason.lower() for w in ("model", "verified", "verify", "organization", "not supported", "invalid value", "does not exist"))):
                            models.pop(0)
                            continue
                        break
                    if not response.ok:
                        self.budget.settle(ident, "failed", 0)
                        self.status = (f"OpenAI refused the {name} picture (HTTP {response.status_code}"
                                       + (f": {reason}" if reason else "") + ").")
                        if made == 0 or response.status_code in (401, 403, 404, 429):
                            break          # the same problem would repeat for every picture: stop and show it
                        continue
                    image = base64.b64decode(response.json()["data"][0]["b64_json"])
                    self.model_used = model
                    (folder / f"{name}.png").write_bytes(image)
                    self.budget.settle(ident, "completed", cost)
                    made += 1
                    self.status = f"Made {made} of {len(todo)} {plural}…"
                except Exception as exc:
                    self.budget.settle(ident, "uncertain", cost)
                    self.status = f"The {name} picture failed: {str(exc)[:120]}"
            if made == len(todo):
                self.status = f"Made {made} {plural}. They're on the islands now."
        except Exception as exc:
            self.status = f"Couldn't make the art: {str(exc)[:160]}"
        finally:
            self.running = False
            self.notify("HQ art: " + self.status)
