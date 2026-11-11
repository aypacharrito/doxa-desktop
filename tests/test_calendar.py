"""Google Calendar connector, chat parsing and the approval card. The Google API is always faked."""
import json
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
import urllib.parse
from datetime import date, datetime, time as clock, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from forgemind.browser_intent import browser_task_from_chat
from forgemind.calendar_connector import (SERVICE, CalendarError, EventDraft, GoogleCalendar, KeyringStore,
                                          NotConnected, event_lines, new_event_id)
from forgemind.calendar_intent import (build_draft, calendar_query_day, describe, is_calendar_request,
                                       parse_clock, parse_event_request)
from forgemind.config import Settings
from forgemind.quick_actions import local_brief

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=LA)  # a Tuesday


class MemoryStore:
    def __init__(self, data=None):
        self.data = data

    def get(self):
        return None if self.data is None else dict(self.data)

    def set(self, data):
        self.data = dict(data)

    def clear(self):
        self.data = None


class FakeGoogle:
    """Answers like Google's token + Calendar endpoints and records every call."""

    def __init__(self):
        self.calls = []
        self.events = {}
        self.fail_next = []  # list of (status, payload) to return before normal handling
        self.refresh_error = None

    def __call__(self, method, url, headers, body, timeout):
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        self.calls.append((method, parsed.path, query, headers, body))
        if parsed.netloc == "oauth2.googleapis.com":
            if parsed.path == "/revoke":
                return 200, {}
            if self.refresh_error:
                return self.refresh_error
            return 200, {"access_token": f"access-{len(self.calls)}", "expires_in": 3600}
        if self.fail_next:
            return self.fail_next.pop(0)
        if method == "POST" and parsed.path.endswith("/calendars/primary/events"):
            event = json.loads(body)
            if event.get("id") in self.events:
                return 409, {"error": {"code": 409, "message": "The requested identifier already exists."}}
            event["htmlLink"] = "https://calendar.google.com/event?eid=" + event.get("id", "x")
            self.events[event.get("id")] = event
            return 200, event
        if method == "GET" and "/calendars/primary/events/" in parsed.path:
            return 200, self.events[parsed.path.rsplit("/", 1)[1]]
        if method == "GET" and parsed.path.endswith("/calendars/primary/events"):
            return 200, {"summary": "owner@example.com", "timeZone": "America/Los_Angeles", "items": [
                {"id": "1", "summary": "Call with the Garcias", "status": "confirmed",
                 "start": {"dateTime": "2026-11-03T15:00:00-08:00"}, "end": {"dateTime": "2026-11-03T16:00:00-08:00"}},
                {"id": "2", "summary": "Gone", "status": "cancelled",
                 "start": {"dateTime": "2026-11-03T09:00:00-08:00"}, "end": {"dateTime": "2026-11-03T10:00:00-08:00"}},
                {"id": "3", "summary": "Office closed", "status": "confirmed", "location": "Van Nuys",
                 "start": {"date": "2026-11-03"}, "end": {"date": "2026-11-04"}},
            ]}
        return 404, {"error": {"code": 404, "message": "not found"}}

    def api_calls(self, method=None):
        return [c for c in self.calls if "googleapis.com" not in c[1] and c[1].startswith("/calendar")
                and (method is None or c[0] == method)]


def connected_calendar(google=None):
    store = MemoryStore({"client_id": "cid", "client_secret": "csecret", "token_uri": "https://oauth2.googleapis.com/token",
                         "refresh_token": "refresh-1", "account": "owner@example.com",
                         "time_zone": "America/Los_Angeles"})
    google = google or FakeGoogle()
    return GoogleCalendar(store=store, http=google), google, store


