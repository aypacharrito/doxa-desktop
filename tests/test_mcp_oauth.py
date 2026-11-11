"""1.38.0: one-click plugin sign-in (MCP OAuth), the ready-to-add catalog and the new Plugins page.

No real network: a fake authorization server answers discovery, registration and token calls. The browser is faked by
an opener that calls Doxa's real loopback callback server, so the redirect path is tested for real."""
import base64
import hashlib
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from forgemind import mcp_oauth
from forgemind.plugin_catalog import BY_ID, CATALOG, GROUPS, find, match_url
from forgemind.plugins import PluginStore
from test_plugins import MemorySecrets

MCP = "https://mcp.example.com/mcp"
AS = "https://auth.example.com"


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self.headers = status, headers or {}
        self._body = body
        self.ok = 200 <= status < 300
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeServer:
    """MCP server + authorization server with dynamic registration and PKCE."""

    def __init__(self, open_server=False, with_metadata=True, registration=True):
        self.open, self.with_metadata, self.registration = open_server, with_metadata, registration
        self.registered, self.token_calls, self.challenges = [], [], {}
        self.counter = 0

    def post(self, url, headers=None, json=None, data=None, auth=None, timeout=None, **_):
        if url == MCP:
            if self.open:
                return Resp(200, {"jsonrpc": "2.0", "id": 1, "result": {}})
            return Resp(401, {"error": "unauthorized"}, {
                "WWW-Authenticate": f'Bearer resource_metadata="{MCP.replace("/mcp", "")}/.well-known/'
                                    f'oauth-protected-resource/mcp", scope="read write"'})
        if url == AS + "/register":
            self.registered.append(json)
            return Resp(201, {"client_id": f"client-{len(self.registered)}"})
        if url == AS + "/token":
            self.token_calls.append(dict(data))
            if data["grant_type"] == "authorization_code":
                verifier = data["code_verifier"]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                if self.challenges.get(data["code"]) != challenge:
                    return Resp(400, {"error": "invalid_grant", "error_description": "PKCE mismatch"})
                return Resp(200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600})
            if data["grant_type"] == "refresh_token":
                if data["refresh_token"] != "refresh-1":
                    return Resp(400, {"error": "invalid_grant"})
                self.counter += 1
                return Resp(200, {"access_token": f"access-r{self.counter}", "expires_in": 3600})
        return Resp(404)

    def get(self, url, headers=None, params=None, timeout=None, **_):
        if not self.with_metadata:
            return Resp(404)
        if url == "https://mcp.example.com/.well-known/oauth-protected-resource/mcp":
            return Resp(200, {"resource": MCP, "authorization_servers": [AS]})
        if url == AS + "/.well-known/oauth-authorization-server":
            meta = {"issuer": AS, "authorization_endpoint": AS + "/authorize", "token_endpoint": AS + "/token",
                    "code_challenge_methods_supported": ["S256"]}
            if self.registration:
                meta["registration_endpoint"] = AS + "/register"
            return Resp(200, meta)
        return Resp(404)

    def browser(self, approve=True, state_override=None, error=None):
        """An opener that plays the user approving (or denying) in the browser."""
        def open_url(url):
            query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            self.last_authorize = query
            code = f"code-{len(self.challenges) + 1}"
            self.challenges[code] = query["code_challenge"]
            back = {"state": state_override or query["state"]}
            if approve:
                back["code"] = code
            else:
                back["error"] = error or "access_denied"
            target = query["redirect_uri"] + "?" + "&".join(f"{k}={v}" for k, v in back.items())
            threading.Thread(target=lambda: urllib.request.urlopen(target, timeout=5).read(), daemon=True).start()
            return True
        return open_url


class ProbeTests(unittest.TestCase):
    def test_open_oauth_and_token_kinds(self):
        self.assertEqual(mcp_oauth.probe(MCP, FakeServer(open_server=True))["kind"], "open")
        found = mcp_oauth.probe(MCP, FakeServer())
        self.assertEqual(found["kind"], "oauth")
        self.assertEqual(found["meta"]["token_endpoint"], AS + "/token")
        self.assertEqual(found["meta"]["resource"], MCP)
        self.assertEqual(found["meta"]["scope"], "read write")
        self.assertEqual(mcp_oauth.probe(MCP, FakeServer(with_metadata=False))["kind"], "token")


