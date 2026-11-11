"""1.12.6 voice: Silero voice detection, gain, wake variants, always-on behavior, Voice check."""
import os
import queue
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
from forgemind.voice_ui import level_fraction


class WakeVariantTests(unittest.TestCase):
    def test_whisper_spellings_of_doxa_wake(self):
        for text in ["Doxa, what time is it?", "Doksa, open my calendar", "Docsa what time is it", "Dox-a, hi there",
                     "Docks a, read my messages", "Dock sa, what's next", "Yo Doxa, play music", "Hey, Doxa."]:
            router = WakeRouter()
            self.assertIsNotNone(router.accept(text, 0.9), text)

    def test_look_alikes_do_not_wake(self):
        for text in ["the docs are on the table", "Docs are ready", "Doctor said rest", "Dachshund pictures",
                     "Doxxing is bad", "Do you know the time", "toxic people", "I said doxa earlier"]:
            self.assertIsNone(WakeRouter().accept(text, 0.95), text)


class HelperTests(unittest.TestCase):
    def test_normalize_lifts_quiet_audio_but_caps_gain(self):
        quiet = np.full(1600, 0.01, np.float32)
        self.assertAlmostEqual(float(np.max(whisper_listen.normalize(quiet))), 0.4, places=3)  # 40x cap
        loud = np.full(1600, 0.5, np.float32)
        self.assertAlmostEqual(float(np.max(whisper_listen.normalize(loud))), 0.9, places=3)
        self.assertEqual(len(whisper_listen.normalize(np.zeros(0, np.float32))), 0)

    def test_meter_scale(self):
        self.assertEqual(level_fraction(0.0), 0.0)
        self.assertLess(level_fraction(0.001), level_fraction(0.01))
        self.assertEqual(level_fraction(1.0), 1.0)

    def test_unknown_mic_falls_back_to_windows_default(self):
        self.assertIsNone(whisper_listen.resolve_device(""))
        self.assertIsNone(whisper_listen.resolve_device("No Such Microphone 123"))
        self.assertEqual(whisper_listen.resolve_device(3), 3)

    def test_not_always_listening_by_default(self):  # 1.35: it answered the room; the chat mic is click-to-talk
        self.assertFalse(Settings().voice_enabled)
        self.assertEqual(Settings().voice_device, "")


class FakeListener:
    made = []

    def __init__(self, on_text, on_error, on_ready, device=None):
        self.on_text, self.on_error, self.on_ready, self.device = on_text, on_error, on_ready, device
        self.stopped = False
        FakeListener.made.append(self)

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0


class LocalVoiceTests(unittest.TestCase):
    def setUp(self):
        FakeListener.made = []
        self.events = []
        self.patches = [mock.patch.object(whisper_listen, "available", return_value=True),
                        mock.patch.object(whisper_listen, "WhisperListener", FakeListener),
                        mock.patch.object(voice, "play_chime")]
        for p in self.patches:
            self.chime = p.start() if p.attribute == "play_chime" else p.start()
        self.chime = voice.play_chime

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_mic_choice_is_passed_to_the_listener(self):
        v = LocalVoice(self.events.append)
        v.device = "Analogue 1 + 2 (2- Focusrite US"
        v.enable()
        self.assertEqual(FakeListener.made[0].device, "Analogue 1 + 2 (2- Focusrite US")
        v.restart()
        self.assertTrue(FakeListener.made[0].stopped)
        self.assertEqual(len(FakeListener.made), 2)

    def test_wake_plays_the_chime_and_is_remembered(self):
        v = LocalVoice(self.events.append)
        v.enable()
        FakeListener.made[0].on_ready()
        self.assertIn(("voice_state", "Sleeping · say “Doxa”"), self.events)
        FakeListener.made[0].on_text("I bought a dose of medicine", 0.9)
        FakeListener.made[0].on_text("Doxa, what time is it?", 0.9)
        time.sleep(0.05)
        self.assertEqual(self.chime.call_count, 1)
        self.assertEqual([h[3] for h in v.heard], ["", "command"])
        self.assertIn(("voice_command", "what time is it?"), self.events)

    def test_stop_interrupts_speech_but_keeps_listening(self):
        v = LocalVoice(self.events.append)
        v.enable()
        v.speaking, v._speaker = True, SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda timeout=None: 0)
        v.interrupt()
        self.assertTrue(v.enabled)
        self.assertFalse(v.speaking)
        self.assertEqual(len(FakeListener.made), 2)  # listening again after the speech was cut off

    def test_app_stop_button_keeps_the_mic_on(self):
        from app import ForgeMindApp
        calls = []
        fake = SimpleNamespace(_cancel_answer=SimpleNamespace(set=lambda: None), _voice_turn=True,
                               voice=SimpleNamespace(interrupt=lambda: calls.append("interrupt"),
                                                     disable=lambda: calls.append("disable")))
        ForgeMindApp.stop_jarvis(fake)
        self.assertEqual(calls, ["interrupt"])