class IntentTests(unittest.TestCase):
    def test_recognizes_calendar_requests(self):
        for text in ["put my 3pm call with the Garcias on my calendar tomorrow",
                     "Can you add lunch with Maria to my calendar on Friday at noon?",
                     "schedule a quote review on my google calendar for 11/20 at 9am",
                     "add an event called Team sync at 4 today",
                     "calendar: dentist Nov 12 10:30am",
                     "please block off 2-4pm tomorrow on my calendar for paperwork"]:
            self.assertTrue(is_calendar_request(text), text)

    def test_ignores_other_chat(self):
        for text in ["Book a DMV appointment in Van Nuys", "what's on my calendar tomorrow?",
                     "How do I add an event to my calendar?", "don't put that on my calendar",
                     "tell me a fun fact about owls", "make a dinner reservation for 4 at 7pm", ""]:
            self.assertFalse(is_calendar_request(text), text)

    def test_calendar_wins_over_browser_for_calendar_phrasing(self):
        text = "schedule an appointment with the Garcias on my calendar Friday at 2pm"
        self.assertTrue(is_calendar_request(text))
        self.assertIsNotNone(browser_task_from_chat(text))  # why app.send checks the calendar first

    def test_read_questions(self):
        today = NOW.date()
        self.assertEqual(calendar_query_day("what's on my calendar tomorrow?", today), today + timedelta(days=1))
        self.assertEqual(calendar_query_day("What do I have on my calendar today", today), today)
        self.assertEqual(calendar_query_day("check my calendar", today), today)
        self.assertEqual(calendar_query_day("what's my schedule on Friday", today), date(2026, 11, 6))
        for text in ["How do I add an event to my calendar?", "put lunch on my calendar tomorrow",
                     "what's the weather tomorrow", "what is a calendar year"]:
            self.assertIsNone(calendar_query_day(text, today), text)


class ParseTests(unittest.TestCase):
    def test_the_garcias_example(self):
        parsed = parse_event_request("put my 3pm call with the Garcias on my calendar tomorrow", NOW)
        self.assertEqual(parsed.title, "Call with the Garcias")
        self.assertEqual(parsed.day, date(2026, 11, 4))
        self.assertEqual((parsed.start, parsed.end), (clock(15), clock(16)))
        self.assertFalse(parsed.all_day)
        self.assertEqual(parsed.attendees, [])

    def test_ranges_durations_dates_and_attendees(self):
        cases = {
            "Schedule a meeting with Bob on Friday from 2pm to 3:30pm on my calendar":
                ("Meeting with Bob", date(2026, 11, 6), clock(14), clock(15, 30)),
            "add dentist appointment to my calendar next tuesday at 10am for 30 minutes":
                ("Dentist appointment", date(2026, 11, 10), clock(10), clock(10, 30)),
            "calendar: Lunch with Maria 12:30 tomorrow":
                ("Lunch with Maria", date(2026, 11, 4), clock(12, 30), clock(13, 30)),
            "put dinner with Sam on my calendar tonight at 7":
                ("Dinner with Sam", date(2026, 11, 3), clock(19), clock(20)),
            "put the quote review on my calendar for 3 to 4pm on the 15th":
                ("The quote review", date(2026, 11, 15), clock(15), clock(16)),
            "add a call on Dec 2 at 9:15am for an hour and a half to my calendar":
                ("Call", date(2026, 12, 2), clock(9, 15), clock(10, 45)),
        }
        for text, (title, day, start, end) in cases.items():
            parsed = parse_event_request(text, NOW)
            self.assertEqual((parsed.title, parsed.day, parsed.start, parsed.end), (title, day, start, end), text)
        parsed = parse_event_request("Can you add a 45 minute call with ana@example.com and joe@ex.co to my calendar "
                                     "on Nov 12 at 9:15am?", NOW)
        self.assertEqual(parsed.attendees, ["ana@example.com", "joe@ex.co"])
        self.assertEqual((parsed.day, parsed.start, parsed.end), (date(2026, 11, 12), clock(9, 15), clock(10)))

    def test_all_day_and_assumptions_are_flagged(self):
        parsed = parse_event_request("put the Garcias' anniversary on my calendar on 11/20", NOW)
        self.assertTrue(parsed.all_day)
        self.assertEqual(parsed.day, date(2026, 11, 20))
        parsed = parse_event_request("add team sync to my calendar at 4", NOW)
        self.assertEqual(parsed.start, clock(16))
        self.assertTrue(any("PM" in note for note in parsed.notes))
        self.assertTrue(any("today" in note for note in parsed.notes))
        parsed = parse_event_request("add standup to my calendar at 9am", NOW.replace(hour=11))
        self.assertEqual(parsed.day, date(2026, 11, 4))  # 9am already passed today
        parsed = parse_event_request("add an event to my calendar tomorrow at 2pm", NOW)
        self.assertEqual(parsed.title, "New event")
        self.assertTrue(any("title" in note for note in parsed.notes))

    def test_dates_roll_into_next_year(self):
        parsed = parse_event_request("put renewal review on my calendar on January 5 at 10am", NOW)
        self.assertEqual(parsed.day, date(2027, 1, 5))

    def test_clock_field(self):
        self.assertEqual(parse_clock("3:00 PM"), clock(15))
        self.assertEqual(parse_clock("3pm"), clock(15))
        self.assertEqual(parse_clock("15:45"), clock(15, 45))
        self.assertEqual(parse_clock("noon"), clock(12))
        self.assertEqual(parse_clock("12:00 AM"), clock(0))
        for bad in ["25:00", "13pm", "soon", "3:75"]:
            with self.assertRaises(ValueError):
                parse_clock(bad)


