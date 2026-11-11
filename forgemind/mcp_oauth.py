"""One-click sign-in for remote MCP plugins (OAuth 2.1 + PKCE + dynamic client registration).

the owner, 2026-11-10: "I wanna be able to just have links ready and connections just quick ready to add how it would be
here and chatgpt". Anthropic's MCP connector only takes a bearer token, so Doxa does the sign-in itself, the way the
MCP authorization spec describes it:

1. POST `initialize` to the plugin's address. 200 = open (no account). 401 = sign-in needed.
2. Protected-resource metadata (from the 401's `resource_metadata`, or /.well-known/oauth-protected-resource) names
   the authorization server; its metadata gives the authorize, token and registration endpoints.
3. Register Doxa as a public client (no secret) with a loopback redirect on 127.0.0.1 (RFC 8252).
4. Open the browser on the authorize page (PKCE S256, `state`, `resource`); a tiny local server catches the redirect.
5. Swap the code for tokens. Tokens are refreshed shortly before they expire.

Everything returned here is a secret: PluginStore keeps it in Windows Credential Manager, never in a file.
"""
from __future__ import annotations

import base64
import hashlib
import html
import http.server
import re
import secrets
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import requests

PROTOCOL = "2025-06-18"
CLIENT_NAME = "Doxa"
SIGN_IN_SECONDS = 300
REFRESH_EARLY = 120  # seconds before expiry
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
           "MCP-Protocol-Version": PROTOCOL, "User-Agent": "Doxa/1.38 (+mcp)"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "doxa", "version": "1.38"}}}


class SignInError(ValueError):
    """Something the owner can read: what went wrong and what to try."""


def _get_json(http, url):
    try:
        response = http.get(url, headers={"Accept": "application/json", "User-Agent": HEADERS["User-Agent"]},
                            timeout=10)
        if not response.ok:
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError):
        return None