class FalseWakeTests(unittest.TestCase):
    """the owner, 2026-11-05: Doxa answered "Doxa Doxa Doxa" and talk it wasn't meant to hear."""

    def test_repeated_wake_words_are_whisper_noise(self):
        router = WakeRouter()
        for text in ("Doxa Doxa Doxa", "Doxa Doxa Doxa Doxa Doxa Doxa", "Doxa, Doxa.", "Doxa Doxa Doxa, what time is it?"):
            self.assertIsNone(router.accept(text, 0.9), text)
            self.assertEqual(router.until, 0.0)  # no listening window opened either
        self.assertIsNone(router.accept("Doxa Doxa, what time is it?", 0.6))  # Whisper's prompt played back

    def test_real_requests_still_work(self):
        router = WakeRouter()
        self.assertEqual(router.accept("Doxa, what time is it?", 0.7), ("command", "what time is it?"))
        self.assertEqual(router.accept("Doxa, Doxa, open my calendar", 0.9), ("command", "open my calendar"))
        self.assertEqual(router.accept("Hey Doxa", 0.8), ("wake", ""))
        self.assertEqual(router.accept("find winning products", 0.8), ("command", "find winning products"))

    def test_unclear_lone_wake_is_ignored_and_window_is_short(self):
        now = [100.0]
        router = WakeRouter(lambda: now[0])
        self.assertIsNone(router.accept("Doxa", 0.6))
        self.assertIsNone(router.accept("what do you want for dinner", 0.9))
        self.assertEqual(router.accept("Doxa", 0.9), ("wake", ""))
        now[0] += voice.WAKE_WINDOW + 0.5
        self.assertIsNone(router.accept("what do you want for dinner", 0.9))


class FollowupTests(LocalVoiceTests):
    """the owner wants to keep talking after Doxa answers (conversation), without echoes or TV noise slipping in."""

    def speak_and_finish(self, v):
        v._followup_on_ready = True  # what speak() sets when an answer has been read out
        FakeListener.made[-1].on_ready()

    def test_conversation_continues_by_default(self):
        v = LocalVoice(self.events.append)
        self.assertTrue(v.followup)
        v.enable()
        self.speak_and_finish(v)
        self.assertIn(("voice_wake", ""), self.events)
        FakeListener.made[-1].on_text("and tomorrow?", 0.9)
        self.assertIn(("voice_command", "and tomorrow?"), self.events)

    def test_owner_can_turn_it_off(self):
        v = LocalVoice(self.events.append)
        v.followup = False
        v.enable()
        self.speak_and_finish(v)
        self.assertNotIn(("voice_wake", ""), self.events)
        FakeListener.made[-1].on_text("so anyway he told me to call back", 0.9)
        self.assertFalse([e for e in self.events if e[0] == "voice_command"])

    def test_own_echo_is_ignored(self):
        v = LocalVoice(self.events.append)
        v.enable()
        v._last_spoken = "The pill comb sells for about twenty four dollars and costs seven."
        self.speak_and_finish(v)
        FakeListener.made[-1].on_text("comb sells for about twenty four dollars", 0.9)
        self.assertFalse([e for e in self.events if e[0] == "voice_command"])
        self.assertEqual(v.heard[-1][3], "echo")
        FakeListener.made[-1].on_text("what about the ice scraper", 0.9)
        self.assertIn(("voice_command", "what about the ice scraper"), self.events)

    def test_settings_default_on(self):
        self.assertTrue(Settings().voice_conversation)
        self.assertTrue(Settings().cloud_voice)


