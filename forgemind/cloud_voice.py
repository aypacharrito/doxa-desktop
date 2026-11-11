"""Doxa's voice and clearer hearing through OpenAI (the owner, 2026-11-05: "I hate the voice… maybe a Latina woman").

- Speaking: `gpt-4o-mini-tts`, voice "coral", steered by `INSTRUCTIONS` (a warm Latina woman's voice). Audio streams as
  raw 24 kHz PCM and plays while it downloads, so Doxa starts talking in about a second.
- Hearing: the always-on wake word stays local (free, private). Only the command after "Doxa" is sent to
  `gpt-4o-mini-transcribe` for a much more accurate transcript (the owner: "the way you hear me is way better").
- Both use the OpenAI key Doxa already has and count against OpenAI's monthly budget. If OpenAI isn't connected,
  is offline or the budget is used up, Doxa falls back to the Windows voice and the local transcript.
"""
from __future__ import annotations

import io
import threading
import wave

import numpy as np
import requests

from .windows_credentials import windows_key

TTS_MODEL = "gpt-4o-mini-tts"
STT_MODEL = "gpt-4o-mini-transcribe"
VOICE = "coral"
SAMPLE_RATE = 24000  # OpenAI "pcm" output: 24 kHz, 16-bit, mono
INSTRUCTIONS = (
    "Voice: a warm, friendly young Latina woman from Los Angeles, with a light, natural Latina accent. "
    "Tone: relaxed, confident and upbeat, like a smart friend helping out, not a robot or a news reader. "
    "Pace: natural and a little quick, with short pauses at commas. "
    "If the text is in Spanish, speak natural Mexican-American Spanish.")
# Prices (OpenAI, checked 2026-11): TTS ≈ $0.015 per spoken minute; transcribe ≈ $0.003 per audio minute.
TTS_USD_PER_CHAR = 0.015 / 900      # ~900 characters per spoken minute
STT_USD_PER_SECOND = 0.003 / 60


class CloudVoice:
    def __init__(self, cloud, transport=requests.post, player=None):
        self.cloud = cloud  # CloudBrain: its key file and its budget
        self.transport = transport
        self.player = player or play_pcm_stream
        self.enabled = True

    @property
    def available(self) -> bool:
        return self.enabled and bool(getattr(self.cloud, "loaded", False))

    def _key(self) -> str:
        try:
            return windows_key((self.cloud.root / "openai-key.dpapi").read_bytes(), False).decode("utf-8")
        except Exception:
            raise ValueError("Windows could not unlock the OpenAI connection.") from None

    # --- speaking -------------------------------------------------------------------------------------
    def speak(self, text: str, stop_event: threading.Event) -> None:
        """Say `text` out loud; returns when finished or stopped. Raises ValueError so the caller can fall back."""
        if not self.available:
            raise ValueError("OpenAI voice isn't connected.")
        cost = len(text) * TTS_USD_PER_CHAR + 0.0005
        identifier = self.cloud.budget.reserve(max(1, int(cost * 100) + 1))
        state = "interrupted"
        try:
            response = self.transport(
                "https://api.openai.com/v1/audio/speech", headers={"Authorization": "Bearer " + self._key()},
                json={"model": TTS_MODEL, "voice": VOICE, "input": text[:4000], "instructions": INSTRUCTIONS,
                      "response_format": "pcm"}, stream=True, timeout=(5, 60), allow_redirects=False)
            if not response.ok:
                state = "failed"
                raise ValueError(f"OpenAI voice failed (HTTP {response.status_code}).")
            self.player(response.iter_content(chunk_size=4800), stop_event)
            state = "stopped" if stop_event.is_set() else "completed"
        except requests.RequestException:
            state = "uncertain"
            raise ValueError("Couldn't reach OpenAI for the voice.") from None
        finally:
            self.cloud.budget.settle(identifier, state, cost)

    # --- hearing --------------------------------------------------------------------------------------
    def transcribe(self, audio) -> str:
        """Accurate transcript of one phrase (16 kHz mono float32). Raises ValueError on any failure."""
        if not self.available:
            raise ValueError("OpenAI isn't connected.")
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        seconds = len(audio) / 16000
        if seconds < 0.2 or seconds > 60:
            raise ValueError("Phrase length out of range.")
        cost = seconds * STT_USD_PER_SECOND + 0.0002
        identifier = self.cloud.budget.reserve(1)
        state = "interrupted"
        try:
            response = self.transport(
                "https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": "Bearer " + self._key()},
                data={"model": STT_MODEL, "prompt": "Doxa, Hey Doxa. Pacifica, Alibaba, dropshipping, TikTok.",
                      "response_format": "json"},
                files={"file": ("phrase.wav", wav_bytes(audio), "audio/wav")}, timeout=(5, 20), allow_redirects=False)
            if not response.ok:
                state = "failed"
                raise ValueError(f"OpenAI transcription failed (HTTP {response.status_code}).")
            state = "completed"
            return " ".join(str(response.json().get("text", "")).split())
        except requests.RequestException:
            state = "uncertain"
            raise ValueError("Couldn't reach OpenAI to transcribe.") from None
        finally:
            self.cloud.budget.settle(identifier, state, cost)