def _origin(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def probe(url, http=requests) -> dict:
    """How does this plugin want to be connected? {"kind": "open"|"oauth"|"token"|"unreachable", ...}."""
    try:
        response = http.post(url, headers=HEADERS, json=INIT, timeout=12)
    except requests.RequestException:
        return {"kind": "unreachable"}
    if response.ok:
        return {"kind": "open"}
    if response.status_code not in (401, 403):
        return {"kind": "unreachable", "http": response.status_code}
    challenge = response.headers.get("WWW-Authenticate", "") or ""
    meta = discover(url, challenge, http)
    if not meta:
        return {"kind": "token"}
    return {"kind": "oauth", "meta": meta}


def discover(url, challenge="", http=requests) -> dict | None:
    """Authorization server metadata for a plugin, plus the `resource` and `scope` to ask for."""
    found = re.search(r'resource_metadata="([^"]+)"', challenge)
    path = urlparse(url).path.rstrip("/")
    prm = None
    for candidate in ([found.group(1)] if found else []) + [
            _origin(url) + "/.well-known/oauth-protected-resource" + path,
            _origin(url) + "/.well-known/oauth-protected-resource"]:
        prm = _get_json(http, candidate)
        if prm:
            break
    prm = prm or {}
    for server in prm.get("authorization_servers") or [_origin(url)]:
        parsed = urlparse(server.rstrip("/"))
        root, tail = f"{parsed.scheme}://{parsed.netloc}", parsed.path
        for candidate in (root + "/.well-known/oauth-authorization-server" + tail,
                          root + "/.well-known/openid-configuration" + tail,
                          server.rstrip("/") + "/.well-known/openid-configuration"):
            meta = _get_json(http, candidate)
            if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                scope = re.search(r'scope="([^"]*)"', challenge)
                scopes = scope.group(1) if scope else " ".join(prm.get("scopes_supported") or [])
                return {"authorization_endpoint": meta["authorization_endpoint"],
                        "token_endpoint": meta["token_endpoint"],
                        "registration_endpoint": meta.get("registration_endpoint", ""),
                        "resource": prm.get("resource") or url, "scope": scopes.strip()}
    return None


def register(meta, redirect_uri, http=requests) -> dict:
    """Dynamic client registration (RFC 7591) as a public client."""
    if not meta.get("registration_endpoint"):
        raise SignInError("This app doesn't support one-click sign-in. Use its token instead (Add by link).")
    body = {"client_name": CLIENT_NAME, "redirect_uris": [redirect_uri], "grant_types": ["authorization_code",
                                                                                        "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"}
    if meta.get("scope"):
        body["scope"] = meta["scope"]
    try:
        response = http.post(meta["registration_endpoint"], json=body, timeout=15,
                             headers={"Accept": "application/json", "User-Agent": HEADERS["User-Agent"]})
        data = response.json() if response.content else {}
    except (requests.RequestException, ValueError):
        raise SignInError("Couldn't reach the app to register Doxa. Check the internet and try again.") from None
    if not response.ok or not data.get("client_id"):
        raise SignInError(f"The app refused to register Doxa (HTTP {response.status_code}).")
    return {"client_id": data["client_id"], "client_secret": data.get("client_secret", ""),
            "auth_method": data.get("token_endpoint_auth_method", "none")}


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(meta, client_id, redirect_uri, challenge, state) -> str:
    query = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
             "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
             "resource": meta["resource"]}
    if meta.get("scope"):
        query["scope"] = meta["scope"]
    joiner = "&" if "?" in meta["authorization_endpoint"] else "?"
    return meta["authorization_endpoint"] + joiner + urlencode(query)


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Doxa</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0c;color:#f3eee5;
font-family:"Segoe UI",system-ui,sans-serif;text-align:center}}h1{{font-weight:600;margin:0 0 8px}}
p{{color:#8e897f;margin:0}}b{{color:#e2b65e}}</style></head><body><main><h1>{title}</h1><p>{text}</p></main></body></html>"""


class Callback:
    """A one-shot local web server on 127.0.0.1 that catches the browser's redirect back to Doxa."""

    def __init__(self):
        outer = self
        self.result = None
        self.done = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (http.server API)
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                ok = "code" in query
                title = "Connected to Doxa" if ok else "Sign-in didn't finish"
                text = ("You can close this tab and go back to <b>Doxa</b>." if ok else
                        html.escape(query.get("error_description") or query.get("error") or "No code came back."))
                body = PAGE.format(title=title, text=text).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if outer.result is None:
                    outer.result = query
                    outer.done.set()

            def log_message(self, *_args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{self.port}/callback"
        threading.Thread(target=self.server.serve_forever, daemon=True, name="doxa-oauth-callback").start()

    def wait(self, timeout, cancel=None) -> dict:
        deadline = time.monotonic() + timeout
        try:
            while not self.done.wait(0.25):
                if cancel is not None and cancel.is_set():
                    raise SignInError("Sign-in cancelled.")
                if time.monotonic() > deadline:
                    raise SignInError("Sign-in timed out. Press Connect again and approve in the browser.")
            return self.result or {}
        finally:
            self.close()

    def close(self):
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def _token_request(token_endpoint, form, client, http):
    auth = None
    form = dict(form, client_id=client["client_id"])
    if client.get("client_secret"):
        if client.get("auth_method") == "client_secret_basic":
            auth = (client["client_id"], client["client_secret"])
            form.pop("client_id")
        else:
            form["client_secret"] = client["client_secret"]
    try:
        response = http.post(token_endpoint, data=form, auth=auth, timeout=20,
                             headers={"Accept": "application/json", "User-Agent": HEADERS["User-Agent"]})
        data = response.json() if response.content else {}
    except (requests.RequestException, ValueError):
        raise SignInError("Couldn't reach the app's sign-in server.") from None
    if not response.ok or not data.get("access_token"):
        reason = data.get("error_description") or data.get("error") or f"HTTP {response.status_code}"
        raise SignInError(f"The app didn't give Doxa a token ({reason}).")
    return data


def _secret(url, meta, client, tokens, now):
    expires = tokens.get("expires_in")
    return {"url": url, "auth": "oauth", "token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "expires_at": (now + int(expires)) if expires else 0,
            "token_endpoint": meta["token_endpoint"], "resource": meta["resource"],
            "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
            "auth_method": client.get("auth_method", "none")}


def sign_in(url, meta=None, *, http=requests, opener=webbrowser.open, timeout=SIGN_IN_SECONDS, cancel=None,
            clock=time.time, on_step=None) -> dict:
    """Run the whole browser sign-in; returns the secret to keep in Credential Manager."""
    step = on_step or (lambda text: None)
    if meta is None:
        found = probe(url, http)
        if found["kind"] != "oauth":
            raise SignInError("This address doesn't offer a browser sign-in.")
        meta = found["meta"]
    callback = Callback()
    try:
        client = register(meta, callback.redirect_uri, http)
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(24)
        step("Opening your browser…")
        opener(authorize_url(meta, client["client_id"], callback.redirect_uri, challenge, state))
        step("Approve in the browser…")
    except Exception:
        callback.close()
        raise
    answer = callback.wait(timeout, cancel)
    if answer.get("state") != state:
        raise SignInError("The sign-in reply didn't match (state). Try again.")
    if not answer.get("code"):
        raise SignInError(answer.get("error_description") or answer.get("error") or "Sign-in was declined.")
    step("Finishing…")
    tokens = _token_request(meta["token_endpoint"], {"grant_type": "authorization_code", "code": answer["code"],
                                                     "redirect_uri": callback.redirect_uri,
                                                     "code_verifier": verifier, "resource": meta["resource"]},
                            client, http)
    return _secret(url, meta, client, tokens, clock())


def list_tools(url, token, http=requests) -> list[str]:
    """Tool names a plugin offers (initialize → tools/list), for the read-only switch. Read-only call."""
    headers = dict(HEADERS, Authorization=f"Bearer {token}") if token else dict(HEADERS)

    def body_of(response):
        text = response.text
        if "data:" in text:  # streamable HTTP may answer as server-sent events
            text = "\n".join(line[5:] for line in text.splitlines() if line.startswith("data:"))
        import json
        return json.loads(text)
    first = http.post(url, headers=headers, json=INIT, timeout=15)
    if not first.ok:
        raise SignInError(f"The plugin answered HTTP {first.status_code}.")
    session = first.headers.get("Mcp-Session-Id")
    if session:
        headers["Mcp-Session-Id"] = session
        http.post(url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=15)
    listed = http.post(url, headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                       timeout=15)
    if not listed.ok:
        raise SignInError(f"The plugin answered HTTP {listed.status_code}.")
    return [tool["name"] for tool in body_of(listed).get("result", {}).get("tools", []) if tool.get("name")]


def fresh(secret: dict, *, http=requests, clock=time.time) -> tuple[dict, bool]:
    """(secret with a valid access token, changed?). Raises SignInError when the owner has to sign in again."""
    if secret.get("auth") != "oauth":
        return secret, False
    now = clock()
    expires = secret.get("expires_at") or 0
    if not expires or expires - REFRESH_EARLY > now:
        return secret, False
    if not secret.get("refresh_token"):
        raise SignInError("Sign-in expired.")
    tokens = _token_request(secret["token_endpoint"], {"grant_type": "refresh_token",
                                                       "refresh_token": secret["refresh_token"],
                                                       "resource": secret.get("resource", secret["url"])},
                            {"client_id": secret["client_id"], "client_secret": secret.get("client_secret", ""),
                             "auth_method": secret.get("auth_method", "none")}, http)
    updated = dict(secret, token=tokens["access_token"],
                   refresh_token=tokens.get("refresh_token") or secret["refresh_token"],
                   expires_at=(now + int(tokens["expires_in"])) if tokens.get("expires_in") else 0)
    return updated, True
