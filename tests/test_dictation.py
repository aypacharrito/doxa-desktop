"""Click-to-talk in the laptop chat box (1.35): words land in the type box, nothing is sent; always-on listening off."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from forgemind import dictation
from forgemind.config import Settings
from forgemind.warehouses import KEYS, WarehouseBots


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.stopped = False

    def stop(self):
        self.stopped = True

    def close(self):
        pass


class DictationTests(unittest.TestCase):
    def test_click_talk_click_puts_the_words_in_the_box(self):
        texts, statuses, done = [], [], threading.Event()
        streams = []

        class Voice:
            available = True

        d = dictation.Dictation(cloud_voice=Voice(), on_text=texts.append,
                                on_status=lambda s: (statuses.append(s), done.set() if s.startswith("Got it") else None),
                                recorder=lambda cb: streams.append(FakeStream(cb)) or streams[-1])
        d.toggle()
        self.assertTrue(d.recording)
        tone = (np.sin(np.arange(16000) / 5) * 0.05).astype("float32").reshape(-1, 1)
        streams[0].callback(tone, len(tone), None, None)
        with mock.patch("forgemind.cloud_voice.transcribe_file", return_value="quote this customer on Mercury") as stt:
            d.toggle()
            self.assertTrue(done.wait(5))
        self.assertTrue(streams[0].stopped)
        self.assertEqual(texts, ["quote this customer on Mercury"])
        name, mime = stt.call_args.args[2:4]
        self.assertEqual((name, mime), ("voice.wav", "audio/wav"))
        self.assertTrue(stt.call_args.args[1].startswith(b"RIFF"))
        self.assertIn("Listening", statuses[0])

    def test_too_short_does_nothing(self):
        statuses, done = [], threading.Event()
        streams = []
        d = dictation.Dictation(on_status=lambda s: (statuses.append(s), done.set() if "Didn't" in s else None),
                                recorder=lambda cb: streams.append(FakeStream(cb)) or streams[-1])
        d.toggle()
        d.toggle()
        self.assertTrue(done.wait(5))
        self.assertIn("Didn't catch anything", statuses[-1])

    def test_always_on_listening_is_off_by_default(self):
        self.assertFalse(Settings().voice_enabled)


class PacificaRenameTests(unittest.TestCase):
    def test_the_insurance_bot_keeps_its_history_as_pacifica_and_reverse_has_a_bot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "w.json"
            path.write_text(json.dumps({"bots": {"insurance": {"runs": 7, "findings": [{"title": "CA rates", "detail": "",
                                                                                          "source": "", "at": 1}]}}}), "utf-8")
            bots = WarehouseBots(path, lambda: {}, log_root=Path(folder) / "logs")
            self.assertNotIn("insurance", bots.data["bots"])
            self.assertEqual(bots.view("pacifica")["runs"], 7)
            self.assertIn("reverse", KEYS)
            self.assertEqual(bots.view("reverse")["name"], "Cipher")
