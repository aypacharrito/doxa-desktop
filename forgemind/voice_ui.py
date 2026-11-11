"""Voice check (Tools → Voice check): which microphone hears you, and what Doxa heard.

Every microphone gets a live level bar; talk and watch which one moves, then press "Use this mic". The list
below shows the last phrases Doxa transcribed (kept in memory only) and whether they woke it.
"""
from __future__ import annotations

import math
import tkinter as tk

from . import jarvis_ui as ui
from . import whisper_listen


def level_fraction(rms: float) -> float:
    """RMS 0.0003 (silence) .. 0.3 (shouting) mapped to 0..1 on a log scale, like a recording meter."""
    if rms <= 0.0003:
        return 0.0
    return max(0.0, min(1.0, (math.log10(rms) + 3.5) / 3.0))


def open_voice_check(app):
    window, content = ui._panel(app, "Voice check",
                                "Say “Doxa, what time is it?” in your normal voice. The bar of the mic you're talking into "
                                "should jump; press Use this mic on that one. Doxa listens all the time but only acts "
                                "after it hears “Doxa”. Listening for “Doxa” happens on this PC; with the natural voice on, the request after it is transcribed by OpenAI.", size="640x720")
    status = tk.StringVar()
    tk.Label(content, textvariable=status, bg=ui.BG, fg=ui.GOLD, font=(ui.BODY_BOLD, 10), anchor="w", justify="left",
             wraplength=560).pack(fill="x", pady=(0, 10))
    ui._section(content, "MICROPHONES")
    rows, monitors, levels = {}, [], {}
    try:
        names = whisper_listen.input_devices()
    except Exception as exc:
        names = []
        status.set(f"Couldn't list microphones: {exc}")

    def choose(name):
        app.settings_data.voice_device = name
        try:
            app.settings_data.save()
        except OSError:
            pass
        app.voice.device = name
        if app.voice.enabled:
            app.voice.restart()
        else:
            app.voice.enable()
            app.settings_data.voice_enabled = True

    def monitor(name):
        """A light, separate stream per mic just for the meter (closed with the window)."""
        try:
            import numpy as np
            import sounddevice
            index = whisper_listen.resolve_device(name)
            rate = int(sounddevice.query_devices(index)["default_samplerate"]) if index is not None else 16000

            def callback(data, frames, time_info, flags):
                levels[name] = float(np.sqrt(np.mean(np.square(data))))
            stream = sounddevice.InputStream(device=index, channels=1, samplerate=rate, blocksize=int(rate * 0.05),
                                             callback=callback)
            stream.start()
            monitors.append(stream)
        except Exception:
            levels[name] = -1.0  # can't open: shown as unavailable

    for name in names:
        row = tk.Frame(content, bg=ui.BG)
        row.pack(fill="x", pady=4)
        label = tk.Label(row, text=name, bg=ui.BG, fg=ui.TEXT, font=(ui.BODY, 10), anchor="w", width=34)
        label.pack(side="left")
        bar = tk.Canvas(row, width=170, height=10, bg=ui.SURFACE_2, highlightthickness=0)
        bar.pack(side="left", padx=8)
        fill = bar.create_rectangle(0, 0, 0, 10, fill=ui.GOLD, width=0)
        ui.button(row, "Use this mic", lambda n=name: choose(n), small=True).pack(side="right")
        rows[name] = (label, bar, fill)
        monitor(name)
    ui._section(content, "WHAT DOXA HEARD", top=18)
    heard = tk.Text(content, height=12, wrap="word", bg=ui.SURFACE, fg=ui.TEXT, relief="flat", borderwidth=8,
                    font=(ui.BODY, 10), highlightthickness=0, state="disabled")
    heard.pack(fill="x")
    always = tk.BooleanVar(value=bool(app.voice.enabled))
    tk.Checkbutton(content, text="Always listen for \"Doxa\" (off = only the chat box mic, click to talk)", variable=always,
                   command=lambda: (app.toggle_voice() if always.get() != app.voice.enabled else None), bg=ui.BG,
                   fg=ui.TEXT, selectcolor=ui.SURFACE_2, activebackground=ui.BG, activeforeground=ui.TEXT,
                   font=(ui.BODY, 10)).pack(anchor="w", pady=(10, 0))
    chime = tk.BooleanVar(value=app.voice.chime)
    tk.Checkbutton(content, text="Play a chime when Doxa hears its name", variable=chime,
                   command=lambda: setattr(app.voice, "chime", chime.get()), bg=ui.BG, fg=ui.TEXT,
                   selectcolor=ui.SURFACE_2, activebackground=ui.BG, activeforeground=ui.TEXT,
                   font=(ui.BODY, 10)).pack(anchor="w", pady=(10, 0))
    followup = tk.BooleanVar(value=bool(getattr(app.voice, "followup", True)))
    natural = tk.BooleanVar(value=bool(getattr(getattr(app, "cloud_voice", None), "enabled", False)))

    def save_voice_choices():
        app.voice.followup = bool(followup.get())
        app.settings_data.voice_conversation = app.voice.followup
        if getattr(app, "cloud_voice", None) is not None:
            app.cloud_voice.enabled = bool(natural.get())
        app.settings_data.cloud_voice = bool(natural.get())
        app.settings_data.save()

    for variable, text in ((followup, "Keep the conversation going: after Doxa answers out loud, talk for 8 seconds "
                                      "without saying \u201cDoxa\u201d"),
                           (natural, "Natural voice (Latina accent) and clearer hearing with OpenAI "
                                     "(about 1\u00a2 per few answers; Windows voice when offline)")):
        tk.Checkbutton(content, text=text, variable=variable, command=save_voice_choices, bg=ui.BG, fg=ui.TEXT,
                       selectcolor=ui.SURFACE_2, activebackground=ui.BG, activeforeground=ui.TEXT, wraplength=560,
                       justify="left", font=(ui.BODY, 10)).pack(anchor="w", pady=(4, 0))

    def refresh():
        if not window.winfo_exists():
            return
        current = app.voice.device or "Windows default"
        detector = app.voice.detector()
        status.set((f"Listening on: {current}" + (f" · {detector}" if detector else "")) if app.voice.enabled
                   else "Microphone is off. Press Use this mic, or the mic button, to start listening.")
        for name, (label, bar, fill) in rows.items():
            value = levels.get(name, 0.0)
            label.configure(fg=ui.GOLD if name == app.voice.device else (ui.FAINT if value < 0 else ui.TEXT))
            bar.coords(fill, 0, 0, 0 if value < 0 else 170 * level_fraction(value), 10)
        lines = [f"{when}  {'✓ ' + kind.upper() if kind else '   '}  {text}  ({conf:.2f})"
                 for when, text, conf, kind in list(app.voice.heard)[::-1]]
        heard.configure(state="normal")
        heard.delete("1.0", "end")
        heard.insert("1.0", "\n".join(lines) or "Nothing yet. Say “Doxa, what time is it?”")
        heard.configure(state="disabled")
        window.after(150, refresh)

    def close():
        for stream in monitors:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        window.destroy()
    window.protocol("WM_DELETE_WINDOW", close)
    refresh()
    return window
