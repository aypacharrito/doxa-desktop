"""Click-to-talk dictation for the laptop chat box (the owner 2026-11-09: "a little click for voice to text … like how I do
it with you, and a type box"; "Doxa kind of responds randomly" came from the always-on wake word hearing the room).

Click the mic: Doxa records from the chosen microphone. Click again (or stop talking for a long while, or 2 minutes):
it transcribes (OpenAI's transcription when connected, the local Whisper model otherwise) and puts the words in the
type box. Nothing is sent until the owner presses Enter, so he can fix a word first.
"""
from __future__ import annotations

import io
import threading
import time
import wave

RATE = 16000
MAX_SECONDS = 120

_local_model = None


def to_wav(samples) -> bytes:
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


def transcribe_local(samples) -> str:
    global _local_model
    from faster_whisper import WhisperModel
    if _local_model is None:
        _local_model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = _local_model.transcribe(samples, language="en", beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


class Dictation:
    def __init__(self, device=None, cloud_voice=None, on_text=None, on_status=None, recorder=None, clock=time.monotonic):
        self.device = device or None
        self.cloud_voice = cloud_voice            # forgemind.cloud_voice.CloudVoice or None
        self.on_text = on_text or (lambda text: None)
        self.on_status = on_status or (lambda text: None)
        self.recorder = recorder                  # tests pass a fake; None = sounddevice
        self.clock = clock
        self.recording = False
        self.busy = False
        self._chunks = []
        self._stream = None
        self._started = 0.0

    def toggle(self):
        if self.busy:
            return
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self):
        import numpy as np
        self._chunks = []
        self._started = self.clock()

        def callback(indata, frames, time_info, status):
            self._chunks.append(np.array(indata[:, 0], dtype="float32"))
            if self.clock() - self._started > MAX_SECONDS:
                threading.Thread(target=self.stop, daemon=True).start()

        if self.recorder is not None:
            self._stream = self.recorder(callback)
        else:
            import sounddevice as sd
            self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", device=self.device,
                                          callback=callback)
            self._stream.start()
        self.recording = True
        self.on_status("Listening… click the mic again when you're done.")

    def stop(self):
        if not self.recording:
            return
        self.recording = False
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self.busy = True
        self.on_status("Getting your words…")
        threading.Thread(target=self._finish, daemon=True, name="doxa-dictation").start()

    def _finish(self):
        import numpy as np
        try:
            samples = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype="float32")
            if len(samples) < RATE * 0.4:
                self.on_status("Didn't catch anything. Click the mic and try again.")
                return
            peak = float(np.max(np.abs(samples))) or 1.0
            samples = samples * min(30.0, 0.9 / peak)          # soft voices come out clear
            text = ""
            if self.cloud_voice is not None and getattr(self.cloud_voice, "available", False):
                try:
                    from .cloud_voice import transcribe_file
                    text = transcribe_file(self.cloud_voice, to_wav(samples), "voice.wav", "audio/wav")
                except Exception:
                    text = ""
            if not text:
                text = transcribe_local(samples)
            if text.strip():
                self.on_text(text.strip())
                self.on_status("Got it. Fix anything you want, then press Enter to send.")
            else:
                self.on_status("Didn't catch any words. Try again a little closer to the mic.")
        except Exception as exc:
            self.on_status(f"Voice to text failed: {str(exc)[:120]}")
        finally:
            self.busy = False
