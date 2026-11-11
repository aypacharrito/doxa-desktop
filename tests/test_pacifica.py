import io
import json
import queue
import sys
import threading
import types
import unittest
import urllib.error
from types import SimpleNamespace
from unittest import mock

from forgemind import pacifica
from forgemind.browser_intent import browser_task_from_chat
from forgemind.config import Settings
from forgemind.pacifica import PacificaClient, PacificaError, QuoteDraft, quote_request_from_chat
from forgemind.phone_delegate import AppPhoneDelegate

TOKEN = "t" * 40
BASE = "https://pacifica.example.com"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    """Stands in for urllib.request.urlopen; records every request, never touches the network."""

    def __init__(self, body=None, error=None):
        self.requests, self.body, self.error = [], body if body is not None else {"ok": True, "request": {"id": "abc123"}}, error

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return FakeResponse(json.dumps(self.body).encode())


def http_error(code, message=""):
    body = io.BytesIO(json.dumps({"error": message}).encode())
    return urllib.error.HTTPError(BASE, code, "x", {}, body)


class IntentTests(unittest.TestCase):
    def test_quote_requests_are_recognized(self):
        cases = {
            "start a quote for Ana Ruiz, full coverage auto": ("Ana Ruiz", "Auto", "full coverage auto"),
            "Doxa, can you start a new quote request for Mike O'Neil for home and auto please":
                ("Mike O'Neil", "Home & Auto", "home and auto"),
            "create a quote for Ana Ruiz - renters": ("Ana Ruiz", "Renters", "renters"),
            "open a quote for Bob Lee with general liability for his bakery":
                ("Bob Lee", "Commercial", "general liability for his bakery"),
            "new quote for Jo Park: term life 500k": ("Jo Park", "Life", "term life 500k"),
            "make a quote for Ana Ruiz, homeowners": ("Ana Ruiz", "Home", "homeowners"),
            "start a quote for Ana Ruiz": ("Ana Ruiz", "", ""),
        }
        for text, (name, product, coverage) in cases.items():
            draft = quote_request_from_chat(text)
            self.assertIsNotNone(draft, text)
            self.assertEqual((draft.customer_name, draft.product, draft.coverage), (name, product, coverage), text)
            self.assertFalse(draft.refused, text)

    def test_contact_details_are_pulled_into_their_own_fields(self):
        draft = quote_request_from_chat("start a quote for Ana Ruiz, renters, phone (818) 555-1234, Ana@Example.com")
        self.assertEqual(draft.phone, "8185551234")
        self.assertEqual(draft.email, "ana@example.com")
        self.assertEqual(draft.coverage, "renters")

    def test_ordinary_chat_and_website_jobs_are_not_quote_requests(self):
        for text in ["how do I start a quote for a customer?",
                     "what does full coverage auto include",
                     "get me a quote on geico.com",
                     "use my browser to start a quote for Ana Ruiz on the Mercury website",
                     "browser: start a quote for Ana Ruiz, auto",
                     "make a quote for 123 Main St",
                     "write a quote for my wall about courage",
                     ""]:
            self.assertIsNone(quote_request_from_chat(text), text)

    def test_binding_or_carrier_contact_is_refused(self):
        for text in ["start a quote for Ana Ruiz, auto and bind it",
                     "start a quote for Ana Ruiz, full coverage, then submit to Mercury",
                     "create a quote for Ana Ruiz, home, and call the carrier"]:
            draft = quote_request_from_chat(text)
            self.assertTrue(draft.refused, text)
            self.assertIn("never bind", draft.refused)

    def test_quote_intent_is_checked_before_browser_intent(self):
        # browser_intent.OBJECT includes "quote": this message is ALSO a browser task, so app.send and the
        # phone delegate must check the Pacifica intent first (see test_phone_* below).
        text = "make a quote for Ana Ruiz, auto"
        self.assertIsNotNone(browser_task_from_chat(text))
        self.assertIsNotNone(quote_request_from_chat(text))

    def test_payload_is_exactly_the_card(self):
        draft = QuoteDraft(customer_name="Ana Ruiz", coverage="full coverage auto", product="Auto", request_id="r-1")
        self.assertEqual(draft.payload(), {"customerName": "Ana Ruiz", "product": "Auto",
                                           "coverage": "full coverage auto", "phone": "", "email": "",
                                           "source": "doxa", "requestId": "r-1"})
        shown = dict(draft.card_rows())
        self.assertEqual(shown["Customer"], "Ana Ruiz")
        self.assertEqual(shown["Coverage"], "full coverage auto")


