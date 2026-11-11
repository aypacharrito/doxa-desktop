"""Doxa Sites: build a cinematic one-page website for a local business from footage filmed on site.

The business from the owner's saved reels (2026-11-05): film a business from the street, walk in, pan the room,
then show the owner a site made from that footage on a laptop and sell it ($1,300 to $3,350 in the reels).
Doxa does the building; the owner does the filming, the selling and the publishing.

Pipeline (all local except optional copywriting):
  media  -> ffmpeg makes a muted looping hero video + poster + gallery stills (videos and photos)
  copy   -> optional: one OpenAI request through CloudBrain (Doxa's $5/month cap) returns JSON copy from the
            facts entered; otherwise copy is written from those facts. Nothing is invented (no reviews,
            awards, prices or years in business unless entered).
  page   -> index.html with click-to-call, directions, hours, map, LocalBusiness JSON-LD and Open Graph tags
  pitch  -> preview.html (phone + laptop frames for showing the owner), shot list, price sheet
Output: Documents\\Doxa Sites\\<business>\\ — a plain static folder that can be hosted anywhere.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from html import escape
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_GALLERY = 9

STYLES = {
    "cinematic": {"bg": "#0b0b0d", "panel": "#15151a", "text": "#f4efe6", "muted": "#a9a39a", "accent": "#e2b65e",
                  "ink": "#16110a", "display": "'Playfair Display', Georgia, serif"},
    "warm": {"bg": "#1a120d", "panel": "#241912", "text": "#fbf1e6", "muted": "#c9b7a6", "accent": "#f08a4b",
             "ink": "#200f05", "display": "'DM Serif Display', Georgia, serif"},
    "clean": {"bg": "#f6f4ef", "panel": "#ffffff", "text": "#1b1b1f", "muted": "#5f5d58", "accent": "#1f6f5c",
              "ink": "#ffffff", "display": "'Fraunces', Georgia, serif"},
}
SHOT_LIST = [
    "Outside: the storefront and sign from across the street (5–8 s, steady, phone horizontal for the hero).",
    "Walk-in: push the door and walk in, camera at chest height (5 s).",
    "The room: slow pan left to right across the whole space. This is the most important shot.",
    "The work: the signature dish, product or service up close (3–4 clips).",
    "People: the owner or staff at work, only with their OK.",
    "Details: menu board, tools, finished results, anything that makes it this business and not another.",
]


@dataclass
class SiteBrief:
    name: str
    kind: str = ""            # "Mexican restaurant", "barbershop", "auto repair", ...
    city: str = ""
    phone: str = ""
    address: str = ""
    hours: str = ""           # free text, one line per day or range
    offer: str = ""           # what they sell / why people come (owner's words)
    cta: str = "Call now"
    style: str = "cinematic"
    media_folder: str = ""
    notes: str = ""           # anything else the owner said (specials, languages, parking...)
    extra: dict = field(default_factory=dict)

    def facts(self) -> dict:
        return {k: v for k, v in {"name": self.name, "kind": self.kind, "city": self.city, "phone": self.phone,
                                  "address": self.address, "hours": self.hours, "offer": self.offer,
                                  "notes": self.notes}.items() if v}


@dataclass
class SiteResult:
    folder: Path
    index: Path
    preview: Path
    pitch: Path
    used_ai: bool
    media: dict


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (text or "site").lower()).strip("-")
    return value[:60] or "site"


def default_root() -> Path:
    return Path.home() / "Documents" / "Doxa Sites"


# --- media ------------------------------------------------------------------------------------------------

def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=600,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _duration(ff: str, path: Path) -> float:
    probe = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr)
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3)) if match else 0.0


def prepare_media(folder: str | Path, assets: Path, progress: Callable[[str], None] | None = None) -> dict:
    """Turn the owner's footage/photos into web-ready files. Returns {'hero': name|None, 'poster': name|None,
    'gallery': [names]}. Originals are never changed."""
    say = progress or (lambda _m: None)
    result: dict = {"hero": None, "poster": None, "gallery": []}
    source = Path(folder) if folder else None
    if not source or not source.is_dir():
        return result
    files = sorted(p for p in source.iterdir() if p.is_file())
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    images = [p for p in files if p.suffix.lower() in IMAGE_EXT]
    assets.mkdir(parents=True, exist_ok=True)
    ff = _ffmpeg() if videos else ""
    if videos:
        # The hero is the first clip by name (film the storefront first, as the shot list says).
        hero = videos[0]
        say(f"Making the hero video from {hero.name}…")
        length = _duration(ff, hero)
        start = 1.0 if length > 6 else 0.0
        _run([ff, "-y", "-v", "error", "-ss", f"{start}", "-t", "10", "-i", str(hero), "-an",
              "-vf", "scale='min(1280,iw)':-2,fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
              "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(assets / "hero.mp4")])
        _run([ff, "-y", "-v", "error", "-ss", f"{start + 1}", "-i", str(hero), "-frames:v", "1",
              "-vf", "scale='min(1600,iw)':-2", "-q:v", "3", str(assets / "poster.jpg")])
        result["hero"], result["poster"] = "hero.mp4", "poster.jpg"
    for index, image in enumerate(images[:MAX_GALLERY]):
        say(f"Preparing photo {index + 1} of {min(len(images), MAX_GALLERY)}…")
        name = f"photo-{index + 1}.jpg"
        try:
            from PIL import Image, ImageOps
            with Image.open(image) as picture:
                picture = ImageOps.exif_transpose(picture).convert("RGB")
                picture.thumbnail((1600, 1600))
                picture.save(assets / name, quality=82, optimize=True)
            result["gallery"].append(name)
        except Exception:
            continue
    # Fill the gallery with stills from the footage (two per clip, from the middle of each).
    for clip in videos:
        if len(result["gallery"]) >= MAX_GALLERY:
            break
        length = _duration(ff, clip)
        for fraction in (0.35, 0.7):
            if len(result["gallery"]) >= MAX_GALLERY:
                break
            name = f"still-{len(result['gallery']) + 1}.jpg"
            say(f"Taking stills from {clip.name}…")
            try:
                _run([ff, "-y", "-v", "error", "-ss", f"{max(0.0, length * fraction):.2f}", "-i", str(clip),
                      "-frames:v", "1", "-vf", "scale='min(1400,iw)':-2", "-q:v", "4", str(assets / name)])
                result["gallery"].append(name)
            except subprocess.CalledProcessError:
                pass
    if not result["poster"] and result["gallery"]:
        result["poster"] = result["gallery"][0]
    return result


# --- copy -------------------------------------------------------------------------------------------------

def default_copy(brief: SiteBrief) -> dict:
    """Copy made only from the facts entered. Used without OpenAI, and as the fallback."""
    kind = brief.kind or "local business"
    place = f" in {brief.city}" if brief.city else ""
    offer = brief.offer.strip() or f"A {kind}{place}."
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", offer) if s.strip()]
    where = ", ".join(x for x in (brief.address, brief.city) if x)
    first_hours = brief.hours.splitlines()[0].strip() if brief.hours.strip() else ""
    highlights = [
        {"title": "Known for", "text": " ".join(sentences[:2]) or offer},
        {"title": "Good to know", "text": brief.notes.strip() or (" ".join(sentences[2:]) if len(sentences) > 2
                                                                  else f"Questions? Call {brief.phone}." if brief.phone
                                                                  else "Stop by any time.")},
        {"title": "Find us", "text": " · ".join(x for x in (where, first_hours) if x) or f"Visit {brief.name}{place}."},
    ]
    return {"headline": brief.name, "subheadline": f"{kind.capitalize()}{place}",
            "about": offer, "highlights": highlights, "cta": brief.cta or "Call now",
            "meta_description": f"{brief.name}: {kind}{place}. {offer}"[:155]}


COPY_KEYS = {"headline", "subheadline", "about", "highlights", "cta", "meta_description"}


def ai_prompt(brief: SiteBrief) -> str:
    return ("Write website copy for this local business as JSON with keys headline (max 8 words), subheadline "
            "(max 16 words), about (2-3 sentences), highlights (exactly 3 objects with title max 4 words and text max "
            "22 words), cta (max 4 words), meta_description (max 150 characters). Use ONLY these facts; do not invent "
            "reviews, awards, years in business, prices, menu items, guarantees or claims not given. Warm, specific, "
            "no cliches like 'look no further'. Return only the JSON. Facts: "
            + json.dumps(brief.facts(), ensure_ascii=False))


def parse_copy(text: str, brief: SiteBrief) -> dict | None:
    """Accept the model's JSON only if it has the right shape; trim lengths. None if unusable."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or not COPY_KEYS <= set(data):
        return None
    highlights = data.get("highlights")
    if not isinstance(highlights, list) or len(highlights) < 3 or not all(
            isinstance(h, dict) and h.get("title") and h.get("text") for h in highlights[:3]):
        return None
    clean = lambda value, limit: " ".join(str(value).split())[:limit]  # noqa: E731
    return {"headline": clean(data["headline"], 80) or brief.name, "subheadline": clean(data["subheadline"], 140),
            "about": clean(data["about"], 600), "cta": clean(data["cta"], 30) or "Call now",
            "meta_description": clean(data["meta_description"], 155),
            "highlights": [{"title": clean(h["title"], 40), "text": clean(h["text"], 180)} for h in highlights[:3]]}


