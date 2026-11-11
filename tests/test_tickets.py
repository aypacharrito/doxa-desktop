import base64
import io
import json
import queue
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from forgemind import tickets
from forgemind.claude_brain import ClaudeBrain
from forgemind.cloud_brain import CloudBrain
from forgemind.config import Settings
from forgemind.phone_delegate import AppPhoneDelegate

TODAY = date(2026, 11, 5)


def extraction(**extra):
    data = {"is_ticket": True, "citation_number": "LA123456", "court_name": "Superior Court of California, County of "
            "Los Angeles — Van Nuys Courthouse West", "court_address": "14400 Erwin St Mall, Van Nuys, CA 91401",
            "county": "Los Angeles", "agency": "LAPD",
            "violations": [{"code": "VC 22350", "section": "VC", "description": "Unsafe speed"},
                           {"code": "21453(a)", "section": "VC", "description": ""}],
            "violation_date": "10/20/2026", "violation_time": "8:15 AM", "location": "Sepulveda Blvd & Victory Blvd",
            "due_date": "12/04/2026", "bail_amount": "$367.00", "kind": "traffic", "defendant_name": "the owner Example",
            "statement": "On October 20, 2026 I was driving north.\n\nThe light was [color] when I entered.",
            "defense_points": ["How was the speed measured?", "Is there a current speed survey?"], "unclear": ""}
    data.update(extra)
    return "```json\n" + json.dumps(data) + "\n```"


class FakeEngine:
    display_name = "Claude"
    provider_id = "claude"
    loaded = True
    vision_message = staticmethod(ClaudeBrain.vision_message)

    def __init__(self, text):
        self.text, self.calls = text, []

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000):
        self.calls.append((system, messages, effort, max_tokens))
        yield from (self.text[i:i + 50] for i in range(0, len(self.text), 50))


class FakeBrain:
    def __init__(self, engine):
        self.engine = engine

    def clouds(self, settings):
        return [self.engine] if self.engine else []


def make_photo(folder: Path, name="ticket.jpg", size=(2400, 1800), exif=True) -> Path:
    image = Image.new("RGB", size, "white")
    path = folder / name
    if exif:
        info = Image.Exif()
        info[0x010F] = "PhoneMaker"         # Make
        info[0x8825] = {2: (34.0, 11.0, 0.0)}  # GPS IFD (latitude)
        image.save(path, "JPEG", exif=info)
    else:
        image.save(path)
    return path


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.photo = make_photo(self.root, "my ticket.jpg", (60, 40), exif=False)

    def test_requests(self):
        ask = tickets.ticket_request(f'contest this ticket "{self.photo}" because the light was yellow')
        self.assertEqual(ask.path, str(self.photo))
        self.assertEqual(ask.reason, "because the light was yellow")
        for text in ("Doxa, contest this ticket", "help me fight my speeding ticket", "dispute this citation",
                     "I want a trial by written declaration", "fill out a TR-205 for me", "beat this red-light ticket"):
            ask = tickets.ticket_request(text)
            self.assertIsNotNone(ask, text)
            self.assertEqual(ask.path, "", text)
        unquoted = self.root / "t.png"
        Image.new("RGB", (10, 10)).save(unquoted)
        self.assertEqual(tickets.ticket_request(f"contest this ticket {unquoted}").path, str(unquoted))

    def test_not_requests(self):
        for text in ("how do I contest a ticket?", "what is a TR-205", "buy concert tickets", "contest the election",
                     "find winning products", "is it worth fighting a ticket?", "the ticket price went up"):
            self.assertIsNone(tickets.ticket_request(text), text)

    def test_question_with_a_photo_is_a_request(self):
        self.assertIsNotNone(tickets.ticket_request(f"can you contest this ticket {self.photo}"))

    def test_missing_photo_path_is_ignored(self):
        self.assertEqual(tickets.ticket_request(r"contest this ticket C:\nope\gone.jpg").path, "")


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_resized_exif_removed_and_boxes_blacked_out(self):
        photo = make_photo(self.root)
        with Image.open(photo) as original:
            self.assertTrue(original.getexif())
        data = tickets.prepare_image(photo, boxes=[(0.5, 0.5, 0.75, 0.75)])
        with Image.open(io.BytesIO(data)) as sent:
            self.assertEqual(max(sent.size), tickets.MAX_SIDE)
            self.assertFalse(sent.getexif())
            self.assertNotIn("exif", sent.info)
            width, height = sent.size
            self.assertLess(sum(sent.getpixel((int(width * 0.6), int(height * 0.6)))), 30)  # covered
            self.assertGreater(sum(sent.getpixel((int(width * 0.2), int(height * 0.2)))), 700)  # untouched

    def test_reversed_and_out_of_range_boxes(self):
        photo = make_photo(self.root, size=(400, 300), exif=False)
        data = tickets.prepare_image(photo, boxes=[(1.4, 1.2, 0.9, 0.9)])
        with Image.open(io.BytesIO(data)) as sent:
            self.assertLess(sum(sent.getpixel((395, 295))), 30)
            self.assertGreater(sum(sent.getpixel((10, 10))), 700)

    def test_unreadable_files(self):
        with self.assertRaises(tickets.TicketError):
            tickets.prepare_image(self.root / "missing.jpg")
        heic = self.root / "IMG_1.HEIC"
        heic.write_bytes(b"x")
        with self.assertRaisesRegex(tickets.TicketError, "JPG"):
            tickets.prepare_image(heic)
        fake = self.root / "fake.jpg"
        fake.write_text("not a picture")
        with self.assertRaises(tickets.TicketError):
            tickets.prepare_image(fake)