class ClientTests(unittest.TestCase):
    def draft(self):
        return QuoteDraft(customer_name="Ana Ruiz", coverage="full coverage auto", product="Auto", request_id="r-1")

    def test_posts_the_payload_with_bearer_token(self):
        opener = Recorder()
        result = PacificaClient(BASE, lambda: TOKEN, opener).create_quote_request(self.draft())
        self.assertEqual(result, {"id": "abc123"})
        (request, timeout), = opener.requests
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, BASE + "/api/integrations/jarvis/quote-requests")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), self.draft().payload())
        self.assertNotIn(TOKEN, request.full_url)
        self.assertNotIn(TOKEN, request.data.decode())
        self.assertEqual(timeout, pacifica.TIMEOUT_SECONDS)

    def test_refused_draft_is_never_sent(self):
        opener = Recorder()
        draft = quote_request_from_chat("start a quote for Ana Ruiz, auto and bind it")
        with self.assertRaises(PacificaError):
            PacificaClient(BASE, lambda: TOKEN, opener).create_quote_request(draft)
        self.assertEqual(opener.requests, [])

    def test_missing_or_short_token_sends_nothing(self):
        for token in ("", "short"):
            opener = Recorder()
            with self.assertRaises(PacificaError) as caught:
                PacificaClient(BASE, lambda: token, opener).create_quote_request(self.draft())
            self.assertIn("Settings", str(caught.exception))
            self.assertEqual(opener.requests, [])

    def test_http_errors_become_plain_messages(self):
        expectations = {401: "rejected Doxa's token", 503: "JARVIS_WORKSPACE_ID", 405: "can't create quote requests",
                        404: "can't create quote requests", 400: "customerName is required", 500: "HTTP 500"}
        for code, words in expectations.items():
            opener = Recorder(error=http_error(code, "customerName is required"))
            with self.assertRaises(PacificaError) as caught:
                PacificaClient(BASE, lambda: TOKEN, opener).create_quote_request(self.draft())
            self.assertIn(words, str(caught.exception), code)
            self.assertEqual(caught.exception.status, code)
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_network_failure(self):
        opener = Recorder(error=urllib.error.URLError("no route"))
        with self.assertRaises(PacificaError) as caught:
            PacificaClient(BASE, lambda: TOKEN, opener).create_quote_request(self.draft())
        self.assertIn("Couldn't reach Pacifica", str(caught.exception))

    def test_server_error_body_is_not_success(self):
        opener = Recorder(body={"ok": False, "error": "Daily limit reached"})
        with self.assertRaises(PacificaError):
            PacificaClient(BASE, lambda: TOKEN, opener).create_quote_request(self.draft())

    def test_connection_check_is_a_read_only_get(self):
        opener = Recorder(body={"requests": []})
        self.assertEqual(PacificaClient(BASE, lambda: TOKEN, opener).check(), 0)
        (request, _), = opener.requests
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertTrue(request.full_url.endswith("/quote-requests?filter=pending&limit=1"))

    def test_base_url_rules(self):
        self.assertEqual(pacifica.clean_base_url("pacifica.example.com/"), "https://pacifica.example.com")
        self.assertEqual(pacifica.clean_base_url("http://localhost:3000"), "http://localhost:3000")
        self.assertEqual(pacifica.clean_base_url(""), "")
        for bad in ("http://pacifica.example.com", "ftp://x.com", "https://u:p@x.com", "https://x.com/?token=1"):
            with self.assertRaises(ValueError, msg=bad):
                pacifica.clean_base_url(bad)

    def test_is_configured(self):
        self.assertTrue(pacifica.is_configured(BASE, lambda: TOKEN))
        self.assertFalse(pacifica.is_configured("", lambda: TOKEN))
        self.assertFalse(pacifica.is_configured(BASE, lambda: "short"))
        self.assertFalse(pacifica.is_configured("http://not-local.com", lambda: TOKEN))


class TokenStorageTests(unittest.TestCase):
    def fake_keyring(self):
        store = {}
        module = types.ModuleType("keyring")
        module.get_password = lambda service, account: store.get((service, account))
        module.set_password = lambda service, account, value: store.__setitem__((service, account), value)
        module.delete_password = lambda service, account: store.pop((service, account))
        return store, module

    def test_token_round_trip_in_credential_manager(self):
        store, module = self.fake_keyring()
        with mock.patch.dict(sys.modules, {"keyring": module}):
            pacifica.token_set("  " + TOKEN + "  ")
            self.assertEqual(store, {("Doxa Pacifica", "jarvis-integration-token"): TOKEN})
            self.assertEqual(pacifica.token_get(), TOKEN)
            with self.assertRaises(ValueError):
                pacifica.token_set("too-short")
            pacifica.token_set("")
            self.assertEqual(store, {})
            self.assertEqual(pacifica.token_get(), "")

    def test_token_is_never_in_settings(self):
        names = [name for name in Settings.__dataclass_fields__ if name.startswith("pacifica")]
        self.assertEqual(names, ["pacifica_url"])
        self.assertNotIn(TOKEN, json.dumps(Settings(pacifica_url=BASE).__dict__))


