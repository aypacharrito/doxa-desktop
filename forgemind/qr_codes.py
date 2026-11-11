"""Both QR codes, every time (the owner 2026-11-09: "Doxa needs to send me TWO QR codes every time: (1) the QR code to
download the app, and (2) the QR code that connects/pairs Doxa to my phone").

`make_both(access, base_url)` writes two PNGs (app download + pairing) into `Documents\\Doxa Notes\\QR codes\\` and
returns both links, plus a `doxa://connect` link that pairs the app in one tap when opened on the phone itself (a phone
can't scan its own screen). The pairing code reuses the current phone key (kept DPAPI-encrypted next to phone.json,
see `PhoneAccess.current_key`), so showing it again doesn't disconnect the phone; a new key is made only when there is
no saved one (`rotate_if_missing`) or when asked.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

# the newest Doxa phone app (EAS build of 2026-11-09: photos, files, voice, chats); phone-app.json can override it
APP_URL = "https://expo.dev/artifacts/eas/oIeH4-jausrePqDnEnUrkh0WS_oyzj1Qwzzi1ihnh9c.apk"
OUT = Path.home() / "Documents" / "Doxa Notes" / "QR codes"
ASK = re.compile(r"\b(?:qr(?:\s*codes?)?|pairing (?:code|link|qr)|pair (?:my )?(?:phone|app)|connect (?:my )?phone|"
                 r"phone link|app (?:download|link)|download (?:the |doxa )?app)\b", re.I)


def qr_request(text: str) -> bool:
    return bool(ASK.search(text or "")) and len(text or "") < 300


def app_url(data_dir: Path | None = None) -> str:
    try:
        data = json.loads(Path(data_dir or Path.home() / "AppData" / "Local" / "ForgeMind").joinpath("phone-app.json")
                          .read_text("utf-8"))
        url = str(data.get("apk", ""))
        if url.startswith("https://"):
            return url
    except (OSError, ValueError, AttributeError):
        pass
    return APP_URL


def save_qr(text: str, path: Path) -> Path:
    import segno
    path.parent.mkdir(parents=True, exist_ok=True)
    segno.make(text, error="m").save(str(path), kind="png", scale=10, border=3, dark="#06080C", light="#FFFFFF")
    return path


def make_both(access, base_url: str, out: Path | None = None, rotate_if_missing: bool = True,
              apk: str | None = None) -> dict:
    """Both codes. Raises ValueError when the phone address isn't known yet (phone access off)."""
    from .phone_bridge import phone_link
    base = (base_url or "").rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("Phone access isn't connected yet, so there's no pairing address. Turn it on in Doxa → Phone.")
    key, rotated = access.current_key(), False
    if not key:
        if not rotate_if_missing:
            raise ValueError("The pairing key isn't saved on this PC yet. Make one in Doxa → Phone (Create new link).")
        key, rotated = access.new_key(), True
    out = Path(out or OUT)
    download = apk or app_url()
    pair = phone_link(base, key)
    deep = f"doxa://connect?u={quote(base, safe='')}&k={key}"
    return {"app_url": download, "app_png": str(save_qr(download, out / "1 - download the Doxa app.png")),
            "pair_link": pair, "pair_png": str(save_qr(pair, out / "2 - pair Doxa with your phone.png")),
            "pair_deeplink": deep, "rotated": rotated}


def phone_reply(both: dict) -> str:
    return ("Your two QR codes (also saved on the PC in Documents\\Doxa Notes\\QR codes):\n"
            f"1. Download the Doxa app: {both['app_url']}\n"
            f"2. Pair Doxa with your phone: {both['pair_deeplink']}\n"
            "On this phone, just tap the links (a phone can't scan its own screen). "
            + ("A new pairing code was made, so other phones need to scan it again." if both["rotated"]
               else "Your current pairing stays connected."))
