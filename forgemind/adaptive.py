from __future__ import annotations

import re


_GREETING_RE = re.compile(
    r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening)|thanks|thank you)[!.?\s]*$",
    re.IGNORECASE,
)

_EVOLUTION_PATTERNS = (
    re.compile(r"^\s*evolve\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL),
    re.compile(
        r"\b(?:evolve|improve|upgrade|extend|update)\s+(?:yourself|forge\s*mind|forgemind)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:change|modify|rewrite|build on)\s+(?:your|its|the)\s+(?:own\s+)?code\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:add|build|install)\b.{0,100}\b(?:into|to)\s+(?:yourself|forge\s*mind|forgemind)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:make|let|allow|give)\s+(?:yourself|forge\s*mind|forgemind)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:remove|change|replace)\b.{0,100}\b(?:your|forgemind['’]s)\b.{0,50}"
        r"\b(?:interface|ui|behavior|feature|button|checkbox|workflow)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:remove|disable|change)\b.{0,100}\b(?:block|restriction|limit)\w*\b"
        r".{0,100}\b(?:your|forgemind|code)\b",
        re.IGNORECASE | re.DOTALL,
    ),
)

_RESEARCH_WORDS = {
    "current", "currently", "latest", "today", "recent", "news", "price", "version",
    "release", "schedule", "weather", "law", "regulation", "documentation", "docs",
    "source", "sources", "verify", "research", "internet", "online", "web", "search",
    "look up", "find out", "2025", "2026",
}


def evolution_goal_from_chat(text: str, history: list[dict[str, str]] | None = None) -> str | None:
    """Return a direct self-improvement goal, while ignoring ordinary coding requests."""
    stripped = text.strip()
    if not stripped:
        return None
    explicit = _EVOLUTION_PATTERNS[0].match(stripped)
    if explicit:
        return explicit.group(1).strip() or None
    if any(pattern.search(stripped) for pattern in _EVOLUTION_PATTERNS[1:]):
        return stripped
    # Resolve short owner confirmations only against the immediately preceding owner
    # instruction, never against an assistant's generated suggestions or quoted code.
    confirmation = re.fullmatch(
        r"(?:no[, ]+)?(?:you\s+)?(?:do it|do this|implement it|build it|evolve and do this)"
        r"(?:\s+evolve(?:\s+and\s+do\s+this)?)?[.!\s]*", stripped, re.IGNORECASE)
    if confirmation and history:
        previous = next((item["content"] for item in reversed(history) if item["role"] == "user"), "")
        goal = evolution_goal_from_chat(previous)
        if goal:
            return goal
    return None


def should_search_web(text: str) -> bool:
    """Choose web research automatically when a request benefits from current public facts."""
    lowered = " ".join(text.lower().split())
    if not lowered or _GREETING_RE.match(lowered):
        return False
    if "http://" in lowered or "https://" in lowered:
        return True
    explicit_web = bool(re.search(r"\b(?:search|research|look up|browse|google|verify online)\b", lowered))
    if not explicit_web:
        # Arithmetic and personal conversation do not need public search queries.
        if re.search(r"\d+(?:\.\d+)?\s*%", lowered) and re.search(r"\b(?:total|discounted|discount|calculate)\b", lowered):
            return False
        if re.search(r"\b(?:times|multiply|multiplied|divide|divided|plus|minus|calculate)\b|\d\s*[+*/=]\s*\d", lowered):
            return False
        if re.search(r"\b(?:my|our|i|we|you|your|jarvis|doxa)\b", lowered):
            return False
    if any(word in lowered for word in _RESEARCH_WORDS):
        return True
    # General factual questions are researched; personal notes and pasted code stay local.
    question_openers = (
        "who ", "what ", "when ", "where ", "why ", "how ", "which ",
        "is ", "are ", "does ", "do ", "can ", "could ", "should ",
    )
    return (
        ("?" in lowered or lowered.startswith(question_openers))
        and "```" not in text
        and len(lowered.split()) >= 5
    )


def web_query(text: str, max_chars: int = 320) -> str:
    """Create a bounded public search query without sending a large pasted payload."""
    without_code = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    compact = " ".join(without_code.split())
    return compact[:max_chars].rstrip()


def learning_items(text: str) -> list[tuple[str, str, float]]:
    """Capture user-provided facts and corrections as searchable local experience."""
    stripped = " ".join(text.strip().split())
    if len(stripped) < 12 or _GREETING_RE.match(stripped):
        return []
    lowered = stripped.lower()
    correction = any(
        marker in lowered
        for marker in ("actually", "correction", "that's wrong", "that is wrong", "i meant", "remember")
    )
    first_person_fact = bool(
        re.search(r"\b(?:i|we|my|our)\b.{0,80}\b(?:am|are|have|use|uses|want|need|prefer|work|build|pay)\b", lowered)
    )
    declarative = not stripped.endswith("?") and not lowered.startswith(
        ("write ", "make ", "create ", "build ", "show ", "tell ", "explain ", "give ", "find ")
    )
    if correction:
        return [(stripped, "correction", 1.0)]
    if first_person_fact or declarative:
        return [(stripped, "observation", 0.8)]
    return []
