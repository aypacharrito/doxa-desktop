from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from forgemind.config import app_data_dir
from forgemind.media import MediaLibrary


def timestamp(value: str) -> float:
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError("Use seconds, MM:SS, or HH:MM:SS.")
    total = 0.0
    for part in parts:
        number = float(part)
        if not math.isfinite(number) or number < 0:
            raise ValueError("Timestamps must be finite and non-negative.")
        total = total * 60 + number
    return total


def transcript_segments(text: str) -> list[tuple[float, float, str]]:
    return [(float(a), float(b), words.strip()) for a, b, words in
            re.findall(r"^\[(\d+(?:\.\d+)?)[–-](\d+(?:\.\d+)?)\]\s*(.+)$", text, re.MULTILINE)]


def _srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    seconds_int, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{seconds_int:02},{millis:03}"


def captions(text: str, start: float, end: float) -> str:
    cues = []
    for a, b, words in transcript_segments(text):
        if b <= start or a >= end:
            continue
        left, right = max(0, a - start), min(end - start, b - start)
        if right <= left:
            continue
        cues.append(f"{len(cues) + 1}\n{_srt_time(left)} --> {_srt_time(right)}\n{words}\n")
    return "\n".join(cues)


class ClipStudio:
    def __init__(self, library: MediaLibrary, root: Path | None = None) -> None:
        self.library = library
        self.root = Path(root) if root else app_data_dir() / "clips"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def jobs(self) -> list[dict]:
        result = []
        for path in self.root.glob("*/job.json"):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def save(self, job: dict) -> None:
        with self._lock:
            path = self.root / job["id"] / "job.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)

    def transition(self, identifier: str, expected: str, status: str, **fields) -> dict:
        with self._lock:
            if not re.fullmatch(r"[0-9a-f]{32}", identifier):
                raise ValueError("Invalid clip job ID.")
            path = self.root / identifier / "job.json"
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["status"] != expected:
                raise ValueError(f"Clip is now {job['status']}; refresh the export list.")
            job.update(status=status, **fields)
            self.save(job)
            return job

    def plan(self, media_id: str, start: float, end: float, title: str,
             layout: str = "fit", burn_captions: bool = True) -> dict:
        record = self.library.get(media_id)
        if record["type"] != "video":
            raise ValueError("Select an OBS or other video recording.")
        if not all(math.isfinite(x) for x in (start, end)) or start < 0 or end <= start:
            raise ValueError("The end must be after the start.")
        if end - start > 180:
            raise ValueError("A YouTube Short can be up to 180 seconds. Choose a shorter section.")
        duration = record.get("metadata", {}).get("duration_seconds", 0)
        if duration and end > duration + 0.1:
            raise ValueError("The selected clip extends beyond the recording.")
        if layout not in {"fit", "crop"}:
            raise ValueError("Choose fit or crop layout.")
        if not title.strip() or len(title.strip()) > 100:
            raise ValueError("Use a title between 1 and 100 characters.")
        identifier = uuid.uuid4().hex
        folder = self.root / identifier
        folder.mkdir()
        job = {"id": identifier, "media_id": media_id, "source": record["source"],
               "title": title.strip(), "start": start, "end": end, "layout": layout,
               "burn_captions": burn_captions, "created_at": datetime.now(timezone.utc).isoformat(),
               "status": "planned", "output": str(folder / "clip.mp4")}
        self.save(job)
        return job

    def suggest(self, media_id: str, generate_json: Callable, progress: Callable | None = None) -> list[dict]:
        record = self.library.get(media_id)
        transcript = Path(record.get("transcript") or "missing-transcript")
        if not transcript.is_file():
            raise ValueError("Analyze the recording in Media library first to create a transcript.")
        segments = transcript_segments(transcript.read_text(encoding="utf-8"))
        if not segments:
            raise ValueError("The recording has no transcribed speech to select clips from.")
        chunks, current = [], ""
        for a, b, text in segments:
            line = f"[{a:.2f}–{b:.2f}] {text}\n"
            if len(current) + len(line) > 10000 and current:
                chunks.append(current)
                current = ""
            current += line
        if current:
            chunks.append(current)
        suggestions = []
        for index, chunk in enumerate(chunks):
            if progress:
                progress(f"Finding clip moments in transcript section {index + 1}/{len(chunks)}…")
            response = generate_json(
                "Select self-contained video highlights using only the supplied timestamped transcript. "
                "Return JSON: {\"clips\":[{\"start\":0,\"end\":30,\"title\":\"...\",\"reason\":\"...\"}]}. "
                "Use exact seconds from the transcript. Choose up to 3 moments, each 15–60 seconds. "
                "Avoid incomplete sentences, personal information, and unsupported promises of virality.",
                chunk, max_tokens=900,
            )
            boundaries = transcript_segments(chunk)
            lo, hi = boundaries[0][0], boundaries[-1][1]
            for item in response.get("clips", []):
                try:
                    start, end = float(item["start"]), float(item["end"])
                    title = str(item["title"]).strip()[:100]
                    if (not all(math.isfinite(x) for x in (start, end)) or not title
                            or start < lo or end > hi or not 15 <= end - start <= 60):
                        continue
                    if any(start < other["end"] and end > other["start"] for other in suggestions):
                        continue
                    suggestions.append({"start": start, "end": end, "title": title,
                                        "reason": str(item.get("reason", ""))})
                except (ValueError, TypeError, KeyError):
                    continue
        path = self.root / f"suggestions-{media_id}.json"
        path.write_text(json.dumps(suggestions, indent=2), encoding="utf-8")
        return suggestions

    def render(self, job: dict, progress: Callable | None = None) -> Path:
        import av
        import imageio_ffmpeg

        destination = Path(job["output"])
        source = Path(job["source"])
        if destination.resolve() == source.resolve():
            raise ValueError("Clip output must differ from the recording.")
        if destination.exists():
            if job["status"] in {"rendered", "uploaded"}:
                return destination
            raise ValueError("Output already exists; create a new clip to preserve it.")
        folder = destination.parent
        record = self.library.get(job["media_id"])
        transcript = Path(record.get("transcript") or "missing-transcript")
        srt = captions(transcript.read_text(encoding="utf-8"), job["start"], job["end"]) if transcript.is_file() else ""
        (folder / "captions.srt").write_text(srt, encoding="utf-8")
        dimensions = "720:1280"
        if job["layout"] == "crop":
            filters = f"scale={dimensions}:force_original_aspect_ratio=increase,crop={dimensions},setsar=1"
        else:
            filters = f"scale={dimensions}:force_original_aspect_ratio=decrease,pad={dimensions}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        if job["burn_captions"] and srt:
            filters += ",subtitles=captions.srt:force_style='FontSize=20,Outline=2,MarginV=60'"
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        base = [executable, "-hide_banner", "-nostdin", "-y", "-ss", str(job["start"]),
                "-i", str(source), "-t", str(job["end"] - job["start"]),
                "-map", "0:v:0", "-map", "0:a:0?", "-vf", filters, "-r", "30",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
        job.update(status="rendering", error="")
        self.save(job)
        try:
            for encoder in ("h264_nvenc", "libx264"):
                if progress:
                    progress(f"Exporting vertical clip with {'NVIDIA GPU' if encoder == 'h264_nvenc' else 'CPU fallback'}…")
                command = base + ["-c:v", encoder, "-preset", "fast", "rendering.mp4"]
                result = subprocess.run(command, cwd=folder, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", shell=False,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                (folder / "render.log").write_text(result.stderr, encoding="utf-8")
                if result.returncode == 0:
                    break
            if result.returncode != 0:
                raise RuntimeError("Video export failed: " + result.stderr[-1800:])
            temporary = folder / "rendering.mp4"
            with av.open(str(temporary)) as container:
                stream = container.streams.video[0]
                actual = float(container.duration / av.time_base) if container.duration else 0
                if (stream.width != 720 or stream.height != 1280 or actual <= 0
                        or abs(actual - (job["end"] - job["start"])) > 0.25):
                    raise RuntimeError("The exported clip did not pass the video check.")
            temporary.replace(destination)
            job.update(status="rendered", encoder=encoder, duration_seconds=actual,
                       subtitles=str(folder / "captions.srt"), captions_burned=bool(job["burn_captions"] and srt))
            self.save(job)
            return destination
        except Exception as exc:
            job.update(status="failed", error=str(exc))
            self.save(job)
            raise