class DesktopFlowTests(unittest.TestCase):
    """ForgeMindApp methods run against a stand-in app (no Tk window)."""

    def make_app(self, url=BASE):
        messages, shown = [], []
        db = SimpleNamespace(add_message=lambda role, content: messages.append((role, content)))
        app = SimpleNamespace(db=db, settings_data=Settings(pacifica_url=url), events=queue.Queue(),
                              _voice_turn=False, voice=SimpleNamespace(enabled=False),
                              _append=lambda tag, text: shown.append(text), refresh_all=lambda: None,
                              _set_status=lambda *a, **k: None, _send_quote=lambda draft: None)
        return app, messages, shown

    def test_card_opens_and_nothing_is_sent_before_approval(self):
        from app import ForgeMindApp
        app, messages, _ = self.make_app()
        draft = quote_request_from_chat("start a quote for Ana Ruiz, full coverage auto")
        with mock.patch.object(pacifica, "token_get", return_value=TOKEN), \
                mock.patch("forgemind.pacifica_ui.confirm_quote") as card, \
                mock.patch("forgemind.pacifica.urllib.request.urlopen") as urlopen:
            ForgeMindApp.offer_quote(app, "start a quote for Ana Ruiz, full coverage auto", draft)
        card.assert_called_once()
        self.assertIs(card.call_args.args[1], draft)
        urlopen.assert_not_called()
        self.assertIn("won't send it until you do", messages[-1][1])

    def test_not_connected_points_to_settings(self):
        from app import ForgeMindApp
        app, messages, _ = self.make_app(url="")
        draft = quote_request_from_chat("start a quote for Ana Ruiz, auto")
        with mock.patch("forgemind.pacifica_ui.confirm_quote") as card, \
                mock.patch("forgemind.pacifica_ui.open_connection") as settings_panel:
            ForgeMindApp.offer_quote(app, "start a quote for Ana Ruiz, auto", draft)
        card.assert_not_called()
        settings_panel.assert_called_once()
        self.assertIn("Pacifica connection", messages[-1][1])

    def test_refused_request_opens_no_card(self):
        from app import ForgeMindApp
        app, messages, _ = self.make_app()
        draft = quote_request_from_chat("start a quote for Ana Ruiz, auto and bind it")
        with mock.patch.object(pacifica, "token_get", return_value=TOKEN), \
                mock.patch("forgemind.pacifica_ui.confirm_quote") as card:
            ForgeMindApp.offer_quote(app, "start a quote for Ana Ruiz, auto and bind it", draft)
        card.assert_not_called()
        self.assertIn("never bind", messages[-1][1])

    def test_approved_send_posts_once_and_reports_back(self):
        from app import ForgeMindApp
        app, _, _ = self.make_app()
        draft = quote_request_from_chat("start a quote for Ana Ruiz, full coverage auto")
        opener = Recorder()
        done = threading.Event()
        real_client = pacifica.PacificaClient
        with mock.patch.object(pacifica, "token_get", return_value=TOKEN), \
                mock.patch.object(pacifica, "PacificaClient",
                                  side_effect=lambda url: real_client(url, lambda: TOKEN, opener)):
            ForgeMindApp._send_quote(app, draft)
            event = app.events.get(timeout=5)
            done.set()
        self.assertEqual(event[0], "pacifica_done")
        self.assertTrue(event[1])
        self.assertIn("Ana Ruiz", event[2])
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(json.loads(opener.requests[0][0].data)["requestId"], draft.request_id)

    def test_failed_send_says_nothing_was_created(self):
        from app import ForgeMindApp
        app, _, _ = self.make_app()
        draft = quote_request_from_chat("start a quote for Ana Ruiz, auto")
        opener = Recorder(error=http_error(405))
        real_client = pacifica.PacificaClient
        with mock.patch.object(pacifica, "PacificaClient",
                               side_effect=lambda url: real_client(url, lambda: TOKEN, opener)):
            ForgeMindApp._send_quote(app, draft)
            event = app.events.get(timeout=5)
        self.assertFalse(event[1])
        self.assertIn("Nothing was created", event[2])


class PhoneTests(unittest.TestCase):
    def make_app(self):
        class Inference:
            def stream(self, *args, **kwargs):
                raise AssertionError("quote requests must never reach the model")
        db = SimpleNamespace(recent_messages=lambda limit: [], add_message=lambda *a: None, retrieve=lambda t: [])
        return SimpleNamespace(db=db, engine=SimpleNamespace(loaded=True), inference=Inference(),
                               events=queue.Queue(), settings_data=Settings(auto_research=False))

    def test_phone_quote_opens_the_card_on_the_pc_without_the_model(self):
        app = self.make_app()
        result = AppPhoneDelegate(app).chat("make a quote for Ana Ruiz, full coverage auto")
        self.assertEqual(result["kind"], "reply")
        self.assertIn("press Send", result["reply"])
        kind, text, draft = app.events.get_nowait()
        self.assertEqual(kind, "pacifica_offer")
        self.assertEqual(draft.customer_name, "Ana Ruiz")

    def test_phone_binding_request_is_refused(self):
        app = self.make_app()
        result = AppPhoneDelegate(app).chat("start a quote for Ana Ruiz, auto and bind it")
        self.assertIn("never bind", result["reply"])


if __name__ == "__main__":
    unittest.main()
