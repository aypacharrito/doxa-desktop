"""Doxa on your phone: a private local server plus a Cloudflare Tunnel.

* The server listens on 127.0.0.1 only. Nothing on your network can reach it directly.
* Cloudflare Tunnel (cloudflared) makes an outbound connection to Cloudflare and gives you
  an https address that forwards to this server. No router or firewall changes.
* Every API call needs your phone access key. Only a SHA-256 hash of the key is stored.
  Repeated wrong keys lock the API for 10 minutes.
* The phone talks to a delegate object (PhoneDelegate in app.py) that uses the same chat
  path and browser-task controller as the desktop.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol

WEB_ROOT = Path(__file__).with_name("phone_web")
DEFAULT_PORT = 8790
MAX_BODY = 32_000
KEYRING_SERVICE = "ForgeMind Jarvis"
KEYRING_TUNNEL = "cloudflare-tunnel-token"
PUSH_TOKEN = re.compile(r"Expo(?:nent)?PushToken\[[A-Za-z0-9_\-]{10,200}\]")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class PhoneError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class PhoneDelegate(Protocol):
    def status(self) -> dict: ...
    def history(self, limit: int) -> list[dict]: ...
    def chat(self, text: str) -> dict: ...
    def chat_stream(self, text: str): ...
    def push_register(self, token: str) -> dict: ...
    def browser_start(self, task: str) -> dict: ...
    def browser_state(self) -> dict: ...
    def browser_respond(self, request_id: str, value) -> bool: ...
    def stop(self) -> None: ...


class PhoneAccess:
    """Settings for phone access, stored in %LOCALAPPDATA%\\ForgeMind\\phone.json (no secrets in clear)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"enabled": False, "port": DEFAULT_PORT, "key_hash": "", "public_url": "", "use_named_tunnel": False}
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def new_key(self) -> str:
        """Create (or replace) the phone access key. Old phone links stop working. The key is also kept encrypted for
        this Windows account (phone-key.dpapi) so Doxa can show the same pairing QR again (qr_codes.make_both)."""
        key = secrets.token_urlsafe(24)
        self.data["key_hash"] = hashlib.sha256(key.encode()).hexdigest()
        self.save()
        try:
            from .windows_credentials import windows_key
            self.key_path.write_bytes(windows_key(key.encode("utf-8"), True))
        except Exception:
            self.key_path.unlink(missing_ok=True)  # never leave an old key that no longer matches
        return key

    @property
    def key_path(self) -> Path:
        return self.path.with_name("phone-key.dpapi")

    def current_key(self) -> str:
        """The saved phone key, only if it still matches the active one ("" otherwise)."""
        try:
            from .windows_credentials import windows_key
            key = windows_key(self.key_path.read_bytes(), False).decode("utf-8")
        except Exception:
            return ""
        stored = self.data.get("key_hash", "")
        return key if stored and hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), stored) else ""

    local_keys: set = set()  # the PC's own windows (Doxa HQ): random per start, never saved

    def check(self, key: str) -> bool:
        if key and any(hmac.compare_digest(key, local) for local in self.local_keys):
            return True
        stored = self.data.get("key_hash", "")
        if not stored or not key:
            return False
        return hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), stored)

    def add_push_token(self, token: str) -> None:
        token = str(token or "").strip()
        if not PUSH_TOKEN.fullmatch(token):
            raise PhoneError(400, "Not a valid Expo push token.")
        tokens = [t for t in self.data.get("push_tokens", []) if t != token]
        self.data["push_tokens"] = (tokens + [token])[-5:]
        self.save()

    def remove_push_token(self, token: str) -> None:
        self.data["push_tokens"] = [t for t in self.data.get("push_tokens", []) if t != token]
        self.save()

    @property
    def port(self) -> int:
        return int(self.data.get("port") or DEFAULT_PORT)


class Lockout:
    def __init__(self, limit=10, window=600):
        self.limit, self.window, self.failures = limit, window, deque()

    def blocked(self) -> bool:
        now = time.monotonic()
        while self.failures and now - self.failures[0] > self.window:
            self.failures.popleft()
        return len(self.failures) >= self.limit

    def fail(self) -> None:
        self.failures.append(time.monotonic())


