from __future__ import annotations

import hashlib
import base64
import json
import mimetypes
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from forgemind.config import app_data_dir


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv"}
VISION_MODEL_NAME = "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
VISION_PROJECTOR_NAME = "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
VISION_REVISION = "5037fcf163dd95d1e41d1974465f0898ed108ca2"
VISION_FILES = {
    VISION_MODEL_NAME: (1929901056, "d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12"),
    VISION_PROJECTOR_NAME: (844757728, "980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904"),
}
VISION_MODEL_URL = (
    f"https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/{VISION_REVISION}/"
    + VISION_MODEL_NAME
)
VISION_PROJECTOR_URL = (
    f"https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/{VISION_REVISION}/"
    + VISION_PROJECTOR_NAME
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _media_id(path: Path) -> str:
    stat = path.stat()
    value = f"{path.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


class MediaLibrary:
    """Persistent, read-only media records plus locally generated derivatives."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else app_data_dir() / "media"
        self.records_dir = self.root / "records"
        self.transcripts_dir = self.root / "transcripts"
        self.frames_dir = self.root / "frames"
        self.models_dir = self.root / "models"
        for directory in (self.records_dir, self.transcripts_dir, self.frames_dir, self.models_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def vision_model_path(self) -> Path:
        return self.models_dir / VISION_MODEL_NAME

    @property
    def vision_projector_path(self) -> Path:
        return self.models_dir / VISION_PROJECTOR_NAME

    @property
    def vision_ready(self) -> bool:
        return (
            self.vision_model_path.is_file()
            and self.vision_model_path.stat().st_size > 1_500_000_000
            and self.vision_projector_path.is_file()
            and self.vision_projector_path.stat().st_size > 700_000_000
        )

    def download_vision_models(self, progress: Callable[[str], None] | None = None) -> tuple[Path, Path]:
        downloads = (
            (VISION_MODEL_URL, self.vision_model_path, "vision language model", 1_500_000_000),
            (VISION_PROJECTOR_URL, self.vision_projector_path, "vision projector", 700_000_000),
        )
        for url, destination, label, minimum_size in downloads:
            expected_size, expected_hash = VISION_FILES[destination.name]
            def verified(path):
                if not path.is_file() or path.stat().st_size != expected_size:
                    return False
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                        digest.update(block)
                return digest.hexdigest() == expected_hash
            if destination.exists():
                if verified(destination):
                    continue
                raise ValueError(f"Existing {label} differs from the verified release. It was preserved.")
            temporary = destination.with_suffix(destination.suffix + ".download")
            if progress:
                progress(f"Downloading {label}…")

            def report(blocks: int, block_size: int, total: int, name: str = label) -> None:
                if progress and total > 0:
                    progress(f"Downloading {name}: {min(100, blocks * block_size * 100 / total):0.0f}%")

            try:
                urllib.request.urlretrieve(url, temporary, reporthook=report)
                if not verified(temporary):
                    raise ValueError(f"The {label} download did not pass checksum verification.")
                temporary.replace(destination)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        return self.vision_model_path, self.vision_projector_path

    @staticmethod
    def media_type(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            return "image"
        if suffix in AUDIO_SUFFIXES:
            return "audio"
        if suffix in VIDEO_SUFFIXES:
            return "video"
        raise ValueError(f"Unsupported media type: {suffix or '[no extension]'}")

    def add(self, path: Path) -> dict[str, Any]:
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Media file not found: {path}")
        media_id = _media_id(path)
        record_path = self.records_dir / f"{media_id}.json"
        if record_path.exists():
            return json.loads(record_path.read_text(encoding="utf-8"))
        record: dict[str, Any] = {
            "id": media_id,
            "source": str(path),
            "name": path.name,
            "type": self.media_type(path),
            "size_bytes": path.stat().st_size,
            "added_at": _now(),
            "read_only_source": True,
            "status": "added",
            "transcript": "",
            "frames": [],
            "ocr_text": "",
            "metadata": {},
        }
        self._enrich_metadata(record)
        self._save(record)
        return record

    def _enrich_metadata(self, record: dict[str, Any]) -> None:
        source = Path(record["source"])
        if record["type"] == "image":
            try:
                from PIL import Image

                with Image.open(source) as image:
                    record["metadata"].update(
                        {"width": image.width, "height": image.height, "format": image.format or "unknown"}
                    )
            except Exception as exc:
                record["metadata"]["inspection_note"] = f"Image metadata unavailable: {exc}"
        elif record["type"] in {"audio", "video"}:
            try:
                import av

                with av.open(str(source)) as container:
                    duration = float(container.duration / av.time_base) if container.duration else 0.0
                    record["metadata"].update(
                        {
                            "duration_seconds": round(duration, 3),
                            "audio_streams": len(container.streams.audio),
                            "video_streams": len(container.streams.video),
                        }
                    )
            except Exception as exc:
                record["metadata"]["inspection_note"] = f"Media metadata unavailable: {exc}"

    def _save(self, record: dict[str, Any]) -> None:
        destination = self.records_dir / f"{record['id']}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)

    def list_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.records_dir.glob("*.json"), reverse=True):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def get(self, media_id: str) -> dict[str, Any]:
        path = self.records_dir / f"{media_id}.json"
        if not path.exists():
            raise FileNotFoundError("Media record not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def transcribe(
        self,
        media_id: str,
        model_name: str = "small.en",
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        record = self.get(media_id)
        if record["type"] not in {"audio", "video"}:
            raise ValueError("Only audio and video recordings can be transcribed.")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "The local transcription engine is not installed. Run SETUP_WINDOWS.bat from this release."
            ) from exc
        if progress:
            progress(f"Loading local speech model {model_name} on CPU…")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        if progress:
            progress("Listening to the recording and creating timestamps…")
        options = dict(beam_size=5, vad_filter=True, condition_on_previous_text=True)
        try:
            segments, info = model.transcribe(record["source"], **options)
        except TypeError as exc:
            if "metadata_errors" not in str(exc):
                raise
            # Some installed PyAV versions cannot accept Whisper's metadata flag.
            # Decode locally with the bundled FFmpeg and keep audio off the network.
            import imageio_ffmpeg
            import numpy as np
            audio = subprocess.check_output([
                imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", record["source"],
                "-f", "f32le", "-ar", "16000", "-ac", "1", "pipe:1",
            ], timeout=300)
            segments, info = model.transcribe(np.frombuffer(audio, dtype=np.float32), **options)
        lines = [
            f"# Transcript: {record['name']}",
            "",
            f"Source: {record['source']}",
            f"Language: {getattr(info, 'language', 'unknown')}",
            "",
        ]
        count = 0
        for segment in segments:
            count += 1
            lines.append(f"[{segment.start:0.2f}–{segment.end:0.2f}] {segment.text.strip()}")
            if progress and count % 25 == 0:
                progress(f"Transcribed {segment.end / 60:0.1f} minutes…")
        destination = self.transcripts_dir / f"{media_id}.md"
        destination.write_text("\n".join(lines), encoding="utf-8")
        record.update(
            {
                "status": "transcribed",
                "transcript": str(destination),
                "transcribed_at": _now(),
                "transcription_model": model_name,
                "language": getattr(info, "language", "unknown"),
            }
        )
        self._save(record)
        return destination

    def sample_video_frames(self, media_id: str, maximum: int = 12) -> list[Path]:
        record = self.get(media_id)
        if record["type"] != "video":
            raise ValueError("Frame sampling requires a video recording.")
        try:
            import av
        except ImportError as exc:
            raise RuntimeError("Video frame support is not installed. Run SETUP_WINDOWS.bat.") from exc
        destination = self.frames_dir / media_id
        destination.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        with av.open(record["source"]) as container:
            if not container.streams.video:
                return []
            stream = container.streams.video[0]
            duration = float(container.duration / av.time_base) if container.duration else 0.0
            points = [0.0] if duration <= 0 else [duration * i / maximum for i in range(maximum)]
            for index, seconds in enumerate(points):
                container.seek(int(seconds * av.time_base), backward=True, any_frame=False)
                frame = next(container.decode(video=0), None)
                if frame is None:
                    continue
                path = destination / f"frame-{index + 1:03d}-{seconds:0.1f}s.jpg"
                frame.to_image().save(path, quality=88)
                created.append(path)
        record["frames"] = [str(path) for path in created]
        record["frames_sampled_at"] = _now()
        self._save(record)
        return created

    @staticmethod
    def _data_url(path: Path) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def analyze_visual(
        self,
        media_id: str,
        prompt: str = "Describe this image precisely, including visible text, interface state, errors, and useful details.",
        maximum_video_frames: int = 6,
        progress: Callable[[str], None] | None = None,
    ) -> str:
        if not self.vision_ready:
            raise RuntimeError("Download the local vision model from the Media Library first.")
        record = self.get(media_id)
        if record["type"] == "image":
            images = [Path(record["source"])]
        elif record["type"] == "video":
            images = [Path(item) for item in record.get("frames", [])]
            if not images:
                images = self.sample_video_frames(media_id, maximum=maximum_video_frames)
            images = images[:maximum_video_frames]
        else:
            raise ValueError("Vision analysis requires an image or video.")
        if not images:
            raise RuntimeError("No usable images or video frames were found.")

        from forgemind.runtime import prepare_windows_dlls

        prepare_windows_dlls()
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Qwen25VLChatHandler

        if progress:
            progress("Loading the local screenshot vision model onto the GPU…")
        handler = Qwen25VLChatHandler(clip_model_path=str(self.vision_projector_path), verbose=False)
        model = Llama(
            model_path=str(self.vision_model_path),
            chat_handler=handler,
            n_ctx=4096,
            n_gpu_layers=-1,
            flash_attn=True,
            verbose=False,
        )
        analyses: list[str] = []
        try:
            for index, image in enumerate(images, start=1):
                if progress:
                    progress(f"Looking at image {index} of {len(images)}…")
                response = model.create_chat_completion(
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": self._data_url(image)}},
                            ],
                        }
                    ],
                    max_tokens=900,
                    temperature=0.1,
                    stream=False,
                )
                content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
                analyses.append(f"## Image {index}: {image.name}\n\n{content.strip()}")
        finally:
            model.close()
        result = "\n\n".join(analyses)
        record.update({"vision_analysis": result, "vision_analyzed_at": _now(), "status": "vision-complete"})
        self._save(record)
        return result

    def ocr_image(self, media_id: str) -> str:
        record = self.get(media_id)
        if record["type"] != "image":
            raise ValueError("OCR requires an image record.")
        executable = shutil.which("tesseract")
        if not executable:
            raise RuntimeError(
                "Image OCR is ready, but Tesseract is not installed. Doxa saved the screenshot and metadata."
            )
        result = subprocess.run(
            [executable, record["source"], "stdout"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Tesseract could not read the image.")
        text = result.stdout.strip()
        record.update({"ocr_text": text, "status": "ocr-complete", "ocr_at": _now()})
        self._save(record)
        return text

    def knowledge_document(self, media_id: str) -> Path:
        record = self.get(media_id)
        path = self.root / f"knowledge-{media_id}.md"
        sections = [
            f"# Media: {record['name']}",
            "",
            f"Type: {record['type']}",
            f"Read-only source: {record['source']}",
            f"Metadata: {json.dumps(record.get('metadata', {}), ensure_ascii=False)}",
        ]
        transcript = record.get("transcript")
        if transcript and Path(transcript).is_file():
            sections.extend(["", Path(transcript).read_text(encoding="utf-8", errors="replace")])
        if record.get("ocr_text"):
            sections.extend(["", "## Visible text", "", record["ocr_text"]])
        if record.get("vision_analysis"):
            sections.extend(["", "## Local vision analysis", "", record["vision_analysis"]])
        if record.get("frames"):
            sections.extend(["", "## Sampled frames", *[f"- {item}" for item in record["frames"]]])
        path.write_text("\n".join(sections), encoding="utf-8")
        return path