def transcribe_file(voice: "CloudVoice", data: bytes, name: str = "voice.m4a", mime: str = "audio/mp4") -> str:
    """Transcribe a recording sent from the phone (any format OpenAI accepts). Raises ValueError on failure."""
    if not voice.available:
        raise ValueError("Voice needs OpenAI connected on your PC (Settings → AI brains).")
    if not 200 <= len(data) <= 8_000_000:
        raise ValueError("That recording is empty or too long.")
    seconds = len(data) / 16000  # ~128 kbps AAC; only used for the budget estimate
    cost = seconds * STT_USD_PER_SECOND + 0.0002
    identifier = voice.cloud.budget.reserve(max(1, int(cost * 100) + 1))
    state = "interrupted"
    try:
        response = voice.transport(
            "https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": "Bearer " + voice._key()},
            data={"model": STT_MODEL, "prompt": "Doxa, Hey Doxa. Pacifica, Alibaba, dropshipping, TikTok, Codex, Claude.",
                  "response_format": "json"},
            files={"file": (name, data, mime)}, timeout=(5, 45), allow_redirects=False)
        if not response.ok:
            state = "failed"
            raise ValueError(f"OpenAI transcription failed (HTTP {response.status_code}).")
        state = "completed"
        return " ".join(str(response.json().get("text", "")).split())
    except requests.RequestException:
        state = "uncertain"
        raise ValueError("Couldn't reach OpenAI to transcribe.") from None
    finally:
        voice.cloud.budget.settle(identifier, state, cost)


def synthesize(voice: "CloudVoice", text: str) -> bytes:
    """Doxa's voice as an MP3 (for the phone to play). Raises ValueError on failure."""
    if not voice.available:
        raise ValueError("Voice needs OpenAI connected on your PC.")
    text = (text or "").strip()[:3000]
    if not text:
        raise ValueError("Nothing to say.")
    cost = len(text) * TTS_USD_PER_CHAR + 0.0005
    identifier = voice.cloud.budget.reserve(max(1, int(cost * 100) + 1))
    state = "interrupted"
    try:
        response = voice.transport(
            "https://api.openai.com/v1/audio/speech", headers={"Authorization": "Bearer " + voice._key()},
            json={"model": TTS_MODEL, "voice": VOICE, "input": text, "instructions": INSTRUCTIONS,
                  "response_format": "mp3"}, timeout=(5, 60), allow_redirects=False)
        if not response.ok:
            state = "failed"
            raise ValueError(f"OpenAI voice failed (HTTP {response.status_code}).")
        state = "completed"
        return response.content
    except requests.RequestException:
        state = "uncertain"
        raise ValueError("Couldn't reach OpenAI for the voice.") from None
    finally:
        voice.cloud.budget.settle(identifier, state, cost)


def wav_bytes(audio, rate=16000) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return out.getvalue()


def play_pcm_stream(chunks, stop_event: threading.Event) -> None:
    """Play 24 kHz 16-bit mono PCM chunks as they arrive (sounddevice). Stops promptly when stop_event is set."""
    import sounddevice as sd
    leftover = b""
    with sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=2400) as stream:
        for chunk in chunks:
            if stop_event.is_set():
                stream.abort()
                return
            data = leftover + chunk
            usable = len(data) - len(data) % 2
            leftover = data[usable:]
            if usable:
                stream.write(data[:usable])
        if not stop_event.is_set():
            stream.write(b"\x00\x00" * (SAMPLE_RATE // 10))  # 100 ms tail so the last word isn't clipped