class DraftTests(unittest.TestCase):
    def draft(self, **changes):
        fields = dict(title="Call with the Garcias", day="2026-11-04", start="3:00 PM", end="4:00 PM",
                      all_day=False, attendees="", time_zone="America/Los_Angeles", today=NOW.date())
        fields.update(changes)
        return build_draft(**fields)

    def test_timed_event_body(self):
        draft = self.draft(event_id="d0abc123")
        body = draft.body()
        self.assertEqual(body["summary"], "Call with the Garcias")
        self.assertEqual(body["start"], {"dateTime": "2026-11-04T15:00:00-08:00", "timeZone": "America/Los_Angeles"})
        self.assertEqual(body["end"]["dateTime"], "2026-11-04T16:00:00-08:00")
        self.assertEqual(body["id"], "d0abc123")
        self.assertNotIn("attendees", body)
        self.assertEqual(describe(draft), "Call with the Garcias — Wed Nov 4, 3:00–4:00 PM (America/Los_Angeles)")

    def test_dst_offset_follows_the_date(self):
        draft = self.draft(day="2026-07-01")
        self.assertTrue(draft.body()["start"]["dateTime"].endswith("-07:00"))

    def test_all_day_overnight_and_attendees(self):
        draft = self.draft(all_day=True, start="", end="")
        self.assertEqual(draft.body()["start"], {"date": "2026-11-04"})
        self.assertEqual(draft.body()["end"], {"date": "2026-11-05"})
        self.assertIn("all day", describe(draft))
        late = self.draft(start="11 PM", end="1 AM")
        self.assertEqual(late.end - late.start, timedelta(hours=2))
        invited = self.draft(attendees="ana@example.com, joe@ex.co", send_invites=True)
        self.assertEqual(invited.body()["attendees"], [{"email": "ana@example.com"}, {"email": "joe@ex.co"}])
        self.assertTrue(invited.send_invites)
        self.assertFalse(self.draft(send_invites=True).send_invites)  # no one to invite
        self.assertTrue(self.draft().event_id)

    def test_rejects_bad_fields(self):
        for changes in [dict(title="  "), dict(day="someday"), dict(start="later"),
                        dict(attendees="the Garcias"), dict(time_zone="Mars/Base"), dict(title="x" * 201)]:
            with self.assertRaises(ValueError, msg=str(changes)):
                self.draft(**changes)

    def test_event_ids_are_valid_for_google(self):
        identifier = new_event_id()
        self.assertTrue(5 <= len(identifier) <= 1024)
        self.assertTrue(set(identifier) <= set("0123456789abcdefghijklmnopqrstuv"))
        self.assertNotEqual(identifier, new_event_id())


