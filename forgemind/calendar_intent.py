"""Recognize calendar requests in chat and turn them into an event draft for the owner to check.

Deterministic, instant, no model call: "put my 3pm call with the Garcias on my calendar tomorrow"
→ title "Call with the Garcias", tomorrow 3:00–4:00 PM. A match never writes anything; it only
fills the event card, and the event is created after the owner presses Yes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .calendar_connector import EventDraft, new_event_id

PREFIX = re.compile(r"^\s*(?:calendar|cal)\s*:\s*(.{2,600})$", re.I | re.S)
ON_CALENDAR = re.compile(r"\b(?:on|to|in|onto|into)\s+(?:my|our|the)\s+(?:google\s+)?calendar\b", re.I)
CREATE_VERB = re.compile(r"\b(?:put|add|schedule|book|block|create|set up|make|pencil|save|stick|throw|enter|plug)\b", re.I)
WRITE_VERB = re.compile(r"\b(?:put|add|book|block|create|set up|make|pencil|save|stick|throw|enter|plug)\b", re.I)
NEW_EVENT =re.compile(r"\b(?:add|create|make|schedule|set up|new)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:calendar\s+)?"
                       r"(?:event|calendar entry|calendar invite)\b", re.I)
NEGATIVE = re.compile(r"\b(?:don't|dont|do not|never|no need to|stop)\b.{0,30}\b(?:calendar|event)\b", re.I)
QUESTION = re.compile(r"^\s*(?:what|whats|what's|when|why|how|is|are|am|do i|does|did|which|who|anything)\b", re.I)
POLITE = re.compile(r"^\s*(?:can|could|would|will) you\b|\bplease\b|\bfor me\b", re.I)
READ = re.compile(r"\b(?:my|the)\s+(?:calendar|schedule|agenda)\b|\bon\s+(?:my\s+)?calendar\b", re.I)
READ_START = re.compile(r"^\s*(?:what|whats|what's|anything|do i have|is there|am i|show|read|check|tell me|give me|"
                        r"how(?:'s|s| is| does| do)\s+(?:my|the)\s+(?:calendar|schedule|agenda|day))\b", re.I)

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
MONTHS = {name: number for number, names in enumerate([
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
    ("nov", "november"), ("dec", "december")], start=1) for name in names}
MONTH = r"(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MERIDIEM = r"(a\.?m\.?|p\.?m\.?)"
CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*" + MERIDIEM + r"?"
DEFAULT_MINUTES = 60


@dataclass
class ParsedEvent:
    title: str
    day: date
    start: time | None = None      # None → all-day
    end: time | None = None
    attendees: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # assumptions the card should point out

    @property
    def all_day(self) -> bool:
        return self.start is None


def is_calendar_request(text: str) -> bool:
    value = text.strip()
    if not value or len(value) > 600 or NEGATIVE.search(value):
        return False
    if PREFIX.match(value):
        return True
    if QUESTION.search(value) and not POLITE.search(value):
        return False  # "What's on my calendar?" is a read, handled by calendar_query_day
    return bool((ON_CALENDAR.search(value) and CREATE_VERB.search(value)) or NEW_EVENT.search(value))


def calendar_query_day(text: str, today: date) -> date | None:
    """'What's on my calendar tomorrow?' → that date. None if this isn't a calendar read."""
    value = text.strip()
    if not value or len(value) > 200 or is_calendar_request(value):
        return None
    if not (READ.search(value) and READ_START.search(value)) or WRITE_VERB.search(value):
        return None
    found = _find_day(value, today)
    return found[0] if found else today


# ── date / time pieces ────────────────────────────────────────

def _year_for(month: int, day_number: int, today: date) -> date:
    candidate = date(today.year, month, day_number)
    return candidate if candidate >= today else date(today.year + 1, month, day_number)


def _find_day(text: str, today: date):
    """Return (date, (start, end) span) for the first date expression, or None."""
    tests = [
        (r"\b(?:on\s+)?(?:the\s+)?day after tomorrow\b", lambda m: today + timedelta(days=2)),
        (r"\b(?:tomorrow|tmrw|tmr)(?:\s+(?:morning|afternoon|evening|night))?\b", lambda m: today + timedelta(days=1)),
        (r"\b(?:today|tonight|this (?:morning|afternoon|evening))\b", lambda m: today),
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
        (r"\b(?:on\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
         lambda m: date(_full_year(m[3]), int(m[1]), int(m[2])) if m[3] else _year_for(int(m[1]), int(m[2]), today)),
        (rf"\b(?:on\s+)?{MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
         lambda m: date(int(m[3]), MONTHS[m[1].lower()], int(m[2])) if m[3]
         else _year_for(MONTHS[m[1].lower()], int(m[2]), today)),
        (rf"\b(?:on\s+)?(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH}(?:,?\s+(\d{{4}}))?\b",
         lambda m: date(int(m[3]), MONTHS[m[2].lower()], int(m[1])) if m[3]
         else _year_for(MONTHS[m[2].lower()], int(m[1]), today)),
        (r"\b(?:on\s+)?(?:(this|next|coming)\s+)?(" + "|".join(WEEKDAYS) + r")\b", lambda m: _weekday(m, today)),
        (r"\bon the (\d{1,2})(?:st|nd|rd|th)\b", lambda m: _day_of_month(int(m[1]), today)),
    ]
    best = None
    for pattern, make in tests:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        try:
            value = make(match)
        except ValueError:
            continue  # e.g. "2/30"
        if best is None or match.start() < best[1][0]:
            best = (value, match.span())
    return best


def _full_year(value: str) -> int:
    year = int(value)
    return year + 2000 if year < 100 else year


def _weekday(match, today: date) -> date:
    target = WEEKDAYS.index(match[2].lower())
    delta = (target - today.weekday()) % 7
    if delta == 0 and (match[1] or "").lower() != "this":
        delta = 7  # "on Monday" said on a Monday means next week
    return today + timedelta(days=delta)


def _day_of_month(number: int, today: date) -> date:
    candidate = date(today.year, today.month, number)
    if candidate < today:
        month = today.month % 12 + 1
        candidate = date(today.year + (today.month == 12), month, number)
    return candidate


def _to_time(hour: int, minute: int, meridiem: str | None, notes: list[str] | None = None,
             hint_pm: bool = False) -> time:
    if minute > 59:
        raise ValueError("minutes")
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError("hour")
        pm = meridiem.lower().startswith("p")
        hour = (hour % 12) + (12 if pm else 0)
    elif hour > 23:
        raise ValueError("hour")
    elif 1 <= hour <= 12:
        # No am/pm said: business hours. 1–6 and evening words → PM, 7–11 → AM, 12 → noon.
        if hour <= 6 or (hint_pm and hour < 12):
            if notes is not None:
                notes.append(f"You didn't say AM or PM, so I used {hour}:{minute:02d} PM.")
            hour += 12
        elif notes is not None and hour != 12:
            notes.append(f"You didn't say AM or PM, so I used {hour}:{minute:02d} AM.")
    return time(hour % 24, minute)


def _find_times(text: str, notes: list[str], hint_pm: bool = False):
    """Return (start, end, spans). end may be None. hint_pm: the request said tonight/evening."""
    lowered = text.lower()
    named = {"noon": time(12), "midday": time(12), "midnight": time(0)}
    range_match = re.search(rf"\b(?:from\s+|at\s+|@\s*)?{CLOCK}\s*(?:-|–|to|until|till)\s*{CLOCK}(?!\s*(?:/|people|guests))",
                            text, re.I)
    if range_match and (range_match[3] or range_match[6] or range_match[2] or range_match[5]):
        h1, m1, mer1, h2, m2, mer2 = range_match.groups()
        mer1 = mer1 or mer2  # "from 3 to 4pm"
        try:
            start = _to_time(int(h1), int(m1 or 0), mer1, notes, hint_pm)
            end = _to_time(int(h2), int(m2 or 0), mer2 or mer1, notes, hint_pm)
            return start, end, [range_match.span()]
        except ValueError:
            pass
    for pattern, has_meridiem in [
        (rf"\b(?:at\s+|@\s*)?(\d{{1,2}})(?::(\d{{2}}))?\s*{MERIDIEM}(?=\W|$)", True),
        (r"\b(?:at\s+|@\s*)?(\d{1,2}):(\d{2})\b", False),
        (r"\b(?:at|@)\s*(\d{1,2})\b(?!\s*(?:minutes?|mins?|hours?|hrs?|people|guests|%|/|\.\d))", False),
    ]:
        match = re.search(pattern, text, re.I)
        if match:
            try:
                meridiem = match.group(3) if has_meridiem else None
                minute = int(match.group(2) or 0) if match.lastindex and match.lastindex >= 2 else 0
                return _to_time(int(match.group(1)), minute, meridiem, notes, hint_pm), None, [match.span()]
            except (ValueError, IndexError):
                continue
    for word, value in named.items():
        match = re.search(rf"\b(?:at\s+)?{word}\b", lowered)
        if match:
            return value, None, [match.span()]
    return None, None, []


def _find_minutes(text: str):
    patterns = [
        (r"\bfor\s+(?:an?\s+|one\s+)?hour and a half\b", lambda m: 90),
        (r"\bfor\s+(?:a\s+)?half(?:\s+an)?\s+hour\b", lambda m: 30),
        (r"\bfor\s+(?:an?|one)\s+hour\b", lambda m: 60),
        (r"\bfor\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", lambda m: round(float(m[1]) * 60)),
        (r"\bfor\s+(\d+)\s*(?:minutes?|mins?|m)\b", lambda m: int(m[1])),
        (r"\b(\d+)[- ]?(?:minute|min)\b", lambda m: int(m[1])),
        (r"\b(\d+)[- ]?hour\b(?!s)", lambda m: int(m[1]) * 60),
    ]
    for pattern, make in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            minutes = make(match)
            if 5 <= minutes <= 24 * 60:
                return minutes, match.span()
    return None, None


LEAD = re.compile(r"^(?:(?:hey|ok|okay)\s+)?(?:doxa|jarvis)?[,:]?\s*(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
                  r"(?:put|add|schedule|book|block(?:\s+(?:off|out))?|create|set up|make|pencil(?:\s+in)?|save|stick|"
                  r"throw|enter|plug(?:\s+in)?)?\s*(?:in\s+)?", re.I)
ARTICLE = re.compile(r"^(?:(?:my|a|an|our|new)\s+)+", re.I)
DANGLING = re.compile(r"(?:^|\s)(?:on|at|for|from|to|and|in|by|with|the)$", re.I)
TAIL = re.compile(r"\s*\b(?:for me|please|thanks|thank you)\b\s*[.!?]*$", re.I)


def _title(text: str, spans: list[tuple[int, int]]) -> str:
    pieces, last = [], 0
    for start, end in sorted(spans):
        if start >= last:
            pieces.append(text[last:start])
            last = end
    pieces.append(text[last:])
    value = " ".join(" ".join(pieces).split())
    value = re.sub(r"\bon the calendar\b|\bcalendar (?:entry|event|invite)\b|\b(?:an?\s+)?event\b(?=\s*(?:for|called|named|:))",
                   " ", value, flags=re.I)
    value = re.sub(r"\b(?:called|named|titled)\b", " ", value, flags=re.I)
    value = " ".join(value.split())
    for _ in range(3):
        value = LEAD.sub("", value, count=1).strip(" ,.;:-")
        value = TAIL.sub("", value).strip(" ,.;:-")
        value = ARTICLE.sub("", value).strip(" ,.;:-")
        while DANGLING.search(value):
            value = DANGLING.sub("", value).strip(" ,.;:-")
    value = value.strip(" \"'?!.")
    if value.lower() in {"event", "calendar event", "new event", "something", "it", "this", "that"}:
        return ""
    return (value[:1].upper() + value[1:])[:200] if value else ""


def parse_event_request(text: str, now: datetime) -> ParsedEvent:
    """Pull title, date, times and attendee emails out of a calendar request. `now` is aware."""
    match = PREFIX.match(text)
    body = (match.group(1) if match else text).strip()
    notes: list[str] = []
    spans: list[tuple[int, int]] = []
    attendees = []
    for found in EMAIL.finditer(body):
        email = found.group(0)
        if email.lower() not in (a.lower() for a in attendees):
            attendees.append(email)
    # Mask emails so their digits never read as dates or times.
    masked = EMAIL.sub(lambda m: "x" * len(m.group(0)), body)
    today = now.date()
    day_found = _find_day(masked, today)
    if day_found:
        day, day_span = day_found
        spans.append(day_span)
        masked = masked[:day_span[0]] + " " * (day_span[1] - day_span[0]) + masked[day_span[1]:]
    else:
        day = None
    minutes, minutes_span = _find_minutes(masked)
    if minutes_span:
        spans.append(minutes_span)
        masked = masked[:minutes_span[0]] + " " * (minutes_span[1] - minutes_span[0]) + masked[minutes_span[1]:]
    hint_pm = bool(re.search(r"\b(?:tonight|evening|afternoon|night)\b", body, re.I))
    start, end, time_spans = _find_times(masked, notes, hint_pm)
    spans += time_spans
    for found in ON_CALENDAR.finditer(body):
        spans.append(found.span())
    if day is None:
        if start is not None and datetime.combine(today, start, now.tzinfo) <= now:
            day = today + timedelta(days=1)
            notes.append("You didn't give a date and that time has passed today, so I used tomorrow.")
        else:
            day = today
            notes.append("You didn't give a date, so I used today.")
    if start is not None and end is None:
        end_moment = datetime.combine(day, start) + timedelta(minutes=minutes or DEFAULT_MINUTES)
        end = end_moment.time()
        if not minutes:
            notes.append("No length given, so it's set for 1 hour.")
    title = _title(body, spans)
    if not title:
        title = "New event"
        notes.append("I couldn't tell what to call it — please add a title.")
    return ParsedEvent(title=title, day=day, start=start, end=end, attendees=attendees, notes=notes)


# ── card fields → validated draft ─────────────────────────────

def parse_clock(value: str) -> time:
    text = value.strip().lower().replace(".", "")
    named = {"noon": time(12), "midday": time(12), "midnight": time(0)}
    if text in named:
        return named[text]
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?", text)
    if not match:
        raise ValueError(f"Use a time like 3:00 PM (got “{value.strip()}”).")
    hour, minute, meridiem = int(match[1]), int(match[2] or 0), match[3]
    if meridiem:
        if not 1 <= hour <= 12 or minute > 59:
            raise ValueError(f"“{value.strip()}” isn't a real time.")
        return time(hour % 12 + (12 if meridiem.startswith("p") else 0), minute)
    if hour > 23 or minute > 59:
        raise ValueError(f"“{value.strip()}” isn't a real time.")
    return time(hour, minute)


def parse_date_field(value: str, today: date | None = None) -> date:
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    found = _find_day(text, today or date.today())
    if found and found[1][1] - found[1][0] >= len(text.strip(" ,.")) - 1:
        return found[0]
    raise ValueError(f"Use a date like 2026-11-04 (got “{text}”).")


def build_draft(*, title: str, day: str, start: str, end: str, all_day: bool, attendees: str,
                time_zone: str, send_invites: bool = False, location: str = "", event_id: str = "",
                today: date | None = None) -> EventDraft:
    name = " ".join(title.split())
    if not name:
        raise ValueError("Add a title for the event.")
    if len(name) > 200:
        raise ValueError("Keep the title under 200 characters.")
    when = parse_date_field(day, today)
    try:
        zone = ZoneInfo(time_zone)
    except Exception as exc:
        raise ValueError(f"Unknown time zone “{time_zone}”.") from exc
    emails = [part.strip() for part in re.split(r"[,;\s]+", attendees) if part.strip()]
    bad = [email for email in emails if not EMAIL.fullmatch(email)]
    if bad:
        raise ValueError("Attendees must be email addresses: " + ", ".join(bad[:3]))
    if len(emails) > 50:
        raise ValueError("That's more than 50 attendees.")
    if all_day:
        begins, ends = when, when + timedelta(days=1)
    else:
        begins = datetime.combine(when, parse_clock(start), zone)
        finish = parse_clock(end) if end.strip() else (datetime.combine(when, parse_clock(start)) +
                                                       timedelta(minutes=DEFAULT_MINUTES)).time()
        ends = datetime.combine(when, finish, zone)
        if ends <= begins:
            ends += timedelta(days=1)  # "11 PM to 1 AM" runs past midnight
        if ends - begins > timedelta(hours=24):
            raise ValueError("The event is longer than a day; check the times.")
    return EventDraft(title=name, start=begins, end=ends, time_zone=time_zone, attendees=emails,
                      location=" ".join(location.split())[:300], send_invites=bool(send_invites and emails),
                      event_id=event_id or new_event_id())


def describe(draft: EventDraft) -> str:
    """One line for chat: 'Call with the Garcias — Wed Nov 4, 3:00–4:00 PM (America/Los_Angeles)'."""
    if draft.all_day:
        when = draft.start.strftime("%a %b ") + str(draft.start.day) + " (all day)"
    else:
        same = draft.start.strftime("%p") == draft.end.strftime("%p")
        first = draft.start.strftime("%I:%M" if same else "%I:%M %p").lstrip("0")
        when = (draft.start.strftime("%a %b ") + str(draft.start.day) + ", " + first + "–" +
                draft.end.strftime("%I:%M %p").lstrip("0") + f" ({draft.time_zone})")
    return f"{draft.title} — {when}"
