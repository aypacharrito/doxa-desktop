from __future__ import annotations

import re
from pathlib import Path


CORE_PLAYBOOKS = ("01_REASONING_PLAYBOOK.md", "02_CODING_STANDARDS.md")
STOP_WORDS = {
    "about", "after", "again", "also", "and", "build", "change", "code", "could",
    "every", "for", "from", "have", "into", "make", "more", "that", "the", "then",
    "this", "through", "use", "with", "your",
}


def _terms(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z][a-z0-9_-]{2,}", text.lower())
        if word not in STOP_WORDS
    }


def relevant_playbooks(
    root: Path,
    goal: str,
    *,
    max_files: int = 5,
    max_chars: int = 6500,
) -> str:
    """Return a compact, goal-ranked set of local engineering playbooks."""
    if not root.is_dir() or max_files <= 0 or max_chars <= 0:
        return ""
    goal_terms = _terms(goal)
    ranked: list[tuple[int, str, str]] = []
    for path in sorted(root.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name_terms = _terms(path.stem.replace("_", " "))
        content_terms = _terms(content[:12000])
        score = 8 * len(goal_terms & name_terms) + len(goal_terms & content_terms)
        if path.name in CORE_PLAYBOOKS:
            score += 4
        ranked.append((score, path.name, content))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    sections: list[str] = []
    used = 0
    for _score, name, content in ranked[:max_files]:
        header = f"--- PLAYBOOK: {name} ---\n"
        room = max_chars - used - len(header)
        if room <= 80:
            break
        piece = content[:room]
        sections.append(header + piece)
        used += len(header) + len(piece)
    return "\n\n".join(sections)
