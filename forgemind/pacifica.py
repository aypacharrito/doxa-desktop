"""Pacifica CRM connection: start a quote *request* from chat ("start a quote for Ana Ruiz, full coverage auto").

Safety model (see ..\\CLAUDE.md hard rules):
- Matching is deterministic (regex). The local model never sees the customer's details for this flow, and
  model output never decides whether anything is sent.
- A match only builds a draft. The owner sees exactly what will be sent on a confirmation card and must
  press "Send to Pacifica"; nothing is sent without that click.
- Doxa only creates a quote request in the owner's CRM. It never binds coverage, never contacts carriers and
  never runs carrier quoting (Mercury automation is out of scope). Messages that ask for binding are refused.
- The integration token lives only in Windows Credential Manager (keyring). It is sent only in the
  Authorization header, never in a URL, and is never logged or shown.

Endpoint (Pacifica, your CRM's repo):
  POST {base}/api/integrations/jarvis/quote-requests
  Authorization: Bearer <JARVIS_INTEGRATION_TOKEN>
  {"customerName": "...", "product": "Auto"|"Home"|"Renters"|"Life"|"Commercial"|"Home & Auto"|"",
   "coverage": "...", "phone": "", "email": "", "source": "doxa", "requestId": "<uuid>"}
  -> 200/201 {"ok": true, "request": {"id": "...", ...}}
`requestId` lets the server ignore an accidental resend of the same request.
Read-only check used by "Test connection": GET {base}/api/integrations/jarvis/quote-requests?filter=pending&limit=1
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .browser_intent import PREFIX as BROWSER_PREFIX, USE_BROWSER

KEYRING_SERVICE = "Doxa Pacifica"
KEYRING_TOKEN = "jarvis-integration-token"
QUOTE_PATH = "/api/integrations/jarvis/quote-requests"
MIN_TOKEN_LENGTH = 32
TIMEOUT_SECONDS = 15

PRODUCTS = ("Auto", "Home", "Renters", "Life", "Commercial", "Home & Auto")

# "start a quote for Ana Ruiz, full coverage auto" / "new quote request for Ana Ruiz - renters" /
# "can you open a quote for Ana Ruiz for home and auto"
INTENT = re.compile(
    r"^\s*(?:(?:hey|ok|okay)\s+)?(?:doxa|jarvis)?[\s,]*(?:please\s+)?(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
    r"(?:start|create|open|make|begin|add|log|put in|set up|new)\s+(?:me\s+)?(?:a\s+|an\s+)?(?:new\s+)?"
    r"(?:pacifica\s+)?quote(?:\s+request)?\s+(?:for|on)\s+(?P<rest>.{2,600}?)\s*(?:,?\s*please)?[.!?]?\s*$",
    re.I | re.S)
SPLIT = re.compile(r"\s*(?:[,;:]|\s-\s|\s–\s|\s—\s)\s*|\s+(?:for|with|needs|wants|on)\s+", re.I)
BIND = re.compile(r"\b(?:bind|binds|binding|bound|issue (?:the |a )?polic(?:y|ies)|effectuate|"
                  r"(?:call|contact|email|submit to|send (?:it )?to)\s+(?:the\s+)?(?:carrier|mercury|progressive|geico|"
                  r"state farm|allstate|farmers|travelers|safeco))\b", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")
EMAIL = re.compile(r"[^\s@,;]+@[^\s@,;]+\.[A-Za-z]{2,}")
NAME_OK = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.\- ]{1,99}$")
PRODUCT_WORDS = [
    ("Home & Auto", re.compile(r"\b(?:home\s*(?:&|and|\+)\s*auto|auto\s*(?:&|and|\+)\s*home|bundle|bundled)\b", re.I)),
    ("Renters", re.compile(r"\brent(?:er|ers|al)?(?:'s)?\b", re.I)),
    ("Commercial", re.compile(r"\b(?:commercial|business|general liability|gl|workers'? comp|bop|fleet)\b", re.I)),
    ("Life", re.compile(r"\b(?:life|term life|whole life)\b", re.I)),
    ("Home", re.compile(r"\b(?:home|homeowners?|house|condo|ho-?3|dwelling)\b", re.I)),
    ("Auto", re.compile(r"\b(?:auto|car|cars|vehicle|truck|motorcycle|liability only|full coverage|sr-?22)\b", re.I)),
]


@dataclass
class QuoteDraft:
    customer_name: str
    coverage: str
    product: str = ""
    phone: str = ""
    email: str = ""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    refused: str = ""  # non-empty: why Doxa will not send this (e.g. it asks to bind coverage)

    def payload(self) -> dict:
        """Exactly the JSON body that is sent. The confirmation card shows this."""
        return {"customerName": self.customer_name, "product": self.product, "coverage": self.coverage,
                "phone": self.phone, "email": self.email, "source": "doxa", "requestId": self.request_id}

    def card_rows(self) -> list[tuple[str, str]]:
        return [("Customer", self.customer_name), ("Insurance", self.product or "(not set — choose in Pacifica)"),
                ("Coverage", self.coverage or "(none given)"), ("Phone", self.phone or "—"),
                ("Email", self.email or "—"), ("Source", "doxa"), ("Request ID", self.request_id)]


def quote_request_from_chat(text: str) -> QuoteDraft | None:
    """Return a draft if the message asks to start a quote request, else None. Pure, no I/O, no model."""
    value = (text or "").strip()
    if not value or len(value) > 800 or BROWSER_PREFIX.match(value) or USE_BROWSER.search(value):
        return None  # website jobs ("get a quote on geico.com") stay with the browser agent
    match = INTENT.match(value)
    if not match:
        return None
    rest = match.group("rest").strip()
    email = (EMAIL.search(rest).group(0).lower() if EMAIL.search(rest) else "")
    rest = EMAIL.sub(" ", rest)
    phone_match = PHONE.search(rest)
    phone = "".join(phone_match.groups()) if phone_match else ""
    rest = PHONE.sub(" ", rest)
    rest = re.sub(r"\b(?:phone|cell|number|email|e-mail)\s*(?:is|:)?\s*(?=[,;]|$)", " ", rest, flags=re.I)
    parts = [p.strip(" .") for p in SPLIT.split(rest, maxsplit=1)]
    name = re.sub(r"\s+", " ", parts[0]).strip(" .,'’")
    coverage = re.sub(r"\s+", " ", parts[1] if len(parts) > 1 else "").strip(" .,;")
    coverage = re.sub(r"[\s,;]+$", "", coverage)[:500]
    if not NAME_OK.match(name) or len(name.split()) > 6:
        return None
    product = next((label for label, words in PRODUCT_WORDS if words.search(coverage)), "")
    draft = QuoteDraft(customer_name=name[:100], coverage=coverage, product=product, phone=phone, email=email[:200])
    if BIND.search(value):
        draft.refused = ("I can start the quote request in Pacifica, but I never bind coverage or contact carriers — "
                         "binding is always your call, done by you. Ask again without that part and I'll prepare the request.")
    return draft


# --- token storage (Windows Credential Manager) --------------------------------------------------------

def token_get() -> str:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_TOKEN) or ""
    except Exception:
        return ""


def token_set(token: str) -> None:
    """Save (or with an empty value, remove) the token. Never written to any file."""
    import keyring
    token = token.strip()
    if token:
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"The Pacifica token must be at least {MIN_TOKEN_LENGTH} characters.")
        keyring.set_password(KEYRING_SERVICE, KEYRING_TOKEN, token)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_TOKEN)
        except Exception:
            pass


def clean_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parts = urllib.parse.urlsplit(value)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme not in ("https", "http") or (parts.scheme == "http" and not local) or not parts.hostname:
        raise ValueError("Use the https address of your Pacifica CRM, e.g. https://crm.example.com")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Use just the site address, with no login, query or # part.")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def is_configured(base_url: str, token_lookup: Callable[[], str] | None = None) -> bool:
    try:
        return bool(clean_base_url(base_url)) and len((token_lookup or token_get)()) >= MIN_TOKEN_LENGTH
    except ValueError:
        return False


# --- HTTP client ----------------------------------------------------------------------------------------

class PacificaError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _friendly(status: int, server_message: str) -> str:
    if status == 401:
        return "Pacifica rejected Doxa's token. Re-save it in Settings → Pacifica connection (it must match JARVIS_INTEGRATION_TOKEN in Vercel)."
    if status == 503:
        return "Pacifica says the Doxa integration isn't configured. Set JARVIS_INTEGRATION_TOKEN and JARVIS_WORKSPACE_ID in Vercel, then redeploy."
    if status in (404, 405):
        return "This Pacifica deployment can't create quote requests yet (the create endpoint isn't deployed)."
    if status == 413:
        return "That request is too large for Pacifica."
    if 400 <= status < 500 and server_message:
        return f"Pacifica didn't accept it: {server_message[:200]}"
    return f"Pacifica had a problem (HTTP {status}). Nothing was created on Doxa's side; try again in a moment."


class PacificaClient:
    def __init__(self, base_url: str, token_lookup: Callable[[], str] | None = None, opener: Callable | None = None):
        self.base_url = clean_base_url(base_url)
        self._token_lookup = token_lookup or token_get
        self._open = opener or urllib.request.urlopen

    @property
    def endpoint(self) -> str:
        return self.base_url + QUOTE_PATH

    def _call(self, method: str, url: str, body: dict | None = None) -> dict:
        token = self._token_lookup()
        if not self.base_url or len(token) < MIN_TOKEN_LENGTH:
            raise PacificaError("Pacifica isn't connected yet. Add it in Settings → Pacifica connection.")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "Doxa-Pacifica/1"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._open(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(200_000).decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            message = ""
            try:
                message = str(json.loads(exc.read(20_000).decode("utf-8", "replace")).get("error", ""))
            except Exception:
                pass
            raise PacificaError(_friendly(exc.code, message), exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise PacificaError(f"Couldn't reach Pacifica ({reason}). Check the address and your internet connection.") from None
        except ValueError:
            raise PacificaError("Pacifica sent an answer Doxa couldn't read.") from None

    def create_quote_request(self, draft: QuoteDraft) -> dict:
        if draft.refused:
            raise PacificaError(draft.refused)
        result = self._call("POST", self.endpoint, draft.payload())
        if not result.get("ok", True) or result.get("error"):
            raise PacificaError(str(result.get("error") or "Pacifica didn't confirm the request."))
        return result.get("request") or {}

    def check(self) -> int:
        """Read-only connection test. Returns how many pending requests came back (0 or 1)."""
        result = self._call("GET", self.endpoint + "?filter=pending&limit=1")
        return len(result.get("requests") or [])
