"""Short-video links (Instagram reels, TikTok, YouTube Shorts) -> MP4 + local transcript + frames.

Paste a link in chat (desktop or phone) and Doxa downloads the video with yt-dlp, adds it to the Media
library, transcribes it locally with Whisper and samples frames. The transcript is posted in chat, so
follow-up questions ("what was the recipe?") have it in context.

Only public videos are fetched: Doxa never uses the owner's Instagram/TikTok login or browser cookies.
Videos are for the owner's own reference; nothing is re-uploaded or shared.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .config import app_data_dir

LINK = re.compile(
    r"https?://(?:www\.|m\.)?(?:"
    r"(?:instagram\.com|instagr\.am)/(?:[\w.]+/)?(?:reels?|p|tv)/[\w-]+"
    r"|(?:vm|vt)\.tiktok\.com/[\w-]+|tiktok\.com/@[\w.-]+/(?:video|photo)/\d+"
    r"|youtube\.com/shorts/[\w-]+"
    r")[^\s<>\"')\]]*",
    re.I)
MAX_LINKS = None  # no cap: the owner 2026-11-06 ("make that number unlimited"); handled one by one
# A video/audio file on this PC, quoted or not (also @"C:\..." as pasted from Claude or Explorer).
LOCAL_MEDIA = re.compile(r'@?"?([A-Za-z]:\\[^"\r\n<>|*?]*?\.(?:mp4|mov|m4v|webm|mkv|avi|m4a|mp3|wav))(?=["\s]|$)', re.I)
MAX_FILES = None  # no cap either
MAX_BYTES = 300 * 1024 * 1024
TRANSCRIBE_MODEL = "base.en"  # already used for voice; "small.en" would be a 480 MB download


def reel_links(text: str) -> list[str]:
    """Distinct short-video links in a message, in order (all of them)."""
    found: list[str] = []
    for match in LINK.finditer(text or ""):
        url = match.group(0).rstrip(".,!?;:")
        if url not in found:
            found.append(url)
    return found[:MAX_LINKS]


FOLLOW_UP = re.compile(r"\b(?:download|convert|mp4|transcri\w*|save|grab|get|open|watch|see|pull)\b", re.I)
BACK_REFERENCE = re.compile(r"\b(?:them|those|these|it|that|the (?:links?|reels?|videos?|posts?)|my (?:links?|reels?))\b",
                            re.I)
REFUSALS = re.compile(r"\b(?:don'?t|do not|never|stop|cancel)\b", re.I)  # "no, download them" still counts


def links_from_history(text: str, recent: list[dict] | None) -> list[str]:
    """A follow-up like "download them" or "convert those to mp4" (no link in it) uses the reel links from the
    owner's most recent message that had any. Looks back at most 8 messages."""
    value = (text or "").strip()
    if not value or len(value) > 300 or reel_links(value) or not FOLLOW_UP.search(value):
        return []
    if not (BACK_REFERENCE.search(value) or re.search(r"\b(?:mp4|transcri\w*)\b", value, re.I)):
        return []
    if REFUSALS.search(value):
        return []
    for item in reversed((recent or [])[-8:]):
        if item.get("role") == "user":
            links = reel_links(str(item.get("content", "")))
            if links:
                return links
    return []


def local_media(text: str) -> list[str]:
    """Video/audio files on this PC named in a message (existing files only, all of them)."""
    found: list[str] = []
    for match in LOCAL_MEDIA.finditer(text or ""):
        path = match.group(1).strip()
        if path not in found and Path(path).is_file():
            found.append(path)
    return found[:MAX_FILES]


def is_local(item: str) -> bool:
    return not item.lower().startswith(("http://", "https://"))


def question_about(text: str) -> str:
    """Whatever the owner asked besides the link(s)/file(s), or "" if the message is only those plus filler."""
    text = LOCAL_MEDIA.sub(" ", text or "")
    rest = LINK.sub(" ", text)
    rest = re.sub(r"\b(?:can you|could you|please|convert|transcribe|transcript|transcripted|get|all|download|"
                  r"this|these|those|that|reels?|videos?|files?|links?|to|into|an?|the|mp4|for me|watch|"
                  r"check out|look at|and|it|them)\b", " ", rest, flags=re.I)
    rest = re.sub(r"[\s,.:;!?-]+", " ", rest).strip()
    return " ".join(re.sub(r'["@]', " ", LINK.sub(" ", text)).split()) if len(rest.split()) >= 2 else ""


