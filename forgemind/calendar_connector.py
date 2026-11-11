"""Google Calendar connector: OAuth sign-in, today's events, and creating an approved event.

Secrets: the refresh token and OAuth client live only in Windows Credential Manager (keyring
service ``ForgeMind.Calendar``). Access tokens stay in memory. The owner signs in and consents
on Google's own page; Doxa never sees a password.

Writes: ``create_event`` is only called after the owner presses "Yes, add it" on the event
card (see ``calendar_ui.py``). Invitations are not emailed unless the owner ticks that box.
"""
from __future__ import annotations

import base64
import json
import secrets as _secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]  # events only; no calendar settings or sharing
SERVICE = "ForgeMind.Calendar"
ACCOUNT = "google"
API = "https://www.googleapis.com/calendar/v3"
TOKEN_URI = "https://oauth2.googleapis.com/token"
TIMEOUT = 12.0

# (method, url, headers, body bytes or None, timeout) -> (status, parsed JSON dict)
Http = Callable[[str, str, dict, "bytes | None", float], "tuple[int, dict]"]


class CalendarError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class NotConnected(CalendarError):
    pass


@dataclass
class EventDraft:
    title: str
    start: datetime | date          # aware datetime, or a date for all-day events
    end: datetime | date            # exclusive end date for all-day events (Google's rule)
    time_zone: str
    attendees: list[str] = field(default_factory=list)
    location: str = ""
    description: str = ""
    send_invites: bool = False
    event_id: str = ""              # client-chosen ID: retrying never makes a duplicate

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    def body(self) -> dict:
        if self.all_day:
            start, end = {"date": self.start.isoformat()}, {"date": self.end.isoformat()}
        else:
            start = {"dateTime": self.start.isoformat(), "timeZone": self.time_zone}
            end = {"dateTime": self.end.isoformat(), "timeZone": self.time_zone}
        body = {"summary": self.title, "start": start, "end": end}
        if self.event_id:
            body["id"] = self.event_id
        if self.location:
            body["location"] = self.location
        if self.description:
            body["description"] = self.description
        if self.attendees:
            body["attendees"] = [{"email": email} for email in self.attendees]
        return body


def new_event_id() -> str:
    """Google event IDs use base32hex characters (0-9, a-v), 5-1024 long."""
    raw = base64.b32hexencode(_secrets.token_bytes(15)).decode("ascii").lower().rstrip("=")
    return "d0" + raw  # 'x' isn't a base32hex character, so no "doxa" prefix