class SignInTests(unittest.TestCase):
    def test_full_browser_sign_in_with_pkce(self):
        server = FakeServer()
        steps = []
        secret = mcp_oauth.sign_in(MCP, http=server, opener=server.browser(), timeout=10, clock=lambda: 1000,
                                   on_step=steps.append)
        registration = server.registered[0]
        self.assertEqual(registration["token_endpoint_auth_method"], "none")
        self.assertTrue(registration["redirect_uris"][0].startswith("http://127.0.0.1:"))
        self.assertEqual(server.last_authorize["code_challenge_method"], "S256")
        self.assertEqual(server.last_authorize["resource"], MCP)
        self.assertEqual(server.last_authorize["scope"], "read write")
        self.assertEqual(secret["token"], "access-1")
        self.assertEqual(secret["refresh_token"], "refresh-1")
        self.assertEqual(secret["expires_at"], 1000 + 3600)
        self.assertEqual(secret["auth"], "oauth")
        self.assertIn("Approve in the browser…", steps)

    def test_state_mismatch_and_denial_are_refused(self):
        server = FakeServer()
        with self.assertRaisesRegex(mcp_oauth.SignInError, "state"):
            mcp_oauth.sign_in(MCP, http=server, opener=server.browser(state_override="forged"), timeout=10)
        with self.assertRaisesRegex(mcp_oauth.SignInError, "access_denied"):
            mcp_oauth.sign_in(MCP, http=server, opener=server.browser(approve=False), timeout=10)
        self.assertEqual(server.token_calls, [])

    def test_cancel_and_no_registration(self):
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaisesRegex(mcp_oauth.SignInError, "cancelled"):
            mcp_oauth.sign_in(MCP, http=FakeServer(), opener=lambda url: True, timeout=30, cancel=cancel)
        self.assertLess(time.monotonic() - started, 5)
        with self.assertRaisesRegex(mcp_oauth.SignInError, "token"):
            mcp_oauth.sign_in(MCP, http=FakeServer(registration=False), opener=lambda url: True, timeout=5)


class RefreshTests(unittest.TestCase):
    def secret(self, expires_at):
        return {"url": MCP, "auth": "oauth", "token": "access-1", "refresh_token": "refresh-1",
                "expires_at": expires_at, "token_endpoint": AS + "/token", "resource": MCP, "client_id": "c",
                "client_secret": "", "auth_method": "none"}

    def test_refresh_only_when_close_to_expiry(self):
        server = FakeServer()
        same, changed = mcp_oauth.fresh(self.secret(10_000), http=server, clock=lambda: 1000)
        self.assertFalse(changed)
        new, changed = mcp_oauth.fresh(self.secret(1050), http=server, clock=lambda: 1000)
        self.assertTrue(changed)
        self.assertEqual(new["token"], "access-r1")
        self.assertEqual(new["refresh_token"], "refresh-1")  # kept when the server doesn't rotate it
        self.assertEqual(server.token_calls[-1]["resource"], MCP)
        with self.assertRaises(mcp_oauth.SignInError):
            mcp_oauth.fresh(dict(self.secret(1), refresh_token=""), http=server, clock=lambda: 1000)

    def test_store_refreshes_and_marks_expired_sign_ins(self):
        with tempfile.TemporaryDirectory() as root:
            server, secrets = FakeServer(), MemorySecrets()
            store = PluginStore(Path(root) / "plugins.json", secrets, http=server, clock=lambda: 1000)
            good = store.connect("Stripe", MCP, self.secret(1050), "stripe")
            store.connect("Notion", "https://mcp.notion.example/mcp",
                          dict(self.secret(10), refresh_token="wrong", url="https://mcp.notion.example/mcp"), "notion")
            servers = store.servers()
            self.assertEqual([s["name"] for s in servers], [good["name"]])
            self.assertEqual(servers[0]["authorization_token"], "access-r1")
            self.assertEqual(json.loads(secrets.get(good["name"]))["token"], "access-r1")  # saved for next time
            self.assertTrue(store.by_catalog("notion")["needs_sign_in"])
            self.assertNotIn("Notion", store.describe())
            on_disk = (Path(root) / "plugins.json").read_text()
            self.assertNotIn("access-", on_disk)
            self.assertNotIn("refresh-", on_disk)

    def test_signing_in_again_replaces_the_connection(self):
        with tempfile.TemporaryDirectory() as root:
            store = PluginStore(Path(root) / "plugins.json", MemorySecrets())
            first = store.connect("Stripe", MCP, {"token": "a"}, "stripe")
            store._mark(first["name"], needs_sign_in=True)
            again = store.connect("Stripe", MCP, {"token": "b"}, "stripe")
            self.assertEqual(len(store.list()), 1)
            self.assertEqual(again["name"], first["name"])
            self.assertFalse(store.by_catalog("stripe")["needs_sign_in"])
            self.assertEqual(store.servers()[0]["authorization_token"], "b")


