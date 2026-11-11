"""Offline, opt-in speech. Unaddressed speech is never stored or sent online.

Listening uses local Whisper (`whisper_listen`) when it is installed, otherwise Windows' recognizer
through `speech_bridge.ps1`. Speaking always uses Windows' voice through the bridge.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from collections import deque

from . import whisper_listen

# How Whisper writes "Doxa" when it isn't sure: Doksa, Docsa, Dox-a, Docks a, Dock sa... All anchored to the start of
# the phrase, so "the docs are on the table" or "docs are ready" never wake Doxa.
WAKE = re.compile(r"^\W*(?:(?:hey|okay|ok|hello|yo)[\s,.!-]+)?"
                  r"(?:dox+-?a|doks+a|docs?a|dokza|doxah|doksah|daksa|toxa|docks?[\s-]a|dock[\s-]sa|doc[\s-]sa|jarvis)\b"
                  r"[\s,.:!?-]*", re.I)
# With "hey/okay" in front, Whisper's looser spellings of Doxa count too ("Hey docs", "Hey Dox", "Okay Dosa").
HEY_WAKE = re.compile(r"^\W*(?:hey|okay|ok)[\s,.!-]+(?:docs|dox|doks|dokes|doc|dock|dosa|doza|doxie|doxy|doxas|"
                      r"talks?a|dachsa)\b[\s,.:!?-]*", re.I)
SLEEPING = 'Sleeping · say “Doxa”'


def wake_match(text: str):
    return WAKE.match(text) or HEY_WAKE.match(text)


def strip_wake(text: str) -> str:
    """Remove leading wake words: "Hey Doxa, Doxa, what time is it?" -> "what time is it?"."""
    text = " ".join((text or "").split())
    match = wake_match(text)
    while match:
        text = text[match.end():].strip()
        match = WAKE.match(text)
    return text


def is_echo(heard: str, spoken: str) -> bool:
    """True when a phrase is Doxa's own last answer coming back through the microphone."""
    words = re.findall(r"[a-z']+", (heard or "").lower())
    said = set(re.findall(r"[a-z']+", (spoken or "").lower()))
    return len(words) >= 3 and sum(word in said for word in words) / len(words) >= 0.7


def play_chime():
    """Two short rising tones (Windows only; silent elsewhere)."""
    try:
        import winsound
        winsound.Beep(880, 70)
        winsound.Beep(1320, 90)
    except Exception:
        pass


STOP = {'stop', 'cancel', 'stop listening', 'go to sleep', 'never mind', 'nevermind'}
WAKE_WINDOW = 8               # seconds after a bare "Doxa" (or a follow-up) when no wake word is needed, like Hey Google
BARE_WAKE_CONFIDENCE = .65    # a lone "Doxa" must be heard clearly: Whisper sometimes invents it from noise
REPEATED_WAKE_CONFIDENCE = .8  # "Doxa, Doxa, …"


class WakeRouter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.until = 0.0

    def reset(self):
        self.until = 0.0

    def accept(self, text: str, confidence: float = 1.0):
        text = ' '.join(text.split()).strip()
        if not text or confidence < .55:
            return None
        match = wake_match(text)
        if match:
            command, wakes = text[match.end():].strip(), 1
            while True:  # "Doxa, Doxa, what time is it?" is one wake
                again = WAKE.match(command)
                if not again:
                    break
                command, wakes = command[again.end():].strip(), wakes + 1
            # Over noise Whisper plays back its priming sentence: "Doxa Doxa, what time is it?". People say the name
            # once; two in a row must be heard very clearly, three or more are never the owner.
            if wakes >= 3 or (wakes == 2 and confidence < REPEATED_WAKE_CONFIDENCE):
                return None
            if not command:
                if wakes > 1 or confidence < BARE_WAKE_CONFIDENCE:
                    return None
                self.until = self.clock() + WAKE_WINDOW
                return ('wake', '')
        elif self.clock() < self.until:
            command = text
        else:
            return None
        self.reset()  # One command per wake; unrelated follow-up audio is ignored.
        if command.lower().strip('.!? ') in STOP:
            return ('stop', '')
        return ('command', command)


def spoken_text(text: str, limit=1400) -> str:
    text = re.sub(r'```.*?```', ' Code is shown in the conversation. ', text, flags=re.S)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*#`_]+', '', text)
    text = ' '.join(text.split())
    if len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0] + '. The rest is in the conversation.'
    return text


