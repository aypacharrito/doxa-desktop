"""Island art for Doxa HQ: the Higgsfield renders the owner approved (2026-11-10), one per island.

Files live in Documents\\Doxa Team\\characters\\islands: `originals\\<key>.png` (or a `<key>.png/.jpg` the owner drops in the
islands folder itself, which wins). HQ gets web-sized JPEGs made once per file version and cached in `islands\\.cache`:
"thumb" (900 px wide, for the world map) and "full" (2560 px, for an open island).
"""
from __future__ import annotations

import io
from pathlib import Path

KEYS = ("prime", "stores", "trading", "arbitrage", "pacifica", "marketing", "stenos", "websites", "reverse", "lab",
        "code", "knowledge")
SIZES = {"thumb": (900, 82), "full": (2560, 86)}
MAX_SOURCE = 40_000_000


def folder() -> Path:
    return Path.home() / "Documents" / "Doxa Team" / "characters" / "islands"


def source(key: str, root: Path | None = None) -> Path | None:
    key = (key or "").lower()
    if key not in KEYS:
        return None
    base = root or folder()
    for candidate in (base / f"{key}.png", base / f"{key}.jpg", base / f"{key}.jpeg", base / f"{key}.webp",
                      base / "originals" / f"{key}.png", base / "originals" / f"{key}.jpg"):
        if candidate.is_file() and candidate.stat().st_size <= MAX_SOURCE:
            return candidate
    return None


def versions(root: Path | None = None) -> dict:
    """{island: file time} for every island that has art (HQ reloads a picture when its time changes)."""
    out = {}
    for key in KEYS:
        path = source(key, root)
        if path is not None:
            out[key] = int(path.stat().st_mtime)
    return out


def image(key: str, size: str = "thumb", root: Path | None = None) -> bytes | None:
    """JPEG bytes for HQ, made once per source version and cached."""
    path = source(key, root)
    if path is None or size not in SIZES:
        return None
    width, quality = SIZES[size]
    cache = (root or folder()) / ".cache" / f"{key}-{size}-{int(path.stat().st_mtime)}.jpg"
    if cache.is_file():
        return cache.read_bytes()
    from PIL import Image
    with Image.open(path) as picture:
        picture = picture.convert("RGB")
        if picture.width > width:
            picture = picture.resize((width, round(picture.height * width / picture.width)), Image.LANCZOS)
        buffer = io.BytesIO()
        picture.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
    data = buffer.getvalue()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        for old in cache.parent.glob(f"{key}-{size}-*.jpg"):
            old.unlink(missing_ok=True)
        cache.write_bytes(data)
    except OSError:
        pass  # serving still works without the cache
    return data