def write_copy(brief: SiteBrief, brain=None) -> tuple[dict, bool]:
    """(copy, used_ai). OpenAI is used only if a connected brain is passed; any failure falls back."""
    if brain is not None and getattr(brain, "loaded", False):
        try:
            text = "".join(brain.stream([], ai_prompt(brief), None, [], []))
            parsed = parse_copy(text, brief)
            if parsed:
                return parsed, True
        except Exception:
            pass
    return default_copy(brief), False


# --- page -------------------------------------------------------------------------------------------------

def _hours_rows(hours: str) -> str:
    rows = [line.strip() for line in (hours or "").splitlines() if line.strip()]
    return "".join(f"<li>{escape(row)}</li>" for row in rows) or "<li>Call for today's hours</li>"


def json_ld(brief: SiteBrief, copy: dict) -> str:
    data = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": brief.name,
            "description": copy.get("meta_description", "")}
    if brief.phone:
        data["telephone"] = brief.phone
    if brief.address:
        data["address"] = {"@type": "PostalAddress", "streetAddress": brief.address,
                           **({"addressLocality": brief.city} if brief.city else {})}
    if brief.hours:
        data["openingHours"] = [line.strip() for line in brief.hours.splitlines() if line.strip()]
    # Inside <script>, escape <, > and & so no business text can end or confuse the script block.
    return (json.dumps(data, ensure_ascii=False)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def render_page(brief: SiteBrief, copy: dict, media: dict) -> str:
    s = STYLES.get(brief.style, STYLES["cinematic"])
    e = escape
    tel = re.sub(r"[^\d+]", "", brief.phone or "")
    where = ", ".join(x for x in (brief.address, brief.city) if x)
    maps = f"https://www.google.com/maps/search/?api=1&query={quote_plus(where or brief.name)}"
    embed = f"https://www.google.com/maps?q={quote_plus(where or brief.name)}&output=embed"
    hero_media = (f'<video class="bg" autoplay muted loop playsinline preload="metadata" poster="assets/{e(media["poster"])}">'
                  f'<source src="assets/{e(media["hero"])}" type="video/mp4"></video>' if media.get("hero") else
                  f'<img class="bg" src="assets/{e(media["poster"])}" alt="">' if media.get("poster") else "")
    gallery = "".join(f'<figure class="reveal"><img loading="lazy" src="assets/{e(name)}" alt="{e(brief.name)}"></figure>'
                      for name in media.get("gallery", []))
    highlights = "".join(f'<article class="reveal"><h3>{e(h["title"])}</h3><p>{e(h["text"])}</p></article>'
                         for h in copy["highlights"])
    call = (f'<a class="btn primary" href="tel:{e(tel)}">{e(copy["cta"])}</a>' if tel else "")
    og_image = f'<meta property="og:image" content="assets/{e(media["poster"])}">' if media.get("poster") else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(brief.name)}{(' · ' + e(brief.city)) if brief.city else ''}</title>