class ConnectorTests(unittest.TestCase):
    def test_create_event_refreshes_token_and_never_emails_by_default(self):
        calendar, google, _ = connected_calendar()
        draft = build_draft(title="Call with the Garcias", day="2026-11-04", start="3pm", end="", all_day=False,
                            attendees="ana@example.com", time_zone="America/Los_Angeles", today=NOW.date())
        created = calendar.create_event(draft)
        self.assertTrue(created["link"].startswith("https://calendar.google.com/"))
        token_call = google.calls[0]
        self.assertEqual(token_call[0], "POST")
        self.assertIn(b"grant_type=refresh_token", token_call[4])
        posts = google.api_calls("POST")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][2]["sendUpdates"], "none")
        self.assertTrue(posts[0][3]["Authorization"].startswith("Bearer access-"))
        self.assertEqual(json.loads(posts[0][4])["start"]["dateTime"], "2026-11-04T15:00:00-08:00")
        calendar.create_event(EventDraft("Second", draft.start, draft.end, draft.time_zone))
        refreshes = [c for c in google.calls if c[1] == "/token"]
        self.assertEqual(len(refreshes), 1)  # the access token is reused while valid

    def test_retry_after_lost_response_does_not_duplicate(self):
        calendar, google, _ = connected_calendar()
        draft = build_draft(title="Call", day="2026-11-04", start="3pm", end="", all_day=False, attendees="",
                            time_zone="America/Los_Angeles", today=NOW.date())
        first = calendar.create_event(draft)
        second = calendar.create_event(draft)  # same card, Yes pressed again
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(google.events), 1)

    def test_invites_only_when_asked(self):
        calendar, google, _ = connected_calendar()
        draft = build_draft(title="Call", day="2026-11-04", start="3pm", end="", all_day=False,
                            attendees="ana@example.com", send_invites=True, time_zone="America/Los_Angeles",
                            today=NOW.date())
        calendar.create_event(draft)
        self.assertEqual(google.api_calls("POST")[0][2]["sendUpdates"], "all")

    def test_expired_access_token_is_refreshed_once(self):
        calendar, google, _ = connected_calendar()
        google.fail_next = [(401, {"error": {"code": 401, "message": "Invalid Credentials"}})]
        events = calendar.events_on(date(2026, 11, 3))
        self.assertEqual(len([c for c in google.calls if c[1] == "/token"]), 2)
        self.assertEqual([e["title"] for e in events], ["Call with the Garcias", "Office closed"])

    def test_events_on_reads_one_day_in_calendar_zone(self):
        calendar, google, _ = connected_calendar()
        events = calendar.events_on(date(2026, 11, 3))
        query = google.api_calls("GET")[0][2]
        self.assertEqual(query["timeMin"], "2026-11-03T00:00:00-08:00")
        self.assertEqual(query["timeMax"], "2026-11-04T00:00:00-08:00")
        self.assertEqual(query["singleEvents"], "true")
        self.assertEqual(events[0]["start"].hour, 15)
        self.assertTrue(events[1]["all_day"])
        self.assertEqual(event_lines(events), ["• 3:00 PM–4:00 PM  Call with the Garcias",
                                               "• All day  Office closed · Van Nuys"])

    def test_revoked_permission_asks_to_reconnect(self):
        calendar, google, _ = connected_calendar()
        google.refresh_error = (400, {"error": "invalid_grant", "error_description": "Token has been expired"})
        with self.assertRaises(NotConnected) as caught:
            calendar.events_on(date(2026, 11, 3))
        self.assertIn("Reconnect", str(caught.exception))

    def test_api_errors_are_reported(self):
        calendar, google, _ = connected_calendar()
        google.fail_next = [(403, {"error": {"code": 403, "message": "Calendar API has not been used"}})]
        with self.assertRaises(CalendarError) as caught:
            calendar.events_on(date(2026, 11, 3))
        self.assertEqual(caught.exception.status, 403)
        self.assertIn("Calendar API has not been used", str(caught.exception))

    def test_not_connected(self):
        calendar = GoogleCalendar(store=MemoryStore(), http=Mock())
        self.assertFalse(calendar.connected())
        with self.assertRaises(NotConnected):
            calendar.events_on(date(2026, 11, 3))
        calendar.http.assert_not_called()

    def test_connect_saves_refresh_token_only_in_the_store(self):
        google = FakeGoogle()
        store = MemoryStore()
        calendar = GoogleCalendar(store=store, http=google)
        flow = Mock()
        flow.run_local_server.return_value = SimpleNamespace(refresh_token="refresh-new", token="access-new")
        factory = Mock(return_value=flow)
        with tempfile.TemporaryDirectory() as folder:
            client = Path(folder) / "client.json"
            client.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "cs",
                                                        "token_uri": "https://oauth2.googleapis.com/token"}}))
            info = calendar.connect(client, "owner@example.com", flow_factory=factory)
            self.assertEqual(factory.call_args[0][1], ["https://www.googleapis.com/auth/calendar.events"])
            kwargs = flow.run_local_server.call_args.kwargs
            self.assertEqual(kwargs["login_hint"], "owner@example.com")
            self.assertEqual(kwargs["access_type"], "offline")
            self.assertEqual(info, {"account": "owner@example.com", "time_zone": "America/Los_Angeles"})
            self.assertEqual(store.data["refresh_token"], "refresh-new")
            self.assertNotIn("access-new", json.dumps(store.data))  # access tokens stay in memory
            self.assertTrue(calendar.connected())
            self.assertEqual(calendar.time_zone(), "America/Los_Angeles")
            web = Path(folder) / "web.json"
            web.write_text(json.dumps({"web": {"client_id": "x"}}))
            with self.assertRaises(CalendarError):
                calendar.connect(web, flow_factory=factory)

    def test_disconnect_forgets_and_revokes(self):
        calendar, google, store = connected_calendar()
        calendar.disconnect()
        self.assertIsNone(store.data)
        self.assertFalse(calendar.connected())
        self.assertEqual(google.calls[-1][1], "/revoke")

    def test_keyring_store_uses_its_own_service(self):
        fake = SimpleNamespace(store={})
        fake.set_password = lambda service, account, value: fake.store.__setitem__((service, account), value)
        fake.get_password = lambda service, account: fake.store.get((service, account))
        fake.delete_password = lambda service, account: fake.store.pop((service, account))
        with patch.dict(sys.modules, {"keyring": fake}):
            store = KeyringStore()
            self.assertIsNone(store.get())
            store.set({"refresh_token": "r"})
            self.assertEqual(list(fake.store), [(SERVICE, "google")])
            self.assertEqual(store.get(), {"refresh_token": "r"})
            store.clear()
            self.assertIsNone(store.get())
        self.assertEqual(SERVICE, "ForgeMind.Calendar")


