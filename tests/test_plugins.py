import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from forgemind.agent import needs_tools, status_for
from forgemind.claude_brain import ClaudeBrain
from forgemind.cloud_brain import CloudBudget
from forgemind.plugins import MCP_BETA, PluginStore
from test_agent import FakeClient, FakeTools, text_event, turn


class MemorySecrets:
    def __init__(self):
        self.data = {}

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value):
        self.data[name] = value

    def delete(self, name):
        self.data.pop(name, None)


class PluginStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.secrets = MemorySecrets()
        self.store = PluginStore(Path(self.dir.name) / "plugins.json", self.secrets)

    def tearDown(self):
        self.dir.cleanup()

    def test_add_keeps_url_and_token_out_of_the_file(self):
        item = self.store.add("Gmail via Zapier", "https://mcp.zapier.com/api/mcp/s/SECRET123/mcp", "tok-9")
        self.assertEqual(item["name"], "gmail-via-zapier")
        on_disk = (Path(self.dir.name) / "plugins.json").read_text()
        self.assertNotIn("SECRET123", on_disk)
        self.assertNotIn("tok-9", on_disk)
        self.assertEqual(self.store.servers(), [{"type": "url", "url": "https://mcp.zapier.com/api/mcp/s/SECRET123/mcp",
                                                 "name": "gmail-via-zapier", "authorization_token": "tok-9"}])
        self.assertIn("Gmail via Zapier", self.store.describe())

    def test_names_unique_toggle_remove_and_validation(self):
        self.store.add("GitHub", "https://example.com/mcp")
        second = self.store.add("GitHub", "https://example.org/mcp")
        self.assertEqual(second["name"], "github-2")
        self.assertNotIn("authorization_token", self.store.servers()[0])
        self.store.set_enabled("github", False)
        self.assertEqual([s["name"] for s in self.store.servers()], ["github-2"])
        self.store.remove("github-2")
        self.assertEqual(self.store.servers(), [])
        self.assertNotIn("github-2", self.secrets.data)
        for bad in ("http://insecure.example/mcp", "ftp://x", "not a url", ""):
            with self.assertRaises(ValueError):
                self.store.add("x", bad)

    def test_missing_secret_is_skipped(self):
        self.store.add("Notion", "https://example.com/notion")
        self.secrets.data.clear()
        self.assertEqual(self.store.servers(), [])


class AgentPluginTests(unittest.TestCase):
    def test_mcp_servers_become_toolsets_with_beta(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "anthropic-key.dpapi").write_bytes(b"x")
            client = FakeClient([turn("end_turn", [], [text_event("Two new emails.")])])
            claude = ClaudeBrain(root, CloudBudget(Path(root) / "b.sqlite3", 2000), client_factory=lambda: client)
            servers = [{"type": "url", "url": "https://mcp.example.com", "name": "gmail"}]
            out = "".join(claude.agent_stream("sys", [{"role": "user", "content": "check my email"}], FakeTools(),
                                              mcp_servers=servers))
            self.assertEqual(out, "Two new emails.")
            call = client.calls[0]
            self.assertEqual(call["mcp_servers"], servers)
            self.assertEqual(call["betas"], [MCP_BETA])
            self.assertIn({"type": "mcp_toolset", "mcp_server_name": "gmail"}, call["tools"])
            # no plugins → no beta, no mcp_servers
            client2 = FakeClient([turn("end_turn", [], [text_event("ok")])])
            claude2 = ClaudeBrain(root, CloudBudget(Path(root) / "b2.sqlite3", 2000), client_factory=lambda: client2)
            "".join(claude2.agent_stream("sys", [{"role": "user", "content": "x"}], FakeTools()))
            self.assertNotIn("mcp_servers", client2.calls[0])

    def test_status_and_routing_words(self):
        block = SimpleNamespace(type="mcp_tool_use", server_name="gmail", name="find_email", input={})
        self.assertEqual(status_for(block), "Using gmail: find email")
        for text in ("what's new in my email", "draft a reply in gmail", "post this in slack"):
            self.assertTrue(needs_tools(text), text)


if __name__ == "__main__":
    unittest.main()