def _handler(delegate: PhoneDelegate, access: PhoneAccess, lockout: Lockout):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Doxa"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def _headers(self, status, content_type, length, cache="no-store"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", cache)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'")
            self.end_headers()

        def _json(self, status, data):
            body = json.dumps(data).encode()
            self._headers(status, "application/json", len(body))
            self.wfile.write(body)

        def _stream(self, events):
            """Newline-delimited JSON, flushed per event, so words reach the phone as they are generated."""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

            def chunk(data: bytes):
                self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

            try:
                for event in events:
                    chunk(json.dumps(event).encode() + b"\n")
            except (BrokenPipeError, ConnectionResetError):
                return  # phone went away; the answer is still saved on the PC
            except Exception as exc:
                message = exc.message if isinstance(exc, PhoneError) else "Doxa hit an error while answering."
                chunk(json.dumps({"type": "error", "error": message}).encode() + b"\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        def _authorized(self) -> bool:
            if lockout.blocked():
                raise PhoneError(429, "Too many wrong keys. Phone access is locked for 10 minutes.")
            header = self.headers.get("Authorization", "")
            key = header[7:].strip() if header.lower().startswith("bearer ") else ""
            if not access.check(key):
                lockout.fail()
                raise PhoneError(401, "This phone link is not valid. Get a new link from Doxa > Phone access.")
            return True

        def _body(self, limit: int = MAX_BODY) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > limit:
                raise PhoneError(413, "Message is too large.")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                raise PhoneError(400, "Invalid request.") from None
            if not isinstance(data, dict):
                raise PhoneError(400, "Invalid request.")
            return data

        def _static(self, path: str):
            name = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (WEB_ROOT / name).resolve()
            if WEB_ROOT.resolve() not in target.parents or not target.is_file():
                target = WEB_ROOT / "index.html"
            data = target.read_bytes()
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".webmanifest":
                kind = "application/manifest+json"
            # the bundled libraries (three.js, 700 KB) never change for a given version: let the phone keep them
            vendor = (WEB_ROOT / "vendor").resolve() in target.parents
            self._headers(200, kind, len(data), "public, max-age=2592000, immutable" if vendor else "no-store")
            self.wfile.write(data)

        def _route(self, method: str):
            path = self.path.split("?", 1)[0]
            try:
                if not path.startswith("/api/"):
                    if method != "GET":
                        raise PhoneError(405, "Not allowed.")
                    return self._static(path)
                if path == "/api/ping":
                    return self._json(200, {"ok": True})
                self._authorized()
                if method == "GET" and path == "/api/status":
                    return self._json(200, delegate.status())
                if method == "GET" and path == "/api/history":
                    return self._json(200, {"messages": delegate.history(60)})
                if method == "GET" and path == "/api/browser":
                    return self._json(200, delegate.browser_state())
                if method == "GET" and path == "/api/team":
                    return self._json(200, delegate.team_state())
                if method == "GET" and path == "/api/chats":
                    return self._json(200, delegate.chats())
                if method == "GET" and path.startswith("/api/chats/"):
                    try:
                        chat_id = int(path.rsplit("/", 1)[1])
                    except ValueError:
                        raise PhoneError(404, "Not found.") from None
                    return self._json(200, delegate.chat_history(chat_id))
                if method == "GET" and path.startswith("/api/team/island-art/"):
                    # /api/team/island-art/<thumb|full>/<island>[/<version>]: the Higgsfield renders (1.38.2)
                    parts = path.split("/")[4:]
                    if len(parts) < 2:
                        raise PhoneError(404, "Not found.")
                    data = delegate.team_island_art(parts[0], parts[1])
                    self._headers(200, "image/jpeg", len(data), cache="private, max-age=604800")
                    self.wfile.write(data)
                    return None
                if method == "GET" and path.startswith("/api/team/figure/"):
                    data = delegate.team_figure(path.rsplit("/", 1)[1])
                    self._headers(200, "image/png", len(data))
                    self.wfile.write(data)
                    return None
                if method == "GET" and path.startswith("/api/team/character/"):
                    data, mime = delegate.team_character(path.rsplit("/", 1)[1])
                    self._headers(200, mime, len(data))
                    self.wfile.write(data)
                    return None
                if method == "GET" and path.startswith("/api/speak/"):
                    data = delegate.speech(path.rsplit("/", 1)[1])
                    self._headers(200, "audio/mpeg", len(data))
                    self.wfile.write(data)
                    return None
                if method == "POST" and path == "/api/upload":  # a photo or document from the phone (base64)
                    body = self._body(limit=36_000_000)
                    return self._json(200, delegate.upload(str(body.get("name", "")), str(body.get("data", ""))))
                if method == "POST" and path == "/api/transcribe":  # a voice recording (base64) is bigger than chat
                    body = self._body(limit=12_000_000)
                    return self._json(200, delegate.transcribe(str(body.get("audio", "")), str(body.get("mime", "audio/mp4"))))
                if method == "GET" and path == "/api/code":
                    return self._json(200, delegate.code_state())
                if method == "GET" and path == "/api/screen":
                    query = dict(part.split("=", 1) for part in self.path.partition("?")[2].split("&") if "=" in part)
                    try:
                        width = int(query.get("w", "1280"))
                    except ValueError:
                        width = 1280
                    data = delegate.screen_jpeg(width)
                    self._headers(200, "image/jpeg", len(data))
                    self.wfile.write(data)
                    return None
                if method == "POST":
                    body = self._body()
                    if path == "/api/chat/stream":
                        text = str(body.get("message", "")).strip()
                        if not 1 <= len(text) <= 8000:
                            raise PhoneError(400, "Type a message (up to 8,000 characters).")
                        return self._stream(delegate.chat_stream(text))
                    if path == "/api/push/register":
                        return self._json(200, delegate.push_register(str(body.get("token", ""))))
                    if path == "/api/chat":
                        text = str(body.get("message", "")).strip()
                        if not 1 <= len(text) <= 8000:
                            raise PhoneError(400, "Type a message (up to 8,000 characters).")
                        return self._json(200, delegate.chat(text))
                    if path == "/api/browser/start":
                        return self._json(200, delegate.browser_start(str(body.get("task", ""))))
                    if path == "/api/browser/respond":
                        ok = delegate.browser_respond(str(body.get("id", "")), body.get("value"))
                        return self._json(200 if ok else 409, {"ok": ok, **({} if ok else {"error": "That was already answered."})})
                    if path == "/api/stop":
                        delegate.stop()
                        return self._json(200, {"ok": True})
                    if path == "/api/code/start":
                        return self._json(200, delegate.code_start(str(body.get("task", "")),
                                                                   str(body.get("engine", "auto")),
                                                                   bool(body.get("fresh"))))
                    if path == "/api/code/stop":
                        return self._json(200, delegate.code_stop())
                    if path == "/api/team/decide":
                        return self._json(200, delegate.team_decide(str(body.get("id", "")), bool(body.get("approve"))))
                    if path == "/api/hq/action":
                        return self._json(200, delegate.hq_action(str(body.get("action", "")), body))
                    if path == "/api/team/campaign":
                        return self._json(200, delegate.team_campaign(
                            str(body.get("name", "")), str(body.get("goal", "")), str(body.get("audience", "")),
                            str(body.get("offer", ""))))
                    if path == "/api/team/run":
                        return self._json(200, delegate.team_run(str(body.get("room", ""))))
                    if path == "/api/chats/new":
                        return self._json(200, delegate.new_chat())
                    if path == "/api/speak":
                        return self._json(200, delegate.speak(str(body.get("text", ""))[:3000]))
                raise PhoneError(404, "Not found.")
            except PhoneError as exc:
                self.close_connection = True  # an unread request body must not leak into the next request
                self._json(exc.status, {"error": exc.message})
            except (ValueError, RuntimeError) as exc:
                self.close_connection = True
                self._json(400, {"error": str(exc)[:300]})
            except Exception:
                self.close_connection = True
                self._json(500, {"error": "Doxa hit an unexpected error. Check the desktop app."})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return Handler


class PhoneServer:
    def __init__(self, delegate: PhoneDelegate, access: PhoneAccess):
        self.delegate, self.access = delegate, access
        self.lockout = Lockout()
        self.httpd: ThreadingHTTPServer | None = None

    @property
    def running(self) -> bool:
        return self.httpd is not None

    def start(self, port: int | None = None) -> int:
        if self.httpd:
            return self.httpd.server_address[1]
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.access.port if port is None else port),
                                         _handler(self.delegate, self.access, self.lockout))
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.httpd.server_address[1]

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