def bridge_command(mode, *extra):
    shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    return [str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(Path(__file__).with_name('speech_bridge.ps1')), '-Mode', mode,
            '-OwnerPid', str(os.getpid()), *extra]


class SpeakerThread:
    """Looks like a speech process (poll/terminate/wait) while the cloud voice plays in a thread."""

    def __init__(self):
        self.stop_event = threading.Event()
        self.done = threading.Event()

    def poll(self):
        return 0 if self.done.is_set() else None

    def terminate(self):
        self.stop_event.set()

    kill = terminate

    def wait(self, timeout=None):
        self.done.wait(timeout)
        return 0


class LocalVoice:
    def __init__(self, callback):
        self.callback = callback
        self.router = WakeRouter()
        self.enabled = False
        self.speaking = False
        self.use_whisper = True
        self.device = None               # microphone name from Settings.voice_device (None = Windows default)
        self.chime = True                # short rising tone when "Doxa" is heard, like other assistants
        self.heard = deque(maxlen=12)    # (time, text, confidence, result) for Voice check; memory only
        self.followup = True             # keep the conversation going after a spoken answer (Voice check)
        self.tts = None                  # CloudVoice.speak(text, stop_event): natural voice; Windows voice if None/fails
        self.refine = None               # CloudVoice.transcribe(audio): accurate transcript of the command after "Doxa"
        self._last_spoken = ""
        self._listener = None
        self._speaker = None
        self._generation = 0
        self._lock = threading.RLock()

    def _emit(self, kind, value=''):
        self.callback(('voice_' + kind, value))

    @staticmethod
    def _terminate(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def enable(self):
        with self._lock:
            if self.enabled:
                return
            self.enabled = True
            self._followup_on_ready = False
            self.router.reset()
            self._start_listener()

    def _start_listener(self):
        self._generation += 1
        generation = self._generation
        self._emit('state', 'Opening microphone…')
        if self.use_whisper and whisper_listen.available():
            self._listener = whisper_listen.WhisperListener(
                on_text=lambda text, confidence: self._heard(generation, text, confidence),
                on_error=lambda message: self._listener_failed(generation, message),
                on_ready=lambda: self._listener_ready(generation), device=self.device)
            return
        try:
            process = subprocess.Popen(bridge_command('listen'), stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            self.enabled = False
            self._emit('error', str(exc))
            return
        self._listener = process
        threading.Thread(target=self._read, args=(process, generation), daemon=True).start()

    def _read(self, process, generation):
        failed = False
        for line in process.stdout:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            with self._lock:
                if generation != self._generation or not self.enabled:
                    continue
                if value['type'] == 'ready':
                    self._listener_ready(generation)
                elif value['type'] == 'recognized':
                    self._heard(generation, value.get('text', ''), float(value.get('confidence', 0)))
                elif value['type'] == 'error':
                    failed = True
                    self.enabled = False
                    self._emit('error', value['message'])
        with self._lock:
            if generation == self._generation and self.enabled and not failed:
                self.enabled = False
                self._emit('error', 'The microphone stopped. Check your audio device and turn it on again.')

    def _heard(self, generation, text, confidence):
        with self._lock:
            if generation != self._generation or not self.enabled:
                return
            if self.router.clock() < self.router.until and not wake_match(text) and is_echo(text, self._last_spoken):
                self.heard.append((time.strftime("%H:%M:%S"), text, round(float(confidence), 2), "echo"))
                return  # Doxa hearing its own answer, not the owner
            result = self.router.accept(text, confidence)
            self.heard.append((time.strftime("%H:%M:%S"), text, round(float(confidence), 2), result[0] if result else ""))
            if result:
                if self.chime and result[0] in ("wake", "command"):
                    threading.Thread(target=play_chime, daemon=True).start()
                audio = getattr(self._listener, "last_audio", None)
                if result[0] == "command" and self.refine is not None and audio is not None:
                    threading.Thread(target=self._refine, args=(generation, audio, result[1]), daemon=True).start()
                    return
                self._emit(*result)

    def _refine(self, generation, audio, fallback):
        """Re-transcribe the command with OpenAI (much more accurate than the local wake-word model)."""
        try:
            command = strip_wake(self.refine(audio))
        except Exception:
            command = ""
        with self._lock:
            if generation != self._generation or not self.enabled:
                return
            command = command or fallback
            if command.lower().strip('.!? ') in STOP:
                self._emit('stop', '')
            else:
                self._emit('command', command)

    def _listener_ready(self, generation):
        with self._lock:
            if generation == self._generation and self.enabled:
                followup = getattr(self, '_followup_on_ready', False)
                self._followup_on_ready = False
                # Off by default: after an answer, TV, other people or Doxa's own echo were taken as new commands.
                if followup and self.followup:
                    self.router.until = self.router.clock() + WAKE_WINDOW
                    self._emit('wake', '')
                else:
                    self._emit('state', SLEEPING)

    def _listener_failed(self, generation, message):
        with self._lock:
            if generation == self._generation and self.enabled:
                self.enabled = False
                self._emit('error', message)

    def interrupt(self):
        """Stop talking and forget a half-finished request, but keep listening for "Doxa" (Stop and Esc)."""
        with self._lock:
            self.router.reset()
            if not self.speaking:
                return
            self.speaking = False
            self._generation += 1
            self._terminate(self._speaker)
            self._speaker = None
            if self.enabled:
                self._start_listener()
            else:
                self._emit('state', 'Microphone off')

    def restart(self):
        """Re-open the microphone (after choosing a different one)."""
        with self._lock:
            if self.enabled:
                self._generation += 1
                self._terminate(self._listener)
                self._listener = None
                self._start_listener()

    def level(self) -> float:
        return float(getattr(self._listener, "level", 0.0) or 0.0)

    def detector(self) -> str:
        return getattr(self._listener, "detector_name", "") or ("Windows speech" if self._listener else "")

    def disable(self):
        with self._lock:
            self._followup_on_ready = False
            self.enabled = False
            self.speaking = False
            self._generation += 1
            self.router.reset()
            self._terminate(self._listener)
            self._terminate(self._speaker)
            self._listener = self._speaker = None
            self._emit('state', 'Microphone off')

    def _windows_speaker(self):
        return subprocess.Popen(bridge_command('speak'), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def speak(self, text: str):
        text = spoken_text(text)
        if not text:
            return
        with self._lock:
            self._generation += 1
            self._terminate(self._listener)  # Prevent Doxa hearing its own voice.
            self._terminate(self._speaker)
            self.speaking = True
            self._last_spoken = text
            generation = self._generation
            self._emit('state', 'Speaking · microphone paused')
            try:
                process = SpeakerThread() if self.tts is not None else self._windows_speaker()
                self._speaker = process
            except OSError as exc:
                self.speaking = False
                self._emit('error', str(exc))
                return

        def run():
            nonlocal process
            if isinstance(process, SpeakerThread):
                try:
                    self.tts(text, process.stop_event)  # natural cloud voice
                    process.done.set()
                    error = None
                except Exception:
                    process.done.set()
                    if process.stop_event.is_set():
                        error = None
                    else:  # offline, budget used up, bad key: say it with the Windows voice instead
                        with self._lock:
                            if generation != self._generation:
                                return
                            try:
                                process = self._speaker = self._windows_speaker()
                            except OSError as exc:
                                process = None
                                error = str(exc)
                if process is not None and not isinstance(process, SpeakerThread):
                    try:
                        output, _ = process.communicate(json.dumps({'text': text}) + '\n', timeout=180)
                        error = next((json.loads(x).get('message') for x in output.splitlines()
                                      if x.startswith('{') and json.loads(x).get('type') == 'error'), None)
                    except Exception:
                        self._terminate(process)
                        error = 'Speech playback did not finish. Turn the microphone on again.'
            else:
                try:
                    output, _ = process.communicate(json.dumps({'text': text}) + '\n', timeout=180)
                    error = next((json.loads(x).get('message') for x in output.splitlines()
                                  if x.startswith('{') and json.loads(x).get('type') == 'error'), None)
                except Exception:
                    self._terminate(process)
                    error = 'Speech playback did not finish. Turn the microphone on again.'
            with self._lock:
                if generation != self._generation:
                    return
                self.speaking = False
                if error:
                    self.enabled = False
                    self._emit('error', error)
                elif self.enabled:
                    self._followup_on_ready = True
                    self._start_listener()
                else:
                    self._emit('state', 'Microphone off')
        threading.Thread(target=run, daemon=True).start()