class HeyDoxaTests(unittest.TestCase):
    def test_looser_spellings_after_hey(self):
        router = WakeRouter()
        for text, expected in [("Hey docs, what time is it?", ("command", "what time is it?")),
                               ("Hey Dox", ("wake", "")), ("Okay Dosa, open my calendar", ("command", "open my calendar")),
                               ("Hey, Doxa.", ("wake", ""))]:
            self.assertEqual(router.accept(text, 0.9), expected, text)
            router.reset()
        for text in ("the docs are ready", "docs are on the table", "Hey, how are you?", "hey dog come here"):
            self.assertIsNone(router.accept(text, 0.9), text)

    def test_strip_wake(self):
        self.assertEqual(voice.strip_wake("Hey Doxa, Doxa, what time is it?"), "what time is it?")
        self.assertEqual(voice.strip_wake("what time is it"), "what time is it")


class CloudHearingTests(LocalVoiceTests):
    def test_command_is_retranscribed_in_the_cloud(self):
        v = LocalVoice(self.events.append)
        v.refine = lambda audio: "Hey Doxa, find winning products for pets."
        v.enable()
        FakeListener.made[0].last_audio = np.zeros(16000, dtype=np.float32)
        FakeListener.made[0].on_text("Doxa, find whining products for pets", 0.8)
        deadline = time.time() + 2
        while time.time() < deadline and not [e for e in self.events if e[0] == "voice_command"]:
            time.sleep(0.01)
        self.assertIn(("voice_command", "find winning products for pets."), self.events)

    def test_cloud_failure_keeps_the_local_transcript(self):
        v = LocalVoice(self.events.append)

        def broken(audio):
            raise ValueError("offline")
        v.refine = broken
        v.enable()
        FakeListener.made[0].last_audio = np.zeros(16000, dtype=np.float32)
        FakeListener.made[0].on_text("Doxa, what time is it?", 0.8)
        deadline = time.time() + 2
        while time.time() < deadline and not [e for e in self.events if e[0] == "voice_command"]:
            time.sleep(0.01)
        self.assertIn(("voice_command", "what time is it?"), self.events)


def model_cached():
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return any(hub.glob("models--Systran--faster-whisper-base.en*"))


@unittest.skipUnless(os.name == "nt" and whisper_listen.available() and whisper_listen.vad_available() and model_cached(),
                     "needs Windows speech, faster-whisper, Silero VAD and the cached base.en model")
class QuietSpeechTests(unittest.TestCase):
    """The failure the owner reported: soft speech was never even noticed by the loudness-based listener."""

    def run_listener(self, audio, use_vad):
        from tests.test_whisper_voice import FakeStream
        heard = queue.Queue()
        listener = whisper_listen.WhisperListener(on_text=lambda t, c: heard.put((t, c)), on_error=lambda m: heard.put((m, 0)),
                                                  stream_factory=lambda: FakeStream(audio), use_vad=use_vad)
        results, deadline = [], time.time() + len(audio) / 16000 + 30
        while time.time() < deadline:
            try:
                results.append(heard.get(timeout=1))
            except queue.Empty:
                if results:
                    break
        listener.terminate()
        listener.wait(5)
        return results

    def test_quiet_command_is_caught_only_with_voice_detection(self):
        from tests.test_whisper_voice import pcm16k, synthesize
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "quiet.wav"
            synthesize("Doxa, what time is it", path)
            speech = pcm16k(path) * 0.04  # roughly someone talking from across the room
        rng = np.random.default_rng(3)
        room = lambda n: (rng.standard_normal(n) * 0.0006).astype(np.float32)
        audio = np.concatenate([room(16000), speech + room(len(speech)), room(16000 * 3)])
        with_vad = self.run_listener(audio, True)
        router = WakeRouter()
        self.assertTrue(any((router.accept(t, c) or ("",))[0] == "command" for t, c in with_vad), with_vad)
        self.assertEqual(self.run_listener(audio, False), [])  # what 1.12.5 did: nothing


if __name__ == "__main__":
    unittest.main()