def urllib_http(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except ValueError:
            payload = {}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CalendarError(f"Couldn't reach Google Calendar ({getattr(exc, 'reason', exc)}).") from exc


class KeyringStore:
    """The one place calendar secrets are read or written."""

    def get(self) -> dict | None:
        try:
            import keyring
            saved = keyring.get_password(SERVICE, ACCOUNT)
        except Exception:
            return None
        if not saved:
            return None
        try:
            return json.loads(saved)
        except ValueError:
            return None

    def set(self, data: dict) -> None:
        import keyring
        keyring.set_password(SERVICE, ACCOUNT, json.dumps(data, separators=(",", ":")))

    def clear(self) -> None:
        try:
            import keyring
            keyring.delete_password(SERVICE, ACCOUNT)
        except Exception:
            pass


def _error_message(status: int, payload: dict) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return f"Google Calendar said {status}: {error.get('message', 'request failed')}"
    if isinstance(error, str):
        return f"Google Calendar said {status}: {payload.get('error_description') or error}"
    return f"Google Calendar said {status}."


class GoogleCalendar:
    def __init__(self, *, store=None, http: Http | None = None, clock: Callable[[], float] = time.time):
        self.store = store or KeyringStore()
        self.http = http or urllib_http
        self.clock = clock
        self._lock = threading.Lock()
        self._access = ""
        self._expires = 0.0
        self._saved: dict | None = None

    # ── connection ────────────────────────────────────────────
    def _data(self) -> dict | None:
        if self._saved is None:
            self._saved = self.store.get()
        return self._saved

    def connected(self) -> bool:
        data = self._data()
        return bool(data and data.get("refresh_token"))

    def summary(self) -> dict:
        """Non-secret facts for the UI: which calendar and its time zone."""
        data = self._data() or {}
        return {"connected": self.connected(), "account": data.get("account", ""),
                "time_zone": data.get("time_zone", "")}

    def time_zone(self) -> str:
        return (self._data() or {}).get("time_zone") or ""

    def connect(self, client_file: Path, login_hint: str = "", *, flow_factory=None) -> dict:
        """Opens Google's sign-in page in the owner's browser; blocks until consent or timeout."""
        config = json.loads(Path(client_file).read_text(encoding="utf-8"))
        if "installed" not in config:
            raise CalendarError("Choose an OAuth client of type 'Desktop app' (its JSON starts with \"installed\").")
        if flow_factory is None:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow_factory = InstalledAppFlow.from_client_config
        flow = flow_factory(config, SCOPES)
        extra = {"login_hint": login_hint.strip()} if login_hint.strip() else {}
        credentials = flow.run_local_server(
            port=0, timeout_seconds=300, access_type="offline", prompt="consent",
            success_message="Doxa can now see and add events on your Google Calendar. You can close this tab.",
            **extra)
        if not getattr(credentials, "refresh_token", None):
            raise CalendarError("Google didn't return a lasting permission. Try Connect again.")
        installed = config["installed"]
        data = {"client_id": installed["client_id"], "client_secret": installed.get("client_secret", ""),
                "token_uri": installed.get("token_uri", TOKEN_URI), "refresh_token": credentials.refresh_token}
        with self._lock:
            self._saved = data
            self._access = getattr(credentials, "token", "") or ""
            self._expires = self.clock() + 3000 if self._access else 0.0
        info = self._probe()
        data.update(info)
        self.store.set(data)
        self._saved = data
        return info

    def disconnect(self) -> None:
        """Forget locally and ask Google to revoke the grant (best effort)."""
        data = self._data() or {}
        token = data.get("refresh_token")
        self.store.clear()
        with self._lock:
            self._saved, self._access, self._expires = None, "", 0.0
        if token:
            try:
                self.http("POST", "https://oauth2.googleapis.com/revoke",
                          {"Content-Type": "application/x-www-form-urlencoded"},
                          urllib.parse.urlencode({"token": token}).encode(), 6.0)
            except CalendarError:
                pass

    def _probe(self) -> dict:
        """One cheap read to learn the primary calendar's name and time zone."""
        payload = self._call("GET", "/calendars/primary/events", {"maxResults": "1", "singleEvents": "true"})
        return {"account": payload.get("summary", ""), "time_zone": payload.get("timeZone", "")}

    # ── tokens ────────────────────────────────────────────────
    def _token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._access and self.clock() < self._expires - 60:
                return self._access
            data = self._data()
            if not data or not data.get("refresh_token"):
                raise NotConnected("Google Calendar isn't connected yet. Open Settings → Google Calendar.")
            form = urllib.parse.urlencode({
                "client_id": data["client_id"], "client_secret": data.get("client_secret", ""),
                "refresh_token": data["refresh_token"], "grant_type": "refresh_token"}).encode()
            status, payload = self.http("POST", data.get("token_uri") or TOKEN_URI,
                                        {"Content-Type": "application/x-www-form-urlencoded"}, form, TIMEOUT)
            if status == 400 and payload.get("error") == "invalid_grant":
                raise NotConnected("Google ended Doxa's calendar permission (this happens every 7 days while the "
                                   "Google Cloud app is in Testing). Reconnect in Settings → Google Calendar.")
            if status != 200 or not payload.get("access_token"):
                raise CalendarError(_error_message(status, payload))
            self._access = payload["access_token"]
            self._expires = self.clock() + float(payload.get("expires_in", 3600))
            return self._access

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(2):
            headers = {"Authorization": "Bearer " + self._token(force=attempt > 0), "Accept": "application/json"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            status, payload = self.http(method, url, headers, data, TIMEOUT)
            if status == 401 and attempt == 0:
                continue  # access token expired early; refresh once
            if 200 <= status < 300:
                return payload
            raise CalendarError(_error_message(status, payload), status)
        raise CalendarError("Google Calendar refused the saved permission. Reconnect in Settings → Google Calendar.")

    # ── read ──────────────────────────────────────────────────
    def events_on(self, day: date) -> list[dict]:
        """Events on the primary calendar for one day in the calendar's own time zone."""
        zone = ZoneInfo(self.time_zone() or "UTC")
        start = datetime.combine(day, datetime.min.time(), zone)
        end = start + timedelta(days=1)
        payload = self._call("GET", "/calendars/primary/events", {
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": "50", "timeZone": str(zone),
            "fields": "timeZone,items(id,summary,start,end,status,location,htmlLink)"})
        events = []
        for item in payload.get("items", []):
            if item.get("status") == "cancelled":
                continue
            events.append(_simplify(item, zone))
        return events

    # ── write (only after the owner's Yes) ────────────────────
    def create_event(self, draft: EventDraft) -> dict:
        params = {"sendUpdates": "all" if (draft.send_invites and draft.attendees) else "none"}
        try:
            created = self._call("POST", "/calendars/primary/events", params, draft.body())
        except CalendarError as exc:
            if draft.event_id and exc.status == 409:
                # Same client ID already exists: the first attempt went through. Don't add it twice.
                created = self._call("GET", "/calendars/primary/events/" + draft.event_id)
            else:
                raise
        return {"id": created.get("id", ""), "link": created.get("htmlLink", ""),
                "title": created.get("summary", draft.title)}


def _simplify(item: dict, zone: ZoneInfo) -> dict:
    start, end = item.get("start", {}), item.get("end", {})
    if "dateTime" in start:
        begins = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(zone)
        ends = datetime.fromisoformat(end.get("dateTime", start["dateTime"]).replace("Z", "+00:00")).astimezone(zone)
        return {"title": item.get("summary") or "(no title)", "start": begins, "end": ends, "all_day": False,
                "location": item.get("location", ""), "link": item.get("htmlLink", "")}
    return {"title": item.get("summary") or "(no title)", "start": date.fromisoformat(start.get("date")),
            "end": date.fromisoformat(end.get("date", start.get("date"))), "all_day": True,
            "location": item.get("location", ""), "link": item.get("htmlLink", "")}


def clock_text(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0")


def event_lines(events: list[dict]) -> list[str]:
    lines = []
    for event in events:
        if event["all_day"]:
            when = "All day"
        else:
            when = f"{clock_text(event['start'])}–{clock_text(event['end'])}"
        where = f" · {event['location']}" if event.get("location") else ""
        lines.append(f"• {when}  {event['title']}{where}")
    return lines