class BriefTests(unittest.TestCase):
    def test_brief_lists_todays_events_once_connected(self):
        settings = SimpleNamespace(personal_brief="")
        calendar, _, _ = connected_calendar()
        events = calendar.events_on(date(2026, 11, 3))
        reply = local_brief(settings, {}, [], today="2026-11-03", calendar=events)
        self.assertIn("Today on your Google Calendar:", reply)
        self.assertIn("3:00 PM–4:00 PM  Call with the Garcias", reply)
        self.assertNotIn("Calendar isn't connected", reply)
        self.assertIn("Nothing on your Google Calendar today.", local_brief(settings, {}, [], today="x", calendar=[]))
        self.assertIn("Couldn't read today's Google Calendar: offline",
                      local_brief(settings, {}, [], today="x", calendar="offline"))
        self.assertIn("Calendar isn't connected", local_brief(settings, {}, [], today="x"))


class FakeApp(tk.Tk):
    """Just enough of ForgeMindApp for the calendar card."""

    def __init__(self, calendar):
        super().__init__()
        self.withdraw()
        self.calendar = calendar
        self.events = __import__("queue").Queue()
        self.db = Mock()
        self.voice = Mock(enabled=False)
        self._voice_turn = False
        self.settings_data = Settings()
        self.transcript = []
        self.statuses = []
        self.refresh_all = Mock()

    def _append(self, tag, text):
        self.transcript.append(text)

    def _set_status(self, text, error=False):
        self.statuses.append(text)

    def pump(self, until, seconds=4.0):
        deadline = time.monotonic() + seconds
        while not until() and time.monotonic() < deadline:
            while not self.events.empty():
                kind, *rest = self.events.get_nowait()
                if kind == "ui":
                    rest[0]()
            self.update()
            time.sleep(0.01)


