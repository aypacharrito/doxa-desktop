"""Local wake-word listening with Whisper (faster-whisper, CPU, int8). Audio never leaves the PC.

Windows' built-in recognizer doesn't know the word "Doxa": it heard "Doxa, what time is it" as
"Does of what time is it", so Doxa ignored the owner. Whisper, primed with example phrases, gets the
wake word right (24/24 test recordings, two voices, two speeds, ~0.6 s per phrase on this PC).

`WhisperListener` acts like the old bridge subprocess (poll / terminate / wait / kill), so LocalVoice's
pause-while-speaking and Stop handling are unchanged. Audio is split into phrases by loudness relative
to the room's background level; each phrase is transcribed on a worker thread and passed to `on_text`.
Nothing is written to disk.
"""
from __future__ import annotations

import math
import queue
import threading
from collections import deque

RATE = 16_000
FRAME = 512                      # 32 ms (Silero VAD's frame size)
PRE_ROLL_FRAMES = 10             # keep 300 ms before speech starts
START_FRAMES = 3                 # 90 ms above threshold starts a phrase
END_SILENCE_FRAMES = 23          # ~700 ms of quiet ends it
MIN_PHRASE_FRAMES = 8            # ignore sounds with under 240 ms of voiced audio
MAX_PHRASE_FRAMES = 500          # cut at 15 s
MODEL_NAME = "base.en"
PROMPT = "Doxa, what time is it? Hey Doxa, open my calendar."
HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "thank you for watching", "bye"}

_model = None
_model_lock = threading.Lock()


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
        return True
    except Exception:
        return False


def load_model():
    """Load once per process (~1-2 s). The model is downloaded to the Hugging Face cache on first use."""
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=4)
        return _model


def normalize(audio):
    """Bring a phrase to a steady loudness (peak 0.9, at most 40x gain): Whisper mishears quiet audio."""
    import numpy as np
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    return audio if peak <= 0 else (audio * min(40.0, 0.9 / peak)).astype(np.float32)


class VoiceDetector:
    """Silero VAD (shipped inside faster-whisper, ~0.15 ms per frame) with automatic gain.

    Same approach as RealtimeSTT / Home Assistant voice: a neural model decides "is this a voice" instead of a
    loudness threshold, so soft speech is caught and steady fan or music noise is not. The automatic gain lifts
    quiet input (a mic across the room) before the model sees it."""

    START, KEEP = 0.5, 0.35   # hysteresis: begin at 0.5, stay in speech while >= 0.35

    def __init__(self, model=None):
        import numpy as np
        from faster_whisper.vad import get_vad_model
        self.np = np
        self.model = model or get_vad_model()
        self.prev = np.zeros(FRAME, np.float32)
        self.peak = 0.02          # recent loud level; falls slowly, rises fast
        self.in_speech = False

    def gain(self) -> float:
        return max(1.0, min(30.0, 0.25 / max(self.peak, 1e-4)))

    def __call__(self, frame) -> bool:
        np = self.np
        top = float(np.max(np.abs(frame))) if frame.size else 0.0
        self.peak = max(top, self.peak * 0.995) if top > self.peak else self.peak * 0.995 + top * 0.005
        boosted = np.clip(frame * self.gain(), -1, 1).astype(np.float32)
        out = np.asarray(self.model(np.concatenate([self.prev, boosted]))).reshape(-1)
        self.prev = boosted
        probability = float(out[-1])
        self.in_speech = probability >= (self.KEEP if self.in_speech else self.START)
        return self.in_speech


def vad_available() -> bool:
    try:
        from faster_whisper.vad import get_vad_model  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(audio, model=None) -> tuple[str, float]:
    """Return (text, confidence 0..1) for one phrase of 16 kHz mono float32 audio."""
    model = model or load_model()
    audio = normalize(audio)
    segments, _ = model.transcribe(audio, language="en", beam_size=1, condition_on_previous_text=False,
                                   without_timestamps=True, initial_prompt=PROMPT, hotwords="Doxa")
    segments = list(segments)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not segments:
        return "", 0.0
    logprob = sum(s.avg_logprob for s in segments) / len(segments)
    no_speech = max(s.no_speech_prob for s in segments)
    confidence = math.exp(logprob) * (1.0 - no_speech if no_speech > 0.6 else 1.0)
    if text.lower().strip(" .!?,") in HALLUCINATIONS:
        return "", 0.0  # Whisper's usual output for noise
    return text, round(confidence, 3)