class VisionMessageTests(unittest.TestCase):
    def test_claude_block(self):
        message = ClaudeBrain.vision_message("read it", "QUJD", "image/jpeg")
        self.assertEqual(message["role"], "user")
        self.assertEqual(message["content"][0], {"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": "QUJD"}})
        self.assertEqual(message["content"][1], {"type": "text", "text": "read it"})

    def test_openai_block(self):
        message = CloudBrain.vision_message("read it", "QUJD")
        self.assertEqual(message["content"][0]["type"], "input_image")
        self.assertEqual(message["content"][0]["image_url"], "data:image/jpeg;base64,QUJD")
        self.assertEqual(message["content"][1], {"type": "input_text", "text": "read it"})

    def test_claude_chat_stream_passes_the_photo_through(self):
        sent = {}

        class Stream:
            text_stream = iter(['{"is_ticket":false}'])

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return SimpleNamespace(usage=SimpleNamespace(input_tokens=2500, output_tokens=400), stop_reason="end_turn")

        def stream(**kwargs):
            sent.update(kwargs)
            return Stream()

        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
        budget = mock.Mock()
        root = Path(tempfile.mkdtemp())
        (root / "anthropic-key.dpapi").write_bytes(b"x")
        brain = ClaudeBrain(root, budget, client_factory=lambda: client)
        message = brain.vision_message("read", "QUJD")
        self.assertEqual("".join(brain.chat_stream("sys", [message])), '{"is_ticket":false}')
        self.assertEqual(sent["messages"][0]["content"][0]["type"], "image")
        budget.finish.assert_called_once()


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.photo = make_photo(self.root, size=(800, 600))

    def test_one_request_with_the_photo_and_notes(self):
        engine = FakeEngine(extraction())
        ticket = tickets.read_ticket(FakeBrain(engine), Settings(), self.photo, boxes=[(0, 0, 0.2, 0.2)],
                                     reason="The light was yellow when I entered.")
        self.assertEqual(len(engine.calls), 1)
        system, messages, effort, _tokens = engine.calls[0]
        self.assertIn("never transcribe the driver's license number", system)
        blocks = messages[0]["content"]
        self.assertEqual(blocks[0]["source"]["media_type"], "image/jpeg")
        with Image.open(io.BytesIO(base64.b64decode(blocks[0]["source"]["data"]))) as sent:
            self.assertLess(sum(sent.getpixel((5, 5))), 30)  # the owner's box was applied before sending
        self.assertIn("The light was yellow", blocks[1]["text"])
        self.assertEqual(ticket.citation_number, "LA123456")
        self.assertEqual(ticket.due_date, "2026-12-04")
        self.assertEqual(ticket.violation_date, "2026-10-20")
        self.assertEqual(ticket.bail_amount, 367.0)
        self.assertEqual([v.code for v in ticket.violations], ["22350", "21453(a)"])
        self.assertEqual(ticket.violations[1].description, "Not stopping at a red signal")  # filled from CODES
        self.assertIn("\n\n", ticket.statement)  # paragraphs kept

    def test_needs_a_cloud_brain(self):
        with self.assertRaisesRegex(tickets.TicketError, "AI brains"):
            tickets.read_ticket(FakeBrain(None), Settings(), self.photo)

    def test_brain_without_vision(self):
        engine = FakeEngine(extraction())
        engine.vision_message = None
        with self.assertRaisesRegex(tickets.TicketError, "can't read photos"):
            tickets.read_ticket(FakeBrain(engine), Settings(), self.photo)


