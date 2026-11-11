import os
import queue
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from forgemind import voice, whisper_listen
from forgemind.config import Settings
from forgemind.voice import LocalVoice, WakeRouter
from forgemind.whisper_listen import FRAME, Segmenter


def model_cached():
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return any(hub.glob("models--Systran--faster-whisper-base.en*"))


def synthesize(text, path):
    """Windows' own voice reads `text` into a wav file (test input only)."""
    script = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def pcm16k(path):
    import imageio_ffmpeg
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


class FakeStream:
    def __init__(self, audio):
        self.audio, self.pos = audio, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        if self.pos >= len(self.audio):
            time.sleep(0.02)
            return np.zeros((n, 1), np.float32), False
        chunk = self.audio[self.pos:self.pos + n]
        self.pos += n
        time.sleep(n / 16000 / 2)  # twice real time: fast, but like a microphone, not all at once
        return chunk.reshape(-1, 1), False


class WakeWordTests(unittest.TestCase):
    def test_whisper_style_punctuation_wakes(self):
        router = WakeRouter()
        for text in ["Doxa, what time is it?", "Hey, Doxa, open my calendar.", "Okay Doxa what's on today",
                     "doxa. stop", "Hey Doxa, start a quote for Ana Ruiz, full coverage auto."]:
            router.reset()
            result = router.accept(text, 0.9)
            self.assertIsNotNone(result, text)
            self.assertEqual(result[0], "stop" if text.endswith("stop") else "command", text)

    def test_other_speech_is_ignored(self):
        router = WakeRouter()
        for text in ["What time is it?", "I bought a dose of medicine today.", "Does of what time is it",
                     "Thanks for watching!"]:
            self.assertIsNone(router.accept(text, 0.95), text)


class SegmenterTests(unittest.TestCase):
    def run_frames(self, levels):
        seg, phrases = Segmenter(), []
        for level in levels:
            frame = np.full(FRAME, level, np.float32)
            phrase = seg.push(frame, level)
            if phrase is not None:
                phrases.append(len(phrase))
        return phrases

    def test_speech_between_silence_is_one_phrase(self):
        phrases = self.run_frames([0.002] * 40 + [0.1] * 40 + [0.002] * 30)
        self.assertEqual(len(phrases), 1)
        self.assertGreaterEqual(phrases[0], 40)

    def test_short_clicks_and_silence_are_ignored(self):
        self.assertEqual(self.run_frames([0.002] * 40 + [0.2] * 4 + [0.002] * 40), [])
        self.assertEqual(self.run_frames([0.002] * 200), [])

    def test_follows_a_noisy_room(self):
        # A fan switching on (0.02) may make one short phrase while the baseline adapts, but it must not
        # stay "speech" forever (no 15 s chunks); speech well above it is still its own phrase.
        fan_only = self.run_frames([0.02] * 400)
        self.assertLessEqual(len(fan_only), 1)
        self.assertTrue(all(n < 100 for n in fan_only), fan_only)
        phrases = self.run_frames([0.02] * 300 + [0.25] * 40 + [0.02] * 60)
        self.assertEqual(len(phrases), len(fan_only) + 1)
        self.assertGreaterEqual(phrases[-1], 40)


class LocalVoiceTests(unittest.TestCase):
    def test_falls_back_to_windows_recognizer_without_whisper(self):
        events = []
        with mock.patch.object(whisper_listen, "available", return_value=False), \
                mock.patch.object(voice.subprocess, "Popen") as popen:
            popen.return_value = SimpleNamespace(stdout=iter(()), poll=lambda: 0)
            LocalVoice(events.append).enable()
        self.assertIn("listen", popen.call_args.args[0])

    def test_whisper_listener_is_used_and_routes_commands(self):
        events, made = [], []

        class FakeListener:
            def __init__(self, on_text, on_error, on_ready, device=None):
                made.append(self)
                self.on_text, self.on_error, self.on_ready = on_text, on_error, on_ready

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        with mock.patch.object(whisper_listen, "available", return_value=True), \
                mock.patch.object(whisper_listen, "WhisperListener", FakeListener):
            v = LocalVoice(events.append)
            v.enable()
            made[0].on_ready()
            made[0].on_text("What time is it?", 0.95)       # no wake word: ignored
            made[0].on_text("Doxa, what time is it?", 0.95)
            v.disable()
            made[0].on_text("Doxa, open my calendar", 0.95)  # after the mic is off: ignored
        self.assertEqual([e for e in events if e[0] != "voice_state"], [("voice_command", "what time is it?")])
        self.assertIn(("voice_state", "Sleeping · say “Doxa”"), events)

    def test_listener_error_turns_the_mic_off_with_a_message(self):
        events, made = [], []

        class FakeListener:
            def __init__(self, on_text, on_error, on_ready, device=None):
                made.append(on_error)

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        with mock.patch.object(whisper_listen, "available", return_value=True), \
                mock.patch.object(whisper_listen, "WhisperListener", FakeListener):
            v = LocalVoice(events.append)
            v.enable()
            made[0]("No microphone found")
        self.assertFalse(v.enabled)
        self.assertIn(("voice_error", "No microphone found"), events)

    def test_mic_choice_is_remembered(self):
        from app import ForgeMindApp
        saved = []
        settings = Settings()
        settings.save = lambda: saved.append(settings.voice_enabled)
        fake = SimpleNamespace(voice=SimpleNamespace(enabled=False), settings_data=settings)
        fake.voice.enable = lambda: setattr(fake.voice, "enabled", True)
        fake.voice.disable = lambda: setattr(fake.voice, "enabled", False)
        ForgeMindApp.toggle_voice(fake)
        ForgeMindApp.toggle_voice(fake)
        self.assertEqual(saved, [True, False])


@unittest.skipUnless(os.name == "nt" and whisper_listen.available() and model_cached(),
                     "needs Windows, faster-whisper, sounddevice and the cached base.en model")
class EndToEndTests(unittest.TestCase):
    """Real Whisper on Windows-voice recordings, fed through a fake microphone."""

    def test_wake_word_commands_and_ignored_speech(self):
        with tempfile.TemporaryDirectory() as folder:
            clips = []
            for i, text in enumerate(["Doxa, what time is it", "what time is it",
                                      "I bought a dose of medicine today", "Hey Doxa, open my calendar"]):
                path = Path(folder) / f"{i}.wav"
                synthesize(text, path)
                clips.append(pcm16k(path))
        rng = np.random.default_rng(0)
        quiet = lambda n: (rng.standard_normal(n) * 0.002).astype(np.float32)
        audio = np.concatenate([np.concatenate([quiet(16000), clip * 0.6]) for clip in clips] + [quiet(32000)])
        heard, errors = queue.Queue(), []
        listener = whisper_listen.WhisperListener(on_text=lambda t, c: heard.put((t, c)), on_error=errors.append,
                                                  stream_factory=lambda: FakeStream(audio))
        results = []
        try:
            deadline = time.time() + 120
            while len(results) < 4 and time.time() < deadline:
                try:
                    results.append(heard.get(timeout=1))
                except queue.Empty:
                    pass
        finally:
            listener.terminate()
            listener.wait(5)
        self.assertEqual(errors, [])
        router = WakeRouter()
        decisions = [router.accept(text, confidence) for text, confidence in results]
        self.assertEqual([d[0] if d else None for d in decisions], ["command", None, None, "command"], results)
        self.assertIn("time", decisions[0][1].lower())
        self.assertIn("calendar", decisions[3][1].lower())


if __name__ == "__main__":
    unittest.main()