class CatalogTests(unittest.TestCase):
    def test_catalog_is_clean(self):
        ids = [p.id for p in CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        for plugin in CATALOG:
            self.assertTrue(plugin.url.startswith("https://"), plugin.id)
            self.assertIn(plugin.group, GROUPS)
            self.assertIn(plugin.auth, ("oauth", "open"))
            self.assertRegex(plugin.color, r"^#[0-9a-fA-F]{6}$")
        self.assertTrue(BY_ID["stripe"].money)
        self.assertGreaterEqual(sum(p.popular for p in CATALOG), 6)

    def test_find_and_match(self):
        self.assertEqual([p.id for p in find("stripe")], ["stripe"])
        self.assertIn("zapier", [p.id for p in find("gmail")])
        self.assertEqual({p.id for p in find(group="Money")}, {"stripe", "paypal", "square"})
        self.assertEqual(match_url("https://mcp.stripe.com/").id, "stripe")
        self.assertIsNone(match_url("https://unknown.example/mcp"))


class PageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        app = self.root
        app.plugins = PluginStore(Path(self.dir.name) / "plugins.json", MemorySecrets())
        app.claude = SimpleNamespace(loaded=True)
        app.cloud = SimpleNamespace(loaded=False)
        app.calendar = SimpleNamespace(connected=lambda: False)
        app.settings_data = SimpleNamespace(pacifica_url="")
        app.phone_access = SimpleNamespace(data={"enabled": True})
        app.show_brains = app.show_calendar = app.show_phone = lambda: None
        from forgemind.plugins_ui import PluginsPage
        self.page = PluginsPage(app)

    def tearDown(self):
        self.root.destroy()
        self.dir.cleanup()

    def buttons(self, text):
        """Text buttons by label; "Connect" = the round + buttons on the tiles (1.38.2)."""
        found = []

        def walk(widget):
            for child in widget.winfo_children():
                if text == "Connect" and getattr(child, "connect_plugin", None):
                    found.append(child)
                elif isinstance(child, tk.Button) and child.cget("text") == text:
                    found.append(child)
                walk(child)
        walk(self.page.body)
        return found

    def test_page_lists_catalog_and_connects_an_open_app(self):
        self.root.update()
        self.assertEqual(len(self.buttons("Connect")), len(CATALOG))
        self.page.set_group("Money")
        self.assertEqual(len(self.buttons("Connect")), 3)
        self.page.set_group("All")
        self.page.search_var.set("deepwiki")
        self.page._search_now()
        self.assertEqual(len(self.buttons("Connect")), 1)
        self.buttons("Connect")[0].command()
        self.assertEqual(self.page.store.by_catalog("deepwiki")["label"], "DeepWiki")
        self.assertEqual(self.buttons("Connect"), [])
        self.assertEqual(len(self.buttons("Remove")), 1)  # now under Your plugins

    def test_oauth_connect_runs_in_background_and_saves_on_success(self):
        done = threading.Event()

        def fake_sign_in(url, meta=None, cancel=None, on_step=None, **_):
            on_step("Approve in the browser…")
            done.wait(5)
            return {"url": url, "auth": "oauth", "token": "t", "expires_at": 0}
        original = mcp_oauth.sign_in
        mcp_oauth.sign_in = fake_sign_in
        try:
            self.page.connect(BY_ID["canva"])
            deadline = time.time() + 3
            while self.page.jobs["canva"]["step"] != "Approve in the browser…" and time.time() < deadline:
                time.sleep(0.02)
            self.page._poll()
            self.assertEqual(self.page.jobs["canva"]["var"].get(), "Approve in the browser…")
            self.assertIsNone(self.page.store.by_catalog("canva"))  # nothing saved before the sign-in finishes
            done.set()
            deadline = time.time() + 3
            while not self.page.jobs["canva"]["done"] and time.time() < deadline:
                time.sleep(0.02)
            self.page._poll()
            self.assertEqual(self.page.store.by_catalog("canva")["auth"], "oauth")
            self.assertNotIn("canva", self.page.jobs)
        finally:
            mcp_oauth.sign_in = original


if __name__ == "__main__":
    unittest.main()


class ReadOnlyPaymentTests(unittest.TestCase):
    TOOLS = ["stripe_api_read", "stripe_api_write", "stripe_api_search", "manage_stripe_accounts",
             "list_available_accounts_or_orgs", "atlas_company_formation", "stripe_reports"]

    class Lister:
        def __init__(self, tools, ok=True):
            self.tools, self.ok, self.calls = tools, ok, []

        def post(self, url, headers=None, json=None, **_):
            self.calls.append(json.get("method"))
            if not self.ok:
                return Resp(500)
            if json.get("method") == "tools/list":
                return SimpleNamespace(ok=True, status_code=200, headers={},
                                       text='event: message\ndata: ' + __import__("json").dumps(
                                           {"result": {"tools": [{"name": t} for t in self.tools]}}))
            return SimpleNamespace(ok=True, status_code=200, headers={"Mcp-Session-Id": "s1"}, text="{}")

        def get(self, *a, **k):
            return Resp(404)

    def store(self, http):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        return PluginStore(Path(self.dir.name) / "plugins.json", MemorySecrets(), http=http)

    def test_payment_plugins_start_read_only_with_write_tools_switched_off(self):
        http = self.Lister(self.TOOLS)
        store = self.store(http)
        store.connect("Stripe", "https://mcp.stripe.com", {"token": "t"}, "stripe")
        server = store.servers()[0]
        blocked = set(server["toolset"]["configs"])
        self.assertEqual(blocked, {"stripe_api_write", "manage_stripe_accounts", "atlas_company_formation"})
        self.assertEqual(store.by_catalog("stripe")["tools"], self.TOOLS)  # cached: no second listing
        store.servers()
        self.assertEqual(http.calls.count("tools/list"), 1)
        store.set_read_only("stripe", False)
        self.assertNotIn("toolset", store.servers()[0])

    def test_unknown_tools_means_everything_off_and_others_are_not_limited(self):
        store = self.store(self.Lister([], ok=False))
        store.connect("PayPal", "https://mcp.paypal.com/mcp", {"token": "t"}, "paypal")
        store.connect("Notion", "https://mcp.notion.com/mcp", {"token": "t"}, "notion")
        servers = {s["name"]: s for s in store.servers()}
        self.assertEqual(servers["paypal"]["toolset"], {"default_config": {"enabled": False}})
        self.assertNotIn("toolset", servers["notion"])

    def test_claude_gets_the_tool_switches_but_the_api_server_entry_stays_clean(self):
        from forgemind.claude_brain import ClaudeBrain
        from forgemind.cloud_brain import CloudBudget
        from test_agent import FakeClient, FakeTools, text_event, turn
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "anthropic-key.dpapi").write_bytes(b"x")
            client = FakeClient([turn("end_turn", [], [text_event("ok")])])
            claude = ClaudeBrain(root, CloudBudget(Path(root) / "b.sqlite3", 2000), client_factory=lambda: client)
            servers = [{"type": "url", "url": "https://mcp.stripe.com", "name": "stripe",
                        "toolset": {"configs": {"stripe_api_write": {"enabled": False}}}}]
            "".join(claude.agent_stream("sys", [{"role": "user", "content": "check stripe"}], FakeTools(),
                                        mcp_servers=servers))
            call = client.calls[0]
            self.assertEqual(call["mcp_servers"], [{"type": "url", "url": "https://mcp.stripe.com", "name": "stripe"}])
            self.assertIn({"type": "mcp_toolset", "mcp_server_name": "stripe",
                           "configs": {"stripe_api_write": {"enabled": False}}}, call["tools"])