class ParseTests(unittest.TestCase):
    def test_license_numbers_are_masked(self):
        ticket = tickets.parse_ticket(extraction(unclear="DL B1234567 partly hidden",
                                                 statement="My license B1234567 is valid."))
        self.assertNotIn("B1234567", ticket.unclear + ticket.statement)
        self.assertIn("[license number hidden]", ticket.statement)

    def test_not_a_ticket_and_garbage(self):
        with self.assertRaisesRegex(tickets.TicketError, "doesn't look like"):
            tickets.parse_ticket('{"is_ticket": false}')
        for text in ("", "sorry, I can't", '{"citation_number": ', "[1, 2]", '{"is_ticket": true}'):
            with self.assertRaises(tickets.TicketError, msg=text):
                tickets.parse_ticket(text)

    def test_odd_values(self):
        ticket = tickets.parse_ticket(extraction(due_date="sometime", bail_amount="unknown", kind="felony",
                                                 violations=[{"code": ""}, "x", {"code": "cvc 5200"}],
                                                 defense_points="not a list", statement=None))
        self.assertEqual(ticket.due_date, "")
        self.assertEqual(ticket.bail_amount, 0.0)
        self.assertEqual(ticket.kind, "traffic")
        self.assertEqual([(v.code, v.description) for v in ticket.violations], [("5200", "License plate missing")])
        self.assertEqual(ticket.defense_points, [])
        self.assertEqual(ticket.statement, "")

    def test_dates(self):
        for value in ("2026-12-04", "12/04/2026", "12-04-26", "Dec 4, 2026", "December 4 2026", "12.04.2026"):
            self.assertEqual(tickets.parse_date(value), "2026-12-04", value)
        self.assertEqual(tickets.parse_date("13/45/2026"), "")

    def test_violation_lines_round_trip(self):
        violations = tickets.parse_violations("VC 22350 — Unsafe speed\n21453(a)\nVC 4000(a) - expired tags")
        self.assertEqual([(v.section, v.code) for v in violations], [("VC", "22350"), ("VC", "21453(a)"),
                                                                    ("VC", "4000(a)")])
        self.assertEqual(violations[1].description, "Not stopping at a red signal")
        self.assertEqual(violations[2].description, "expired tags")
        again = tickets.parse_violations(tickets.violations_text(violations))
        self.assertEqual([v.code for v in again], ["22350", "21453(a)", "4000(a)"])


class RedraftTests(unittest.TestCase):
    def test_sends_no_name_citation_or_address(self):
        ticket = tickets.parse_ticket(extraction())
        ticket.mailing_address = "123 Main St, Los Angeles"
        engine = FakeEngine('{"statement": "New wording.", "defense_points": ["Was the signal timing correct?"]}')
        statement, points = tickets.redraft_statement(FakeBrain(engine), Settings(), ticket,
                                                      "Light was yellow. Call me at 818-555-1234, dl B7654321")
        self.assertEqual(statement, "New wording.")
        self.assertEqual(points, ["Was the signal timing correct?"])
        prompt = engine.calls[0][1][0]["content"]
        self.assertIsInstance(prompt, str)  # text only, no photo
        for private in ("the owner Example", "LA123456", "123 Main St", "Erwin", "818-555-1234", "B7654321"):
            self.assertNotIn(private, prompt)
        self.assertIn("22350", prompt)
        self.assertIn("Light was yellow", prompt)


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_packet_has_checklist_worksheet_and_declaration(self):
        ticket = tickets.parse_ticket(extraction())
        ticket.mailing_address = "123 Main St"
        path = tickets.build_packet(ticket, self.root, TODAY)
        self.assertEqual(path.name, "Ticket LA123456 - contest by mail.html")
        page = path.read_text("utf-8")
        for expected in ("Not legal advice", "December 04, 2026", "29 days from today", "Mail it by November 24",
                         "$367.00", "14400 Erwin St Mall", "TR-205 worksheet", tickets.FORM_LINK,
                         "DECLARATION OF DEFENDANT", "under penalty of perjury", "VC 22350", "TR-220",
                         "How was the speed measured?", "123 Main St"):
            self.assertIn(expected, page)
        self.assertIn("<p>The light was [color] when I entered.</p>", page)

    def test_everything_is_escaped(self):
        evil = '<script>alert(1)</script>'
        ticket = tickets.Ticket(citation_number='../../<x>"', court_name=evil, defendant_name=evil, location=evil,
                                statement=evil, defense_points=[evil], unclear=evil,
                                violations=[tickets.Violation(code="<b>", description=evil)])
        path = tickets.build_packet(ticket, self.root, TODAY)
        self.assertEqual(path.parent, self.root)
        self.assertNotIn("/", path.name.replace(" - ", ""))
        page = path.read_text("utf-8")
        self.assertNotIn("<script>", page)
        self.assertNotIn("<b>", page.replace("<b>Not legal advice.</b>", "").split("<h2>Checklist")[1].split(
            "</ol>")[1])
        self.assertIn("&lt;script&gt;", page)

    def test_checklist_cases(self):
        late = tickets.Ticket(due_date="2026-11-01", kind="misdemeanor",
                              violations=[tickets.Violation("26708(a)")])
        titles = dict(tickets.checklist(late, TODAY))
        self.assertIn("4 days ago", titles["Deadline passed"])
        self.assertIn("misdemeanor", titles["Check eligibility"])
        self.assertIn("correctable", titles["Fix-it ticket?"])
        self.assertIn("isn't on the ticket", titles["Bail deposit"])
        self.assertIn("wasn't read", titles["Where to mail"])
        parking = dict(tickets.checklist(tickets.Ticket(kind="parking"), TODAY))
        self.assertIn("administrative review", parking["Parking ticket"])
        self.assertIn("wasn't read", parking["Deadline"])
        soon = dict(tickets.checklist(tickets.Ticket(due_date="2026-11-08"), TODAY))
        self.assertTrue(soon["Deadline"].startswith("Very soon"))
        self.assertIn("Mail it by November 05", soon["Deadline"])  # never a mail-by date in the past

    def test_summary(self):
        ticket = tickets.parse_ticket(extraction())
        summary = tickets.chat_summary(ticket, self.root / "p.html", TODAY)
        self.assertIn("LA123456", summary)
        self.assertIn("Not legal advice", summary)
        self.assertIn("didn't file, pay or send", summary)