<meta name="description" content="{e(copy['meta_description'])}">
<meta property="og:title" content="{e(brief.name)}"><meta property="og:description" content="{e(copy['meta_description'])}">{og_image}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Playfair+Display:wght@600&family=DM+Serif+Display&family=Fraunces:wght@600&display=swap" rel="stylesheet">
<script type="application/ld+json">{json_ld(brief, copy)}</script>
<style>
:root{{--bg:{s['bg']};--panel:{s['panel']};--text:{s['text']};--muted:{s['muted']};--accent:{s['accent']};--ink:{s['ink']}}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--text);font:17px/1.6 Inter,system-ui,sans-serif}}
h1,h2,h3{{font-family:{s['display']};font-weight:600;line-height:1.05;margin:0}}a{{color:inherit}}
.hero{{position:relative;min-height:100svh;display:grid;align-items:end;overflow:hidden;padding:0 6vw 12vh}}
.hero .bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transform:scale(1.04);animation:drift 18s ease-in-out infinite alternate}}
.hero::after{{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.15) 0%,rgba(0,0,0,.35) 45%,var(--bg) 100%)}}
.hero .copy{{position:relative;z-index:1;max-width:820px}}.kicker{{color:var(--accent);letter-spacing:.18em;text-transform:uppercase;font-size:13px;font-weight:600}}
.hero h1{{font-size:clamp(48px,9vw,120px);margin:14px 0 16px}}.hero p{{font-size:clamp(18px,2.2vw,22px);color:#efe9df;max-width:36ch;margin:0 0 28px}}
.btn{{display:inline-block;padding:15px 26px;border-radius:999px;font-weight:600;text-decoration:none;border:1px solid rgba(255,255,255,.35);margin:0 10px 10px 0}}
.btn.primary{{background:var(--accent);color:var(--ink);border-color:var(--accent)}}
section{{padding:13vh 6vw}}.about{{display:grid;grid-template-columns:1fr 1.1fr;gap:6vw;align-items:center}}
.about h2,.visit h2{{font-size:clamp(36px,5vw,64px)}}.about p{{color:var(--muted);font-size:19px}}
.highlights{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}.highlights article{{background:var(--panel);padding:30px;border-radius:18px;border:1px solid rgba(255,255,255,.06)}}
.highlights h3{{font-size:26px;margin-bottom:10px;color:var(--accent)}}.highlights p{{color:var(--muted);margin:0}}
.gallery{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding-top:0}}.gallery figure{{margin:0;overflow:hidden;border-radius:14px;aspect-ratio:4/5}}
.gallery img{{width:100%;height:100%;object-fit:cover;transition:transform .8s}}.gallery figure:hover img{{transform:scale(1.05)}}
.visit{{display:grid;grid-template-columns:1fr 1fr;gap:5vw}}.visit ul{{list-style:none;padding:0;color:var(--muted)}}.visit li{{padding:6px 0;border-bottom:1px solid rgba(255,255,255,.08)}}
.map{{width:100%;min-height:340px;border:0;border-radius:18px;filter:grayscale(.3)}}
footer{{padding:40px 6vw 110px;color:var(--muted);font-size:14px}}
.bar{{position:fixed;left:12px;right:12px;bottom:12px;display:none;gap:10px;z-index:9}}.bar a{{flex:1;text-align:center;margin:0;backdrop-filter:blur(10px);background:rgba(0,0,0,.55)}}
.reveal{{opacity:0;transform:translateY(28px);transition:opacity .9s ease,transform .9s ease}}.reveal.on{{opacity:1;transform:none}}
@keyframes drift{{from{{transform:scale(1.04)}}to{{transform:scale(1.12)}}}}
@media(max-width:760px){{.about,.visit,.highlights{{grid-template-columns:1fr}}.gallery{{grid-template-columns:1fr 1fr}}.bar{{display:flex}}section{{padding:9vh 6vw}}}}
@media(prefers-reduced-motion:reduce){{.hero .bg{{animation:none}}.reveal{{opacity:1;transform:none;transition:none}}}}
</style></head><body>
<header class="hero">{hero_media}<div class="copy"><div class="kicker">{e(copy['subheadline'])}</div><h1>{e(copy['headline'])}</h1>
<p>{e(brief.offer.split('.')[0] if brief.offer else copy['subheadline'])}</p>{call}<a class="btn" href="{e(maps)}" target="_blank" rel="noopener">Get directions</a></div></header>
<section class="about"><h2 class="reveal">About {e(brief.name)}</h2><p class="reveal">{e(copy['about'])}</p></section>
<section class="highlights">{highlights}</section>
{f'<section class="gallery">{gallery}</section>' if gallery else ''}
<section class="visit"><div class="reveal"><h2>Visit us</h2><p>{e(where)}</p><ul>{_hours_rows(brief.hours)}</ul>{call}</div>
<iframe class="map reveal" loading="lazy" src="{e(embed)}" title="Map to {e(brief.name)}" referrerpolicy="no-referrer-when-downgrade"></iframe></section>
<footer>© {date.today().year} {e(brief.name)}{(' · ' + e(brief.phone)) if brief.phone else ''}</footer>
<nav class="bar">{f'<a class="btn primary" href="tel:{e(tel)}">Call</a>' if tel else ''}<a class="btn" href="{e(maps)}" target="_blank" rel="noopener">Directions</a></nav>
<script>const io=new IntersectionObserver(es=>es.forEach(x=>{{if(x.isIntersecting){{x.target.classList.add('on');io.unobserve(x.target)}}}}),{{threshold:.15}});document.querySelectorAll('.reveal').forEach(el=>io.observe(el));</script>
</body></html>"""


def preview_page(brief: SiteBrief) -> str:
    """Phone + laptop frames side by side: what the owner shows the owner on his laptop."""
    e = escape
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(brief.name)} · preview</title><style>body{{margin:0;min-height:100vh;background:radial-gradient(circle at 30% 20%,#242018,#0b0b0d 70%);color:#eee;font:15px system-ui;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;padding:30px}}
.row{{display:flex;gap:40px;align-items:center;flex-wrap:wrap;justify-content:center}}.laptop{{width:min(900px,90vw)}}.screen{{border:14px solid #1c1c20;border-bottom-width:22px;border-radius:16px 16px 4px 4px;aspect-ratio:16/10;overflow:hidden;background:#000}}
.base{{height:16px;background:linear-gradient(#2a2a30,#141418);border-radius:0 0 18px 18px;margin:0 -40px}}.phone{{width:300px;aspect-ratio:9/19.5;border:12px solid #1c1c20;border-radius:44px;overflow:hidden;background:#000;box-shadow:0 30px 60px #0008}}
iframe{{width:100%;height:100%;border:0;display:block}}h1{{font:600 22px Georgia,serif;margin:0;color:#e2b65e}}</style></head><body>
<h1>{e(brief.name)} — website preview</h1><div class="row"><div class="laptop"><div class="screen"><iframe src="index.html" title="Desktop preview"></iframe></div><div class="base"></div></div>
<div class="phone"><iframe src="index.html" title="Phone preview"></iframe></div></div></body></html>"""


def pitch_page(brief: SiteBrief, setup_price: int = 1300, monthly: int = 49) -> str:
    e = escape
    shots = "".join(f"<li>{e(item)}</li>" for item in SHOT_LIST)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(brief.name)} · proposal</title>