class ReelError(Exception):
    pass


def _friendly(message: str) -> str:
    low = message.lower()
    if "login" in low or "log in" in low or "cookies" in low or "private" in low:
        return ("That video needs a signed-in account to watch, and Doxa only fetches public videos. "
                "If it's public, try again in a minute (Instagram sometimes asks for a login when busy).")
    if "unsupported url" in low or "no video" in low:
        return "There's no video at that link (it may be a photo post or deleted)."
    if "max_filesize" in low or "larger than max" in low:
        return "That video is over 300 MB, so Doxa skipped it."
    if "http error 404" in low or "not found" in low:
        return "That link doesn't exist any more (404)."
    return "Couldn't download that video: " + message.splitlines()[0][:200]


def default_folder() -> Path:
    """Where reel MP4s are saved: Downloads\\Doxa reels, so the owner can find them (falls back to app data)."""
    downloads = Path.home() / "Downloads"
    return downloads / "Doxa reels" if downloads.is_dir() else app_data_dir() / "media" / "reels"


def download(url: str, folder: Path | None = None, ydl_factory=None) -> tuple[Path, dict]:
    """Save the video as MP4. Returns (path, info). No account, no cookies."""
    import imageio_ffmpeg
    folder = Path(folder or default_folder())
    folder.mkdir(parents=True, exist_ok=True)
    options = {
        "outtmpl": str(folder / "%(extractor)s-%(id)s.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
        "noplaylist": True,
        "max_filesize": MAX_BYTES,
        "socket_timeout": 20,
        "retries": 2,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if ydl_factory is None:
        import yt_dlp
        ydl_factory = yt_dlp.YoutubeDL
    try:
        with ydl_factory(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get("entries"):
                info = next(entry for entry in info["entries"] if entry)
            downloads = info.get("requested_downloads") or []
            path = Path(downloads[0]["filepath"]) if downloads else Path(ydl.prepare_filename(info))
    except ReelError:
        raise
    except Exception as exc:
        raise ReelError(_friendly(str(exc))) from None
    if not path.is_file():
        raise ReelError("The download finished but the video file is missing.")
    return path, info


def process(url: str, library, progress: Callable[[str], None] | None = None, downloader=download) -> dict:
    """Download (or take a file on this PC) -> media library -> transcript + frames. Returns what chat needs."""
    say = progress or (lambda _message: None)
    if is_local(url):
        downloader = lambda path: (Path(path), {"title": Path(path).stem})  # noqa: E731
    else:
        say("Downloading the video…")
    path, info = downloader(url)
    record = library.add(path)
    say("Transcribing it on this PC…")
    try:
        transcript_path = library.transcribe(record["id"], model_name=TRANSCRIBE_MODEL)
        lines = [line for line in Path(transcript_path).read_text(encoding="utf-8").splitlines()
                 if line.startswith("[")]
        transcript = " ".join(line.split("] ", 1)[-1] for line in lines).strip()
    except Exception as exc:
        transcript, transcript_path = "", None
        say(f"Transcription failed: {exc}")
    frames: list[str] = []
    try:
        frames = [str(p) for p in library.sample_video_frames(record["id"], maximum=8)]
    except Exception:
        pass
    caption = " ".join(str(info.get("description") or "").split())[:600]
    return {"url": url, "local": is_local(url), "path": str(path), "media_id": record["id"],
            "title": str(info.get("title") or "")[:120], "uploader": str(info.get("uploader") or info.get("channel") or ""),
            "duration": info.get("duration"), "caption": caption, "transcript": transcript,
            "transcript_path": str(transcript_path or ""), "frames": frames}


def chat_summary(result: dict) -> str:
    """What Doxa posts in chat for one processed video."""
    who = f" by {result['uploader']}" if result.get("uploader") else ""
    length = f", {round(result['duration'])} s" if result.get("duration") else ""
    lines = ([f"Video {Path(result['path']).name}{length}"] if result.get("local")
             else [f"Reel{who}{length} — saved as MP4: {result['path']}"])
    if result.get("caption"):
        lines.append(f"Caption: {result['caption']}")
    if result.get("transcript"):
        lines.append(f"Transcript: {result['transcript']}")
    else:
        lines.append("Transcript: (no speech found — it may be music only)")
    if result.get("frames"):
        lines.append(f"{len(result['frames'])} still frames saved in the Media library.")
    return "\n".join(lines)