class PanelTests(unittest.TestCase):
    def test_panel_reads_fills_and_makes_the_packet(self):
        import tkinter as tk
        root = Path(tempfile.mkdtemp())
        photo = make_photo(root, size=(800, 600))
        try:
            app = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        app.withdraw()
        engine = FakeEngine(extraction())
        app.brain, app.settings_data, app.events = FakeBrain(engine), Settings(), queue.Queue()
        posted = []
        app.db = SimpleNamespace(add_message=lambda role, text: posted.append(text))
        app._append = lambda *a: None
        app.refresh_all = lambda: None
        try:
            from forgemind import tickets_ui
            window = tickets_ui.open_helper(app, str(photo), "light was yellow")
            helper = window.ticket_helper
            self.assertIsNotNone(helper["state"]["photo"])
            helper["state"]["boxes"].append((0, 0, 0.1, 0.1))
            helper["read"]()
            kind, callback = app.events.get(timeout=10)
            self.assertEqual(kind, "ui")
            callback()
            self.assertEqual(helper["variables"]["citation_number"].get(), "LA123456")
            self.assertIn("light was yellow", engine.calls[0][1][0]["content"][1]["text"])
            helper["variables"]["mailing_address"].set("123 Main St")
            ticket = helper["current"]()
            self.assertEqual(ticket.due_date, "2026-12-04")
            self.assertEqual([v.code for v in ticket.violations], ["22350", "21453(a)"])
            with mock.patch.object(tickets, "output_dir", return_value=root / "Doxa Legal"), \
                    mock.patch("webbrowser.open") as opened:
                helper["make"]()
            packet = helper["state"]["packet"]
            self.assertTrue(packet.is_file())
            self.assertIn("123 Main St", packet.read_text("utf-8"))
            opened.assert_called_once()
            self.assertIn("packet is ready", posted[-1])
        finally:
            app.destroy()


class RoutingTests(unittest.TestCase):
    def test_desktop_opens_the_helper(self):
        from app import ForgeMindApp
        offered, text = [], "contest this ticket because the officer misread the sign"
        fake = SimpleNamespace(_voice_dispatch=False, _voice_turn=False, busy=False,
                               input=SimpleNamespace(get=lambda *a: text, delete=lambda *a: None),
                               db=SimpleNamespace(recent_messages=lambda n: [], add_message=lambda *a: None),
                               offer_ticket_help=lambda t, ask: offered.append(ask))
        with mock.patch("app.parse_command", return_value=None):
            ForgeMindApp.send(fake)
        self.assertEqual(len(offered), 1)
        self.assertEqual(offered[0].reason, "because the officer misread the sign")

    def test_phone_opens_it_on_the_pc(self):
        class Inference:
            def stream(self, *a, **k):
                raise AssertionError("must not reach the model")
        app = SimpleNamespace(db=SimpleNamespace(recent_messages=lambda n: [], add_message=lambda *a: None),
                              engine=SimpleNamespace(loaded=True), inference=Inference(), events=queue.Queue(),
                              settings_data=Settings(auto_research=False))
        result = AppPhoneDelegate(app).chat("help me fight my speeding ticket")
        self.assertIn("on your PC", result["reply"])
        self.assertEqual(app.events.get_nowait()[0], "ui")


if __name__ == "__main__":
    unittest.main()
