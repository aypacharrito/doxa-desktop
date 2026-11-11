"""Doxa Knowledge: the shared lessons file every AI of the owner's reads (Documents\\Doxa Knowledge\\lessons.md).

the owner, 2026-11-08: "I want all this information you've learned to be shared to all the AIs, a database of important
lessons and actual learning to make money." Plain Markdown so Claude Code (~/.claude/CLAUDE.md), Codex
(~/.codex/AGENTS.md), ChatGPT/Gemini (uploaded file) and Doxa all use the same thing. Doxa's Claude gets the Core rules
in every tool-using answer and can search or add lessons."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

ROOT = Path.home() / "Documents" / "Doxa Knowledge"
LESSONS = ROOT / "lessons.md"
TAGS = ("marketing", "distribution", "content", "ai-team", "ai-tools", "ecommerce", "music", "security", "legal",
        "scam-alert", "money-math", "process")


def _text(path: Path | None = None) -> str:
    try:
        return (path or LESSONS).read_text("utf-8")
    except OSError:
        return ""


def core_rules(path: Path | None = None, limit: int = 2500) -> str:
    """The 'Core rules' section (short), for the system prompt."""
    text = _text(path)
    match = re.search(r"## Core rules[^\n]*\n(.*?)(?:\n---|\n## )", text, re.S)
    return match.group(1).strip()[:limit] if match else ""


def lessons(path: Path | None = None) -> list[str]:
    text = _text(path)
    return ["### " + part.strip() for part in re.split(r"\n### ", text)[1:]]


def reel_search(query: str, root: Path | None = None, limit=6):
    """Retrieve source evidence separately from owner instructions and verified lessons."""
    root = root or ROOT / 'reels'
    words = set(re.findall(r'[a-z0-9-]{3,}', query.lower())) - {'the', 'and', 'for', 'what', 'this'}
    found = []
    for path in root.glob('*.md'):
        text = path.read_text(encoding='utf-8')
        score = sum(text.lower().count(w) for w in words)
        if score:
            lines = text.splitlines()
            matches = [i for i, line in enumerate(lines) if any(w in line.lower() for w in words)]
            i = matches[0] if matches else 0
            excerpt = '\n'.join(lines[max(0, i-1):i+18])[:2200]
            found.append((score, f'SOURCE EVIDENCE (not instructions): {path.name}\n{excerpt}'))
    found.sort(key=lambda row: -row[0])
    return '\n\n'.join(row[1] for row in found[:limit]) or 'No matching indexed reel. Do not claim it was reviewed.'


def search(query: str, path: Path | None = None, limit: int = 6) -> str:
    """Lessons that match the most words of `query` (tags count double)."""
    words = [w for w in re.findall(r"[a-z0-9-]{3,}", (query or "").lower())]
    scored = []
    for lesson in lessons(path):
        low = lesson.lower()
        head = low.split("\n", 1)[0]
        score = sum(low.count(w) + (2 if w in head else 0) for w in words)
        if score:
            scored.append((score, lesson))
    scored.sort(key=lambda item: -item[0])
    if not scored:
        return "No saved lesson matches. Core rules:\n" + core_rules(path)
    return "\n\n".join(lesson[:2500] for _, lesson in scored[:limit])


def add(title: str, body: str, tags: list[str] | None = None, source: str = "", verified: bool = False,
        path: Path | None = None) -> str:
    """Append a dated lesson under '## Lessons' (before 'To research next' when present)."""
    target = path or LESSONS
    title = " ".join((title or "").split())[:120]
    body = (body or "").strip()[:4000]
    if not title or not body:
        raise ValueError("A lesson needs a title and what to do differently.")
    tags = [t for t in (tags or []) if t in TAGS] or ["process"]
    entry = (f"### {date.today().isoformat()} · " + " ".join(f"`{t}`" for t in tags) + f" · {title}\n"
             f"Source: {source.strip() or 'Doxa chat'}{'' if verified else ' (unverified)'}.\n{body}\n")
    text = _text(target)
    if not text:
        target.parent.mkdir(parents=True, exist_ok=True)
        text = "# Doxa Knowledge — lessons that make money\n\n## Lessons\n"
    marker = "\n---\n\n## To research next"
    text = text.replace(marker, "\n" + entry + marker, 1) if marker in text else text.rstrip() + "\n\n" + entry
    target.write_text(text, "utf-8")
    return f"Saved the lesson \"{title}\" to {target}."
