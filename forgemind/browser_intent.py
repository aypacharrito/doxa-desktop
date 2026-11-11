"""Recognize chat requests that are really website tasks ("make a DMV appointment").

Deterministic matching only: model output never decides whether a browser opens.
A match only PREPARES the Browser task panel; the owner still presses Start.
"""
from __future__ import annotations

import re

PREFIX = re.compile(r"^\s*(?:browser|web)\s*:\s*(.{3,2400})$", re.I | re.S)
USE_BROWSER = re.compile(r"\b(?:use|open|go (?:on|to)|get on)\s+(?:my|the|your)\s+(?:web\s+)?browser\b|\bgo (?:on|to)\s+\S+\.(?:com|gov|org|net|edu)\b"
                         r"|\bon (?:the|their) (?:website|site)\b|\bonline for me\b|\bdo it (?:online|in (?:the|my) browser)\b", re.I)
VERB = r"(?:book|make|schedule|set up|reserve|order|buy|purchase|renew|register|sign (?:me )?up|apply|fill (?:out|in)|submit|cancel|reschedule|request|get me)"
OBJECT = r"(?:appointment|appt|reservation|table|ticket|tickets|booking|form|application|registration|order|account|renewal|quote|tour|consultation|slot)"
TASK = re.compile(rf"\b{VERB}\b(?:\s+\S+){{0,8}}?\s+{OBJECT}s?\b", re.I)
QUESTION = re.compile(r"^\s*(?:how|what|why|when|where|which|who|is|are|does|do i|should i|can i|could i|would it|tell me how)\b", re.I)
POLITE = re.compile(r"^\s*(?:can|could|would|will) you\b|\bfor me\b|\bplease\b", re.I)
BACK_REFERENCE = re.compile(r"\b(?:it|that|this|the appointment|the reservation|the booking|the form|the order)\b", re.I)
NEGATIVE = re.compile(r"\b(?:don't|do not|never)\b.{0,20}\b(?:book|browser|submit|order)\b", re.I)


def is_web_task(text: str) -> bool:
    value = text.strip()
    if not value or len(value) > 2400 or NEGATIVE.search(value):
        return False
    if QUESTION.search(value) and not POLITE.search(value):
        return False  # "How do I book a DMV appointment?" is a question, not an order
    research = re.search(r"\b(?:research|browse|look through|search|check)\b", value, re.I)
    device = re.search(r"\b(?:my laptop|my computer|my browser|websites?)\b", value, re.I)
    if research and device and not re.search(r"\b(?:don't|do not|never)\b", value, re.I):
        return True
    return bool(USE_BROWSER.search(value) or TASK.search(value))


def browser_task_from_chat(text: str, recent: list[dict[str, str]] | None = None) -> str | None:
    """Return the task to prefill, or None if this message is ordinary chat.

    A short follow-up like "no just use my browser and make the appointment" is combined
    with the earlier request it refers to, so the task stands on its own.
    """
    match = PREFIX.match(text)
    if match:
        return match.group(1).strip()
    if not is_web_task(text):
        return None
    task = text.strip()
    if USE_BROWSER.search(task) and BACK_REFERENCE.search(task) and len(task.split()) <= 25:
        earlier = [m["content"].strip() for m in (recent or []) if m.get("role") == "user" and m.get("content", "").strip()]
        for previous in reversed(earlier):
            if previous != task and is_web_task(previous):
                return f"{previous}\n(Owner follow-up: {task})"
    return task
