"""Plugins: connect any app to Doxa's chat through a remote MCP server (Anthropic's MCP connector).

the owner, 2026-11-06: "add plugins I wanna connect my gmail and anything I want". Each plugin is a remote MCP server URL
(for example a Zapier MCP server with Gmail actions, or any service that publishes an MCP endpoint) plus an optional
token. Claude in chat gets every enabled plugin as an `mcp_toolset` (beta `mcp-client-2025-11-20`); Anthropic makes the
connection server-side.

The URL and token can carry account access, so both live only in Windows Credential Manager (keyring service
"Doxa Plugins", one entry per plugin). `plugins.json` in the data folder holds just names, labels and on/off.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

SERVICE = "Doxa Plugins"
# Tool names that change things (Stripe: stripe_api_write, manage_stripe_accounts, atlas_company_formation, …)
WRITES = re.compile(r"write|create|update|delete|remove|cancel|refund|send|transfer|capture|void|manage|formation|"
                    r"convert|recipient|charge|payout|post|patch|put|set_|add_", re.I)
MCP_BETA = "mcp-client-2025-11-20"
SUGGESTIONS = [
    ("Gmail, Google Sheets, Slack + 8,000 apps (Zapier)", "https://mcp.zapier.com",
     "Make a free MCP server at mcp.zapier.com, add the actions you want (for Gmail: find, read, draft, send), "
     "sign in to those apps there, then copy the server's URL and paste it below."),
    ("Other services", "https://modelcontextprotocol.io/clients",
     "Many apps (GitHub, Notion, Linear, Stripe, Asana…) publish a remote MCP URL in their docs or settings. "
     "Paste it with its token if it needs one."),
]


class KeyringStore:
    """Windows Credential Manager via keyring (same as Doxa's other secrets)."""

    def get(self, name: str) -> str | None:
        import keyring
        return keyring.get_password(SERVICE, name)

    def set(self, name: str, value: str) -> None:
        import keyring
        keyring.set_password(SERVICE, name, value)

    def delete(self, name: str) -> None:
        import keyring
        try:
            keyring.delete_password(SERVICE, name)
        except Exception:
            pass


def slug(label: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:40]
    return value or "plugin"


def clean_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Paste the plugin's full https:// MCP address.")
    return url


class PluginStore:
    def __init__(self, path: Path, secrets=None, http=None, clock=None):
        import time
        self.path = Path(path)
        self.secrets = secrets or KeyringStore()
        self.http = http  # requests-like; None = the real network (mcp_oauth's default)
        self.clock = clock or time.time

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return [item for item in data if isinstance(item, dict) and item.get("name")]
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(items, indent=2), "utf-8")
        temp.replace(self.path)

    def list(self) -> list[dict]:
        return self._load()

    def add(self, label: str, url: str, token: str = "") -> dict:
        return self.connect(label, url, {"url": clean_url(url), "token": (token or "").strip()})

    def connect(self, label: str, url: str, secret: dict, catalog_id: str = "") -> dict:
        """Save a connection. `secret` (url + token, or a full OAuth sign-in) goes to Credential Manager only.
        Signing in again to a catalog app replaces its old connection instead of adding a second one."""
        url = clean_url(url)
        label = (label or "").strip()[:60] or urlparse(url).netloc
        items = self._load()
        if catalog_id:
            for item in items:
                if item.get("catalog") == catalog_id:
                    self.secrets.set(item["name"], json.dumps(dict(secret, url=url)))
                    item.update(enabled=True, needs_sign_in=False)
                    self._save(items)
                    return item
        base, name, n = slug(label), slug(label), 2
        while any(item["name"] == name for item in items):
            name, n = f"{base}-{n}", n + 1
        self.secrets.set(name, json.dumps(dict(secret, url=url)))
        item = {"name": name, "label": label, "enabled": True, "host": urlparse(url).netloc}
        if catalog_id:
            item["catalog"] = catalog_id
        if secret.get("auth") == "oauth":
            item["auth"] = "oauth"
        self._save(items + [item])
        return item

    def by_catalog(self, catalog_id: str) -> dict | None:
        return next((item for item in self._load() if item.get("catalog") == catalog_id), None)

    def _mark(self, name: str, **fields) -> None:
        items = self._load()
        for item in items:
            if item["name"] == name:
                item.update(fields)
        self._save(items)

    def remove(self, name: str) -> None:
        self._save([item for item in self._load() if item["name"] != name])
        self.secrets.delete(name)

    def set_enabled(self, name: str, enabled: bool) -> None:
        items = self._load()
        for item in items:
            if item["name"] == name:
                item["enabled"] = bool(enabled)
        self._save(items)

    def servers(self) -> list[dict]:
        """`mcp_servers` for the Messages API: enabled plugins whose secret is still in Credential Manager."""
        from . import mcp_oauth
        out = []
        for item in self._load():
            if not item.get("enabled", True) or item.get("needs_sign_in"):
                continue
            try:
                secret = json.loads(self.secrets.get(item["name"]) or "{}")
            except (ValueError, TypeError):
                continue
            if not secret.get("url"):
                continue
            if secret.get("auth") == "oauth":  # refresh the sign-in shortly before it expires
                try:
                    kwargs = {"clock": self.clock} | ({"http": self.http} if self.http is not None else {})
                    secret, changed = mcp_oauth.fresh(secret, **kwargs)
                except mcp_oauth.SignInError:
                    self._mark(item["name"], needs_sign_in=True)
                    continue
                if changed:
                    self.secrets.set(item["name"], json.dumps(secret))
            server = {"type": "url", "url": secret["url"], "name": item["name"]}
            if secret.get("token"):
                server["authorization_token"] = secret["token"]
            if self.read_only(item):
                server["toolset"] = self._read_only_toolset(item, server)
            out.append(server)
        return out

    # --- read-only payment plugins (1.38) -------------------------------------------------------------------
    @staticmethod
    def read_only(item: dict) -> bool:
        """Payment apps start read-only: Doxa's plugin calls run without a per-call approval, so writes (charges,
        refunds, payouts, products) stay off until the owner presses Allow changes."""
        if "read_only" in item:
            return bool(item["read_only"])
        from .plugin_catalog import BY_ID
        plugin = BY_ID.get(item.get("catalog", ""))
        return bool(plugin and plugin.money)

    def set_read_only(self, name: str, read_only: bool) -> None:
        self._mark(name, read_only=bool(read_only))

    def _read_only_toolset(self, item: dict, server: dict) -> dict:
        """Toolset config that switches off every tool whose name writes; everything off if the list is unknown."""
        tools = item.get("tools")
        if not tools:
            from . import mcp_oauth
            try:
                tools = mcp_oauth.list_tools(server["url"], server.get("authorization_token", ""),
                                             **({"http": self.http} if self.http is not None else {}))
            except Exception:
                tools = []
            if tools:
                self._mark(item["name"], tools=tools)  # tool names aren't secret
        if not tools:
            return {"default_config": {"enabled": False}}
        blocked = {name: {"enabled": False} for name in tools if WRITES.search(name)}
        return {"configs": blocked} if blocked else {}

    def describe(self) -> str:
        """One line for Claude's system prompt: which plugins are connected (names only)."""
        on = [item["label"] for item in self._load() if item.get("enabled", True) and not item.get("needs_sign_in")]
        return ("Connected plugins (use their tools when they help): " + ", ".join(on) + ".") if on else ""