class Segmenter:
    """Splits a stream of 30 ms frames into phrases using an adaptive loudness threshold.

    The background level falls quickly and rises slowly (about 6 s), so a steady fan or hum becomes
    the new baseline instead of an endless "phrase", while a few seconds of speech barely move it.
    """

    def __init__(self):
        self.floor = 0.004
        self.loud = 0
        self.quiet = 0
        self.voiced = 0
        self.phrase: list | None = None
        self.pre = deque(maxlen=PRE_ROLL_FRAMES)

    def threshold(self) -> float:
        return max(self.floor * 3.0, 0.008)

    def _track(self, rms: float):
        rate = 0.1 if rms < self.floor else 0.005
        self.floor += rate * (rms - self.floor)

    def push(self, frame, rms: float, voiced: bool | None = None):
        """Feed one frame; return a finished phrase (list of frames) or None. `voiced` comes from the voice
        detector when available; otherwise loudness against the background level decides."""
        is_loud = voiced if voiced is not None else rms >= self.threshold()
        self._track(rms)
        if self.phrase is None:
            self.loud = self.loud + 1 if is_loud else 0
            self.pre.append(frame)
            if self.loud >= START_FRAMES:
                self.phrase, self.quiet, self.voiced = list(self.pre), 0, self.loud
                self.pre.clear()
            return None
        self.phrase.append(frame)
        if is_loud:
            self.quiet, self.voiced = 0, self.voiced + 1
        else:
            self.quiet += 1
        if self.quiet >= END_SILENCE_FRAMES or len(self.phrase) >= MAX_PHRASE_FRAMES:
            phrase, voiced, self.phrase, self.loud = self.phrase, self.voiced, None, 0
            return phrase if voiced >= MIN_PHRASE_FRAMES else None
        return None


class WhisperListener:
    """Microphone -> phrases -> Whisper -> on_text(text, confidence). on_error(message) stops it."""

    def __init__(self, on_text, on_error, on_ready=None, stream_factory=None, model=None, device=None,
                 use_vad=True):
        self.on_text, self.on_error, self.on_ready = on_text, on_error, on_ready
        self._stream_factory = stream_factory
        self._model = model
        self.device = device           # sounddevice input name or index; None = Windows default
        self.use_vad = use_vad
        self.level = 0.0               # live input level (RMS) for the Voice check meter
        self.detector_name = ""
        self._stop = threading.Event()
        self._phrases: queue.Queue = queue.Queue(maxsize=3)
        self._threads = [threading.Thread(target=self._capture, daemon=True, name="doxa-mic"),
                         threading.Thread(target=self._recognize, daemon=True, name="doxa-whisper")]
        for thread in self._threads:
            thread.start()

    # --- subprocess-like interface used by LocalVoice._terminate -------------------------------------
    def poll(self):
        return 0 if self._stop.is_set() else None

    def terminate(self):
        self._stop.set()

    kill = terminate

    def wait(self, timeout=None):
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout)
        return 0

    # --- workers --------------------------------------------------------------------------------------
    def _open_stream(self):
        if self._stream_factory:
            return self._stream_factory()
        import sounddevice
        return sounddevice.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME,
                                       device=resolve_device(self.device))

    def _capture(self):
        import numpy as np
        try:
            model = self._model or load_model()
            self._model = model
            stream = self._open_stream()
        except Exception as exc:
            self._fail(f"Couldn't start local speech recognition: {exc}")
            return
        segmenter = Segmenter()
        detector = None
        if self.use_vad and vad_available():
            try:
                detector = VoiceDetector()
            except Exception:
                detector = None
        self.detector_name = "Silero voice detection" if detector else "loudness"
        try:
            with stream:
                if self.on_ready:
                    self.on_ready()
                while not self._stop.is_set():
                    frame, _overflow = stream.read(FRAME)
                    frame = np.asarray(frame, dtype=np.float32).reshape(-1)
                    if not frame.size:
                        continue
                    rms = float(np.sqrt(np.mean(frame * frame)))
                    self.level = rms
                    phrase = segmenter.push(frame, rms, detector(frame) if detector else None)
                    if phrase is not None:
                        try:
                            self._phrases.put_nowait(np.concatenate(phrase))
                        except queue.Full:
                            pass  # recognizer is behind; drop rather than build latency
        except Exception as exc:
            if not self._stop.is_set():
                self._fail(f"The microphone stopped ({exc}). Check your audio device and turn it on again.")
        finally:
            self._phrases.put(None)

    def _recognize(self):
        while True:
            audio = self._phrases.get()
            if audio is None or self._stop.is_set():
                return
            self.last_audio = audio  # LocalVoice can re-transcribe the command more accurately in the cloud
            try:
                text, confidence = transcribe(audio, self._model)
            except Exception as exc:
                self._fail(f"Speech recognition failed: {exc}")
                return
            if text and not self._stop.is_set():
                self.on_text(text, confidence)

    def _fail(self, message: str):
        if not self._stop.is_set():
            self._stop.set()
            self.on_error(message)


def input_devices() -> list[str]:
    """Microphones Windows offers (MME names, as the Sound control panel shows them)."""
    import sounddevice
    names = []
    for device in sounddevice.query_devices():
        api = sounddevice.query_hostapis(device["hostapi"])["name"]
        if device["max_input_channels"] > 0 and api == "MME" and "Sound Mapper" not in device["name"]:
            names.append(device["name"])
    return names


def resolve_device(device):
    """A saved microphone name -> sounddevice index (None = Windows default; unknown names fall back to it)."""
    if device in (None, ""):
        return None
    if isinstance(device, int):
        return device
    import sounddevice
    for index, info in enumerate(sounddevice.query_devices()):
        if info["max_input_channels"] > 0 and info["name"] == device:
            return index
    return None