def find_cloudflared() -> str | None:
    candidates = [shutil.which("cloudflared")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [str(Path(base) / "cloudflared" / "cloudflared.exe"),
                           str(Path(base) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe"),
                           str(Path(base) / "ForgeMind" / "bin" / "cloudflared.exe")]
    return next((c for c in candidates if c and Path(c).is_file()), None)


QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class Tunnel:
    """Runs cloudflared. Quick mode gives a temporary trycloudflare.com address (good for testing);
    named mode uses your own Cloudflare tunnel token and permanent hostname."""

    def __init__(self, port: int, exe: str | None = None):
        self.port, self.exe = port, exe
        self.process: subprocess.Popen | None = None
        self.url = ""
        self.error = ""
        self.lines: deque[str] = deque(maxlen=40)
        self.ready = False
        self.restarts = 0
        self._desired = None
        self._watch_stop = threading.Event()
        self._recovery_lock = threading.RLock()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _spawn(self, args):
        exe = self.exe or find_cloudflared()
        if not exe:
            raise RuntimeError("Cloudflare's connector (cloudflared) isn't installed. Run SETUP_PHONE_ACCESS.bat once.")
        self._stop_process()
        self.url, self.error = "", ""
        self.process = subprocess.Popen([exe, "tunnel", "--no-autoupdate", *args], stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                        encoding="utf-8", errors="replace",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()

    def _read(self, process=None):
        process = process or self.process
        for line in process.stdout:
            if process is not self.process:
                continue
            self.lines.append(line.rstrip()[:300])
            if 'Registered tunnel connection' in line:
                self.ready, self.error = True, ''
            match = QUICK_URL.search(line)
            if match and not self.url:
                self.url = match.group(0)
            if "error" in line.lower() and "ERR" in line and not self.url:
                self.error = line.strip()[:300]
        if process is self.process:
            self.ready = False
            self.error = self.error or "The tunnel stopped."

    def start_quick(self) -> None:
        self.stop()
        self._desired = ('quick', '', '')
        self._spawn(["--url", f"http://127.0.0.1:{self.port}"])
        self._watch()

    def start_named(self, token: str, public_url: str) -> None:
        if not token.strip():
            raise RuntimeError("Paste your Cloudflare tunnel token first.")
        self.stop()
        self._desired = ('named', token, public_url)
        self._launch_named(token, public_url)
        self._watch()

    def _launch_named(self, token, public_url):
        # The token is passed via the environment so it never appears in process listings.
        exe = self.exe or find_cloudflared()
        if not exe:
            raise RuntimeError("Cloudflare's connector (cloudflared) isn't installed. Run SETUP_PHONE_ACCESS.bat once.")
        self._stop_process()
        env = dict(os.environ, TUNNEL_TOKEN=token.strip())
        self.url, self.error = public_url.strip().rstrip("/"), ""
        self.process = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "run"], stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                        encoding="utf-8", errors="replace", env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()

    def _watch(self):
        self._watch_stop = event = threading.Event()
        threading.Thread(target=self._monitor, args=(event,), daemon=True, name='doxa-tunnel-recovery').start()

    def _recover(self):
        with self._recovery_lock:
            desired = self._desired
            if not desired or self.running:
                return False
            if desired[0] == 'named':
                self._launch_named(desired[1], desired[2])
            else:
                self._spawn(['--url', f'http://127.0.0.1:{self.port}'])
            self.restarts += 1
            return True

    def _monitor(self, event):
        delay = 5
        while not event.wait(delay):
            if self.running:
                delay = 5
                continue
            try:
                self._recover()
                delay = min(60, delay * 2)
            except Exception:
                self.error = 'Cloudflare reconnect pending; retrying automatically.'
                delay = min(60, delay * 2)

    def wait_for_url(self, timeout=25.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.url and self.running:
            time.sleep(0.2)
        return self.url

    def stop(self) -> None:
        with self._recovery_lock:
            self._watch_stop.set()
            self._desired = None
            self._stop_process()

    def _stop_process(self) -> None:
        self.ready = False
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def tunnel_token_get() -> str:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_TUNNEL) or ""
    except Exception:
        return ""


def tunnel_token_set(token: str) -> None:
    """Saved in Windows Credential Manager, not in any file."""
    import keyring
    if token.strip():
        keyring.set_password(KEYRING_SERVICE, KEYRING_TUNNEL, token.strip())
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_TUNNEL)
        except Exception:
            pass


def phone_link(base_url: str, key: str) -> str:
    """The key rides in the URL fragment, which browsers never send to any server."""
    return base_url.rstrip("/") + "/#k=" + key


class PushNotifier:
    """Sends phone notifications through Expo's push service (no account keys needed on this PC).
    Only titles and short summaries are sent; details stay on the PC until the phone asks for them."""

    def __init__(self, access: PhoneAccess, post=None):
        self.access = access
        self._post = post or self._http_post

    @staticmethod
    def _http_post(payload: list[dict]) -> dict:
        import urllib.request
        request = urllib.request.Request(EXPO_PUSH_URL, data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read() or b"{}")

    def send(self, title: str, body: str, data: dict | None = None, *, background=True) -> None:
        tokens = list(self.access.data.get("push_tokens", []))
        if not tokens:
            return
        payload = [{"to": token, "title": title[:80], "body": body[:180], "sound": "default", "priority": "high",
                    "channelId": "doxa", "data": data or {}} for token in tokens]

        def deliver():
            try:
                result = self._post(payload)
            except Exception:
                return  # notifications are best-effort; the app still shows everything when opened
            for token, ticket in zip(tokens, result.get("data", []) if isinstance(result, dict) else []):
                if isinstance(ticket, dict) and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                    self.access.remove_push_token(token)

        if background:
            threading.Thread(target=deliver, daemon=True).start()
        else:
            deliver()

