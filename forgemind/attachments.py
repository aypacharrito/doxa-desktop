"""Photos and documents sent from the owner's phone (the owner 2026-11-09: "the app doesn't have the ability to give images
and documents and all that stuff").

The phone uploads a file (`POST /api/upload`), Doxa saves it in `Documents\\Doxa Inbox\\<date>\\` and the chat message
carries `[Attached file: <path>]`. Claude in chat opens it with the `view_file` tool: photos as real images (it can see
them), PDFs as text (scanned ones as the PDF itself), Word documents and text files as text. Nothing is sent anywhere
else; the file stays on the PC.
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

INBOX = Path.home() / "Documents" / "Doxa Inbox"
MAX_BYTES = 25_000_000          # per file
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
TEXT_TYPES = {".txt", ".md", ".csv", ".json", ".log", ".html", ".htm", ".xml", ".tsv", ".py", ".js", ".ts"}
MAX_SIDE = 1568                 # Claude's best image size
TAG = re.compile(r"\[Attached file: ([^\]\n]+)\]")


def clean_name(name: str) -> str:
    name = Path(str(name or "")).name.strip()
    name = re.sub(r"[^\w .()\-]+", "_", name).strip(" .")[:120]
    return name or "file"


def save_upload(name: str, data_b64: str, inbox: Path | None = None, now: datetime | None = None) -> dict:
    try:
        data = base64.b64decode(data_b64 or "", validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("That file didn't arrive in one piece. Try again.") from None
    if not data:
        raise ValueError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise ValueError(f"That file is over {MAX_BYTES // 1_000_000} MB. Send a smaller one.")
    now = now or datetime.now()
    folder = Path(inbox or INBOX) / f"{now:%Y-%m-%d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now:%H%M%S} {clean_name(name)}"
    n = 2
    while path.exists():
        path = folder / f"{now:%H%M%S}-{n} {clean_name(name)}"
        n += 1
    path.write_bytes(data)
    kind = "image" if path.suffix.lower() in IMAGE_TYPES else "document"
    return {"path": str(path), "name": path.name, "size": len(data), "kind": kind, "tag": f"[Attached file: {path}]"}


def save_file(source: str, inbox: Path | None = None, now: datetime | None = None) -> dict:
    """The laptop's paperclip: copy a file into the Doxa Inbox (the original stays where it was)."""
    import shutil
    src = Path(source)
    if not src.is_file():
        raise ValueError(f"No file at {src}.")
    now = now or datetime.now()
    folder = Path(inbox or INBOX) / f"{now:%Y-%m-%d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now:%H%M%S} {clean_name(src.name)}"
    n = 2
    while path.exists():
        path = folder / f"{now:%H%M%S}-{n} {clean_name(src.name)}"
        n += 1
    shutil.copy2(src, path)
    kind = "image" if path.suffix.lower() in IMAGE_TYPES else "document"
    return {"path": str(path), "name": path.name, "size": path.stat().st_size, "kind": kind, "tag": f"[Attached file: {path}]"}


def attached_paths(text: str) -> list[str]:
    return TAG.findall(text or "")


def _image_block(path: Path) -> dict:
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(out.getvalue()).decode("ascii")}}


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def view_blocks(path_text: str):
    """What Claude sees for a file: a list of content blocks (image/document + a note) or plain text."""
    path = Path(str(path_text or "").strip().strip('"'))
    if not path.is_file():
        raise ValueError(f"No file at {path}.")
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES or suffix in (".bmp", ".tif", ".tiff"):
        return [_image_block(path), {"type": "text", "text": f"The image {path.name} ({path.stat().st_size:,} bytes)."}]
    if suffix in (".heic", ".heif"):
        raise ValueError("HEIC photos can't be opened here. In the phone app, send it again from the photo picker "
                         "(it converts to JPEG).")
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:40]).strip()
        if len(text) >= 200 or path.stat().st_size > 10_000_000:
            return f"PDF {path.name}, {len(reader.pages)} page(s):\n\n{text[:60000] or '(no text layer)'}"
        data = base64.b64encode(path.read_bytes()).decode("ascii")  # scanned: let Claude read the pages itself
        return [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
                {"type": "text", "text": f"The PDF {path.name} ({len(reader.pages)} page(s), scanned)."}]
    if suffix == ".docx":
        return f"Word document {path.name}:\n\n{_docx_text(path)[:60000]}"
    if suffix in TEXT_TYPES or path.stat().st_size < 200_000:
        return path.read_text("utf-8", errors="replace")[:60000]
    raise ValueError(f"{path.name} is a {suffix or 'binary'} file Doxa can't read directly. Use run_command to open "
                     "or convert it.")