<style>body{{max-width:760px;margin:6vh auto;padding:0 24px;font:17px/1.6 system-ui;color:#1b1b1f}}h1{{font:600 34px Georgia,serif}}table{{width:100%;border-collapse:collapse}}td{{padding:10px;border-bottom:1px solid #ddd}}td:last-child{{text-align:right;font-weight:600}}small{{color:#666}}</style></head><body>
<h1>A new website for {e(brief.name)}</h1><p>Built from footage of your own business, made for phones first, with one-tap calling and directions,
and set up so Google and AI assistants understand who you are and where you are.</p>
<table><tr><td>Website design and build (this preview, your edits included)</td><td>${setup_price:,}</td></tr>
<tr><td>Hosting, updates and small changes</td><td>${monthly}/month</td></tr></table>
<p><small>You own the content and the domain. Cancel the monthly plan any time and keep the site files.</small></p>
<h2>Shot list (for the next filming visit)</h2><ol>{shots}</ol></body></html>"""


def build_site(brief: SiteBrief, root: Path | None = None, brain=None,
               progress: Callable[[str], None] | None = None) -> SiteResult:
    if not brief.name.strip():
        raise ValueError("Enter the business name.")
    say = progress or (lambda _m: None)
    folder = Path(root or default_root()) / slug(brief.name)
    folder.mkdir(parents=True, exist_ok=True)
    media = prepare_media(brief.media_folder, folder / "assets", say)
    say("Writing the copy with OpenAI…" if brain is not None and getattr(brain, "loaded", False) else "Writing the copy…")
    copy, used_ai = write_copy(brief, brain)
    say("Building the page…")
    (folder / "index.html").write_text(render_page(brief, copy, media), encoding="utf-8")
    (folder / "preview.html").write_text(preview_page(brief), encoding="utf-8")
    (folder / "proposal.html").write_text(pitch_page(brief), encoding="utf-8")
    (folder / "site.json").write_text(json.dumps({"brief": brief.__dict__, "copy": copy, "media": media,
                                                  "used_ai": used_ai}, indent=1, ensure_ascii=False), encoding="utf-8")
    return SiteResult(folder, folder / "index.html", folder / "preview.html", folder / "proposal.html", used_ai, media)