class CardTests(unittest.TestCase):
    def setUp(self):
        self.calendar, self.google, _ = connected_calendar()
        self.app = FakeApp(self.calendar)
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)

    def tearDown(self):
        for pending in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(pending)
        self.app.destroy()
        self.assertEqual(self.errors, [])

    def offer(self, text):
        from forgemind import calendar_ui
        with patch.object(calendar_ui, "calendar_now", return_value=NOW):
            calendar_ui.offer_event(self.app, text)
        self.app.update()
        return self.app._calendar_card

    def test_nothing_is_written_until_yes(self):
        card = self.offer("put my 3pm call with the Garcias on my calendar tomorrow")
        self.assertEqual(card.fields["title"].get(), "Call with the Garcias")
        self.assertEqual(card.fields["day"].get(), "2026-11-04")
        self.assertEqual((card.fields["start"].get(), card.fields["end"].get()), ("3:00 PM", "4:00 PM"))
        self.assertEqual(self.google.api_calls("POST"), [])
        card.approve()
        self.app.pump(lambda: not card.winfo_exists())
        posts = self.google.api_calls("POST")
        self.assertEqual(len(posts), 1)
        body = json.loads(posts[0][4])
        self.assertEqual(body["summary"], "Call with the Garcias")
        self.assertEqual(body["start"]["dateTime"], "2026-11-04T15:00:00-08:00")
        self.assertIn("Added to your Google Calendar: Call with the Garcias", self.app.transcript[-1])

    def test_no_writes_nothing(self):
        card = self.offer("put my 3pm call with the Garcias on my calendar tomorrow")
        card.decline()
        self.app.update()
        self.assertFalse(card.winfo_exists())
        self.assertEqual(self.google.api_calls("POST"), [])
        self.assertIn("didn't add anything", self.app.transcript[-1])

    def test_owner_edits_are_used_and_bad_input_is_blocked(self):
        card = self.offer("put my 3pm call with the Garcias on my calendar tomorrow")
        card.fields["start"].set("later")
        card.approve()
        self.app.update()
        self.assertIn("Use a time like", card.message.cget("text"))
        self.assertEqual(self.google.api_calls("POST"), [])
        card.fields["start"].set("4:30 PM")
        card.fields["end"].set("5 PM")
        card.fields["title"].set("Garcia family call")
        card.approve()
        self.app.pump(lambda: not card.winfo_exists())
        body = json.loads(self.google.api_calls("POST")[0][4])
        self.assertEqual(body["summary"], "Garcia family call")
        self.assertEqual(body["start"]["dateTime"], "2026-11-04T16:30:00-08:00")
        self.assertEqual(body["end"]["dateTime"], "2026-11-04T17:00:00-08:00")

    def test_failure_keeps_the_card_open_for_a_safe_retry(self):
        card = self.offer("put my 3pm call with the Garcias on my calendar tomorrow")
        self.google.fail_next = [(500, {"error": {"code": 500, "message": "Backend Error"}})]
        card.approve()
        self.app.pump(lambda: "Not added" in card.message.cget("text"))
        self.assertTrue(card.winfo_exists())
        self.assertIn("won't make a duplicate", card.message.cget("text"))
        card.approve()
        self.app.pump(lambda: not card.winfo_exists())
        self.assertEqual(len(self.google.events), 1)

    def test_not_connected_opens_settings_instead(self):
        self.app.calendar = GoogleCalendar(store=MemoryStore(), http=Mock())
        from forgemind import calendar_ui
        reply = calendar_ui.offer_event(self.app, "put lunch on my calendar tomorrow at noon")
        self.app.update()
        self.assertIn("isn't connected", reply)
        self.assertIsNone(getattr(self.app, "_calendar_card", None))
        self.assertTrue(self.app._calendar_panel.winfo_exists())


class PhoneTests(unittest.TestCase):
    def test_phone_request_only_opens_the_card_on_the_pc(self):
        from forgemind.phone_delegate import AppPhoneDelegate
        calendar, google, _ = connected_calendar()
        app = SimpleNamespace(calendar=calendar, events=__import__("queue").Queue(), db=Mock())
        events = list(AppPhoneDelegate(app).chat_stream("put my 3pm call with the Garcias on my calendar tomorrow"))
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("press Yes", events[-1]["reply"])
        self.assertEqual(app.events.get_nowait()[0], "ui")
        self.assertEqual(google.api_calls("POST"), [])

    def test_phone_can_ask_whats_on_today(self):
        from forgemind.phone_delegate import AppPhoneDelegate
        calendar, _, _ = connected_calendar()
        app = SimpleNamespace(calendar=calendar, events=__import__("queue").Queue(), db=Mock())
        with patch("forgemind.phone_delegate.calendar_now", return_value=NOW):
            events = list(AppPhoneDelegate(app).chat_stream("what's on my calendar today?"))
        self.assertIn("Call with the Garcias", events[-1]["reply"])
        self.assertIn("You have 2 events today", events[-1]["reply"])


if __name__ == "__main__":
    unittest.main()
