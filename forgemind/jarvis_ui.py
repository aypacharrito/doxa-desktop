"""The native Doxa workspace: near-black, warm gold, one living orb."""
from __future__ import annotations

import math
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

try:  # Pillow gives anti-aliased rounded surfaces; plain Tk canvas shapes are jagged on Windows.
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # pragma: no cover - Pillow ships with Doxa's runtime
    Image = None

# Palette. Other panels import these names, so keep them (BLUE is the accent, now gold).
BG = '#0a0a0c'
SURFACE = '#131317'
SURFACE_2 = '#1b1b21'
LINE = '#24242b'
TEXT = '#f3eee5'
MUTED = '#8e897f'
FAINT = '#5d5951'
GOLD = '#e2b65e'
GOLD_BRIGHT = '#f7d995'
GOLD_DIM = '#6e5428'
INK = '#16110a'          # dark text on gold
ERROR = '#ef8f8f'
SELECT = '#3a2f1a'
BLUE = GOLD

HERE = Path(__file__).parent

# Fonts. Windows 11 ships Segoe UI Variable; fall back to Segoe UI elsewhere.
DISPLAY = 'Segoe UI Semibold'
BODY = 'Segoe UI'
BODY_BOLD = 'Segoe UI Semibold'


def _pick_fonts(root):
    global DISPLAY, BODY, BODY_BOLD, ICONS
    try:
        families = set(tkfont.families(root))
    except tk.TclError:
        return
    if 'Segoe Fluent Icons' in families:  # Windows 11's icon set: same code points, smoother modern shapes (1.38)
        ICONS = 'Segoe Fluent Icons'
    if 'Segoe UI Variable Display' in families:
        DISPLAY = 'Segoe UI Variable Display Semibold' if 'Segoe UI Variable Display Semibold' in families \
            else 'Segoe UI Variable Display'
    if 'Segoe UI Variable Text' in families:
        BODY = 'Segoe UI Variable Text'
        BODY_BOLD = 'Segoe UI Variable Text Semibold' if 'Segoe UI Variable Text Semibold' in families else BODY


def mix(a: str, b: str, t: float) -> str:
    """Blend two #rrggbb colours; t=0 gives a, t=1 gives b."""
    t = max(0.0, min(1.0, t))
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def version() -> str:
    try:
        return HERE.parent.joinpath('VERSION.txt').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


# ── Rounded surfaces ─────────────────────────────────────────

@lru_cache(maxsize=512)
def _rounded_image(w, h, radius, fill, outline, back):
    scale = 3
    img = Image.new('RGB', (w * scale, h * scale), back)
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, w * scale - 1, h * scale - 1), radius=radius * scale, fill=fill,
        outline=outline if outline != fill else None, width=scale)
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))


class Rounded(tk.Canvas):
    """A rounded, anti-aliased surface. Put widgets in ``.inner``; height follows its content."""

    def __init__(self, parent, *, radius=12, fill=SURFACE, outline=LINE, padx=16, pady=14, cursor=''):
        back = parent.cget('bg')
        super().__init__(parent, bg=back, highlightthickness=0, borderwidth=0, height=2 * pady + 4,
                         width=40, cursor=cursor)  # small default: Tk canvases otherwise ask for ~380px
        self.radius, self.fill, self.outline, self.back = radius, fill, outline, back
        self.padx, self.pady = padx, pady
        self._size = (0, 0)
        self._bg_item = self.create_image(0, 0, anchor='nw')
        self.inner = tk.Frame(self, bg=fill, cursor=cursor)
        self._win = self.create_window(padx, pady, window=self.inner, anchor='nw')
        self.bind('<Configure>', self._resize)
        self.inner.bind('<Configure>', self._fit, add='+')

    def _fit(self, _event=None):
        height = self.inner.winfo_reqheight() + 2 * self.pady
        if int(float(self.cget('height'))) != height:
            self.configure(height=height)

    def _resize(self, event):
        self._size = (event.width, event.height)
        self.itemconfigure(self._win, width=max(1, event.width - 2 * self.padx))
        self._paint()

    def _paint(self):
        w, h = self._size
        if w < 4 or h < 4:
            return
        if Image is None:
            self.delete('shape')
            self.create_rectangle(0, 0, w - 1, h - 1, fill=self.fill, outline=self.outline, tags='shape')
            self.tag_lower('shape')
            return
        self._image = _rounded_image(w, h, self.radius, self.fill, self.outline, self.back)
        self.itemconfigure(self._bg_item, image=self._image)

    def recolor(self, fill=None, outline=None):
        old = self.fill
        self.fill = fill or self.fill
        self.outline = outline or self.outline
        if self.fill != old:
            stack = [self.inner]
            while stack:
                w = stack.pop()
                try:
                    if w.cget('bg') == old:
                        w.configure(bg=self.fill)
                except tk.TclError:
                    pass
                stack.extend(w.winfo_children())
        self._paint()

    def on_click(self, command):
        """Make the whole surface (and everything in it) clickable."""
        for w in self._all():
            w.bind('<Button-1>', lambda _e: command(), add='+')

    def on_hover(self, enter, leave):
        def inside(event):
            x, y = self.winfo_pointerxy()
            return self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width() and \
                self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height()
        for w in self._all():
            w.bind('<Enter>', lambda _e: enter(), add='+')
            w.bind('<Leave>', lambda e: None if inside(e) else leave(), add='+')

    def _all(self):
        out, stack = [self], [self.inner]
        while stack:
            w = stack.pop()
            out.append(w)
            stack.extend(w.winfo_children())
        return out


# ── Icons, segmented switch, round icon buttons ─────────────

ICONS = 'Segoe MDL2 Assets'  # Windows' own icon font (Settings, Explorer)
GLYPH = {'team': '\uE716', 'add': '\uE710', 'search': '\uE721', 'plugins': '\uEA86', 'settings': '\uE713', 'mic': '\uE720',
         'stop': '\uE71A', 'send': '\uE724', 'folder': '\uE8B7', 'code': '\uE943', 'chat': '\uE8BD',
         'attach': '\uE723'}
RAISED = '#24242c'  # the selected segment: a soft lift, not a highlight


class Segmented(tk.Canvas):
    """A rounded pill with one rounded, slightly lighter segment for the current choice (like Claude/ChatGPT)."""

    def __init__(self, parent, options, command, *, height=34, pad=3, font_size=10, width=None):
        self.options, self.command, self.pad = list(options), command, pad
        self.font = (BODY_BOLD, font_size)
        probe = tk.Label(parent, font=self.font)
        widths = []
        for _value, label in self.options:
            probe.configure(text=label)
            widths.append(probe.winfo_reqwidth() + 28)
        probe.destroy()
        self.widths = widths
        total = width or (sum(widths) + 2 * pad)
        super().__init__(parent, width=total, height=height, bg=parent.cget('bg'), highlightthickness=0,
                         borderwidth=0, cursor='hand2')
        self.value = self.options[0][0]
        self.bind('<Button-1>', self._click)
        self._paint()

    def _spans(self):
        x, spans = self.pad, []
        for w in self.widths:
            spans.append((x, x + w))
            x += w
        return spans

    def _click(self, event):
        for (value, _label), (a, b) in zip(self.options, self._spans()):
            if a <= event.x < b:
                if value != self.value:
                    self.command(value)
                return

    def select(self, value):
        self.value = value
        self._paint()

    def _paint(self):
        self.delete('all')
        w, h = int(self.cget('width')), int(self.cget('height'))
        back = self.cget('bg')
        if Image is not None:
            self._bg = _rounded_image(w, h, h // 2, SURFACE, SURFACE, back)
            self.create_image(0, 0, image=self._bg, anchor='nw')
        for (value, label), (a, b) in zip(self.options, self._spans()):
            on = value == self.value
            if on and Image is not None:
                self._sel = _rounded_image(b - a, h - 2 * self.pad, (h - 2 * self.pad) // 2, RAISED, RAISED, SURFACE)
                self.create_image(a, self.pad, image=self._sel, anchor='nw')
            self.create_text((a + b) // 2, h // 2, text=label, fill=TEXT if on else MUTED, font=self.font)


class ThinScroll(tk.Canvas):
    """A slim, rounded scrollbar like ChatGPT/Claude: no arrows, no track, hidden when everything fits, a little wider
    on hover. Drop-in for ttk.Scrollbar(orient='vertical'): pass command=view.yview and give the view .set."""
    THUMB, HOVER = '#3a3942', '#6a6670'

    def __init__(self, parent, command=None, *, width=12, **_ignored):
        super().__init__(parent, width=width, bg=parent.cget('bg'), highlightthickness=0, borderwidth=0)
        self.command, self.first, self.last, self.hover, self._grab = command, 0.0, 1.0, False, None
        self.bind('<Configure>', lambda _e: self._paint())
        self.bind('<Enter>', lambda _e: self._hover(True))
        self.bind('<Leave>', lambda _e: self._hover(False))
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<ButtonRelease-1>', lambda _e: setattr(self, '_grab', None))

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._paint()

    def _hover(self, on):
        self.hover = on
        self._paint()

    def _paint(self):
        self.delete('all')
        if self.first <= 0.0 and self.last >= 1.0:
            return  # everything fits: no bar at all
        h, w = self.winfo_height(), self.winfo_width()
        top, bottom = self.first * h, max(self.first * h + 24, self.last * h)
        thick = 6 if (self.hover or self._grab is not None) else 4
        x = (w - thick) / 2
        self.create_line(x + thick / 2, top + thick / 2 + 2, x + thick / 2, bottom - thick / 2 - 2, width=thick,
                         capstyle='round', fill=self.HOVER if (self.hover or self._grab is not None) else self.THUMB)

    def _press(self, event):
        h = max(1, self.winfo_height())
        if self.first * h <= event.y <= self.last * h:
            self._grab = event.y / h - self.first
        elif self.command:
            self.command('scroll', -1 if event.y < self.first * h else 1, 'pages')

    def _drag(self, event):
        if self._grab is None or not self.command:
            return
        self.command('moveto', max(0.0, event.y / max(1, self.winfo_height()) - self._grab))


class IconButton(tk.Canvas):
    """A round icon button (anti-aliased circle + an icon-font glyph). Accepts the old text button's
    configure(text=…, fg=…, state=…) calls, so the rest of Doxa keeps working unchanged."""

    def __init__(self, parent, glyph, command, *, size=36, filled=False, tip=''):
        self.back = parent.cget('bg')
        super().__init__(parent, width=size, height=size, bg=self.back, highlightthickness=0, borderwidth=0,
                         cursor='hand2')
        self.size, self.glyph, self.command, self.filled = size, glyph, command, filled
        self.state_, self.lit, self.hover = 'normal', False, False
        self.bind('<Button-1>', lambda _e: self.command() if self.state_ != 'disabled' else None)
        self.bind('<Enter>', lambda _e: self._set_hover(True))
        self.bind('<Leave>', lambda _e: self._set_hover(False))
        self.tip = tip
        self._paint()

    def _set_hover(self, on):
        self.hover = on
        self._paint()

    def _paint(self):
        self.delete('all')
        s = self.size
        disabled = self.state_ == 'disabled'
        if self.filled:
            fill = GOLD_DIM if disabled else (GOLD_BRIGHT if self.hover else GOLD)
            ink = INK
        else:
            fill = SURFACE_2 if (self.hover or self.lit) else self.back
            ink = GOLD if self.lit else (TEXT if self.hover else MUTED)
        if Image is not None and fill != self.back:
            self._img = _rounded_image(s, s, s // 2, fill, fill, self.back)
            self.create_image(0, 0, image=self._img, anchor='nw')
        self.create_text(s // 2, s // 2 + 1, text=GLYPH.get(self.glyph, self.glyph), fill=ink,
                         font=(ICONS, max(9, s // 3)))

    def configure(self, cnf=None, **kw):
        if 'text' in kw:  # "Mic on" / "Mic off" from the voice code
            self.lit = 'on' in str(kw.pop('text')).lower()
        kw.pop('fg', None)
        if 'state' in kw:
            self.state_ = str(kw.pop('state'))
        if cnf or kw:
            super().configure(cnf, **kw)
        self._paint()

    config = configure


def link(parent, text, command, *, color=None):
    """Plain text that acts like a button (no box): for low-key actions such as Change or New chat."""
    label = tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color or MUTED, font=(BODY_BOLD, 9),
                     cursor='hand2')
    label.bind('<Button-1>', lambda _e: command())
    label.bind('<Enter>', lambda _e: label.configure(fg=TEXT))
    label.bind('<Leave>', lambda _e: label.configure(fg=color or MUTED))
    return label


def button(parent, text, command, *, active=False, small=False):
    """Flat button. active=True is the primary (gold) style."""
    base = parent.cget('bg')
    background = GOLD if active else base
    hover = GOLD_BRIGHT if active else SURFACE_2
    widget = tk.Button(parent, text=text, command=command, bg=background,
        fg=INK if active else TEXT, activebackground=hover, activeforeground=INK if active else TEXT,
        disabledforeground=GOLD_DIM if active else MUTED,
        relief='flat', borderwidth=0, highlightthickness=0, cursor='hand2',
        font=(BODY_BOLD, 10 if small else 11), anchor='center' if active else 'w',
        padx=16 if active else 12, pady=9)
    widget.bind('<Enter>', lambda _e: widget.configure(bg=hover) if str(widget['state']) != 'disabled' else None)
    widget.bind('<Leave>', lambda _e: widget.configure(bg=background))
    return widget


def card(parent, title, subtitle, command, *, number='', ghost=False):
    """A clickable rounded card. ghost=True is borderless until hovered (for lists)."""
    rest_fill, rest_line = (parent.cget('bg'), parent.cget('bg')) if ghost else (SURFACE, SURFACE)
    surface = Rounded(parent, fill=rest_fill, outline=rest_line, radius=10 if ghost else 12,
                      padx=14 if ghost else 18, pady=10 if ghost else 16, cursor='hand2')
    top = tk.Frame(surface.inner, bg=rest_fill, cursor='hand2')
    top.pack(fill='x')
    if number:
        tk.Label(top, text=number, bg=rest_fill, fg=GOLD, font=(BODY_BOLD, 9),
                 cursor='hand2').pack(side='left', padx=(0, 10))
    tk.Label(top, text=title, bg=rest_fill, fg=TEXT, font=(BODY_BOLD, 10 if ghost else 11), anchor='w',
             cursor='hand2').pack(side='left')
    arrow = tk.Label(top, text='→', bg=rest_fill, fg=FAINT, font=(BODY, 10), cursor='hand2')
    arrow.pack(side='right')
    sub = tk.Label(surface.inner, text=subtitle, bg=rest_fill, fg=MUTED, font=(BODY, 9), anchor='w',
                   justify='left', cursor='hand2')
    sub.pack(fill='x', pady=(3 if ghost else 6, 0))
    sub.bind('<Configure>', lambda e: sub.configure(wraplength=max(120, e.width - 4)))
    surface.on_click(command)

    def enter():
        surface.recolor(SURFACE_2, SURFACE_2)
        arrow.configure(fg=GOLD)

    def leave():
        surface.recolor(rest_fill, rest_line)
        arrow.configure(fg=FAINT)
    surface.on_hover(enter, leave)
    return surface


def logo(size: int):
    """The Doxa orb logo at a given pixel size (anti-aliased), or None."""
    path = HERE / 'doxa-icon.png'
    if Image is None or not path.is_file():
        return None
    return ImageTk.PhotoImage(Image.open(path).convert('RGBA').resize((size, size), Image.LANCZOS))


# ── The orb ──────────────────────────────────────────────────

class Orb(tk.Canvas):
    """A glowing gold sphere with an orbit ring and a voice meter.

    Idle: slow breathing. Listening/speaking (``active``): stronger pulse and meter.
    Thinking (app.busy): the ring spins faster. Everything is pre-built canvas items whose
    coordinates are updated, so each frame is cheap; it barely ticks when hidden.
    """
    HALO = 14
    CORE = 22

    def __init__(self, parent, app=None):
        super().__init__(parent, bg=BG, highlightthickness=0, height=280)
        self.app = app
        self.phase = 0.0
        self.spin = 0.0
        self._last_frame = time.monotonic()
        self.active = False
        self._items = None
        self.bind('<Configure>', lambda _e: self.draw())
        self.after(100, self.animate)

    def _build(self):
        self._halo = [self.create_oval(0, 0, 0, 0, outline='', fill=BG) for _ in range(self.HALO)]
        self._ring_back = self.create_line(0, 0, 0, 0, fill=GOLD_DIM, width=1, smooth=True)
        self._core = [self.create_oval(0, 0, 0, 0, outline='', fill=BG) for _ in range(self.CORE)]
        self._ring_front = self.create_line(0, 0, 0, 0, fill=GOLD, width=1.2, smooth=True)
        self._spark = self.create_oval(0, 0, 0, 0, outline='', fill=GOLD_BRIGHT)
        self._bars = [self.create_line(0, 0, 0, 0, fill=GOLD, width=2, capstyle='round') for _ in range(23)]
        self._items = True

    @property
    def thinking(self):
        return bool(self.app is not None and getattr(self.app, 'busy', False))

    def animate(self):
        if not self.winfo_exists():
            return
        visible = self.winfo_viewable()
        now = time.monotonic()
        elapsed = min(now - self._last_frame, .12)
        self._last_frame = now
        if visible:
            thinking = self.thinking
            self.phase += elapsed * (3.5 if self.active else 1.0)
            self.spin = (self.spin + elapsed * (2 if thinking else .65 if self.active else .18)) % math.tau
            self.draw()
        fast = self.active or self.thinking
        self.after((17 if fast else 33) if visible else 500, self.animate)

    def draw(self):
        if not self._items:
            self._build()
        w, h = max(300, self.winfo_width()), max(200, self.winfo_height())
        cx, cy = w / 2, h / 2 - 12
        breathe = math.sin(self.phase)
        level = 1.0 if self.active else (.75 if self.thinking else .55)
        r = min(h * .21, w * .16) * (1 + (.045 if self.active else .02) * breathe)

        # Halo: stacked discs fading from background to dim gold.
        for i, item in enumerate(self._halo):
            t = i / (self.HALO - 1)
            radius = r * (2.15 - 1.05 * t)
            glow = (.05 + .42 * t ** 2.2) * level * (1 + .12 * breathe)
            self.coords(item, cx - radius, cy - radius, cx + radius, cy + radius)
            self.itemconfigure(item, fill=mix(BG, GOLD_DIM, glow))

        # Core: a sphere lit from the upper left.
        for i, item in enumerate(self._core):
            t = i / (self.CORE - 1)
            radius = r * (1 - .86 * t)
            ox, oy = -r * .28 * t, -r * .32 * t
            if t < .55:
                colour = mix('#3d2b0e', GOLD, (t / .55) ** 1.2)
            else:
                colour = mix(GOLD, '#fff3d6', ((t - .55) / .45) ** 1.6)
            self.coords(item, cx + ox - radius, cy + oy - radius, cx + ox + radius, cy + oy + radius)
            self.itemconfigure(item, fill=colour)

        # Orbit ring, tilted; the back half is drawn behind the sphere.
        rx, ry, tilt = r * 1.55, r * .38, -.32
        back, front = [], []
        for step in range(61):
            a = step / 60 * math.tau + self.spin
            x, y = math.cos(a) * rx, math.sin(a) * ry
            px = cx + x * math.cos(tilt) - y * math.sin(tilt)
            py = cy + x * math.sin(tilt) + y * math.cos(tilt)
            (front if math.sin(a) > 0 else back).append((step, px, py))
        self._set_line(self._ring_back, back)
        self._set_line(self._ring_front, front)
        a = self.spin + math.pi / 2
        sx = cx + math.cos(a) * rx * math.cos(tilt) - math.sin(a) * ry * math.sin(tilt)
        sy = cy + math.cos(a) * rx * math.sin(tilt) + math.sin(a) * ry * math.cos(tilt)
        self.coords(self._spark, sx - 3, sy - 3, sx + 3, sy + 3)
        self.itemconfigure(self._spark, state='normal' if self.active or self.thinking else 'hidden')

        # Voice meter under the orb, only while listening or speaking.
        base_y = cy + r * 2.1 + 4
        for i, item in enumerate(self._bars):
            k = i - 11
            x = cx + k * 7
            amp = 14 * math.exp(-(k / 7) ** 2) * (.35 + .65 * abs(math.sin(self.phase * 2.1 + k * .8)))
            self.coords(item, x, base_y - amp, x, base_y + amp)
            self.itemconfigure(item, state='normal' if self.active else 'hidden',
                               fill=mix(GOLD_DIM, GOLD, math.exp(-(k / 8) ** 2)))

    def _set_line(self, item, points):
        # Split runs at the wrap-around so the line never jumps across the sphere.
        if len(points) < 2:
            self.itemconfigure(item, state='hidden')
            return
        points.sort()
        runs, current = [], [points[0]]
        for p in points[1:]:
            if p[0] != current[-1][0] + 1:
                runs.append(current)
                current = []
            current.append(p)
        runs.append(current)
        if len(runs) > 1 and runs[0][0][0] == 0 and runs[-1][-1][0] == 60:
            runs[0] = runs.pop() + runs[0]
        run = max(runs, key=len)
        flat = [c for _s, x, y in run for c in (x, y)]
        if len(flat) < 4:
            self.itemconfigure(item, state='hidden')
            return
        self.coords(item, *flat)
        self.itemconfigure(item, state='normal')


VoiceWave = Orb  # older name


def _greeting(name: str) -> str:
    hour = datetime.now().hour
    part = 'Good morning' if 5 <= hour < 12 else 'Good afternoon' if hour < 18 else 'Good evening'
    return f'{part}, {name}.' if name else f'{part}.'


# ── Sidebar navigation ───────────────────────────────────────

def _nav(app, sidebar, name, command, glyph=''):
    base = sidebar.cget('bg')
    row = Rounded(sidebar, fill=base, outline=base, radius=8, padx=12, pady=7, cursor='hand2')
    if glyph:
        icon = tk.Label(row.inner, text=GLYPH.get(glyph, glyph), bg=base, fg=MUTED, font=(ICONS, 10), width=2,
                        anchor='w', cursor='hand2')
        icon.pack(side='left', padx=(0, 8))
    label = tk.Label(row.inner, text=name, bg=base, fg=MUTED, font=(BODY_BOLD, 10), anchor='w', cursor='hand2')
    label.pack(side='left', fill='x', expand=True)
    row.pack(fill='x', pady=1)
    row._label, row._name, row._base = label, name, base
    row.on_click(command)

    def hover(on):
        if app._nav_current != name:
            row.recolor(SURFACE_2 if on else base, SURFACE_2 if on else base)
            label.configure(fg=TEXT if on else MUTED)
    row.on_hover(lambda: hover(True), lambda: hover(False))
    return row


def set_view(app, name):
    """Highlight the sidebar entry for the main view (Home or Conversation)."""
    app._nav_current = name
    for row in getattr(app, '_nav_buttons', []):
        on = row._name == name
        base = getattr(row, '_base', BG)
        row.recolor(SURFACE_2 if on else base, SURFACE_2 if on else base)
        row._label.configure(fg=GOLD if on else MUTED)


# ── ttk theme ────────────────────────────────────────────────

def style_ttk(app):
    """Dark-gold look for every ttk widget used across Doxa's panels."""
    style = ttk.Style(app)
    style.configure('.', background=BG, foreground=TEXT, fieldbackground=SURFACE, bordercolor=LINE,
                    lightcolor=BG, darkcolor=BG, troughcolor=SURFACE, selectbackground=SELECT,
                    selectforeground=TEXT, insertcolor=GOLD, focuscolor=GOLD_DIM, font=(BODY, 10))
    style.configure('TFrame', background=BG)
    style.configure('Panel.TFrame', background=BG)
    style.configure('TLabel', background=BG, foreground=TEXT, font=(BODY, 10))
    style.configure('Title.TLabel', background=BG, foreground=TEXT, font=(DISPLAY, 20))
    style.configure('Muted.TLabel', background=BG, foreground=MUTED, font=(BODY, 9))
    style.configure('Faint.TLabel', background=BG, foreground=FAINT, font=(BODY, 9))
    style.configure('Card.TLabel', background=SURFACE, foreground=TEXT, font=(BODY, 9))
    style.configure('CardMuted.TLabel', background=SURFACE, foreground=MUTED, font=(BODY, 9))
    style.configure('Panel.TLabel', background=BG, foreground=TEXT, font=(BODY, 10))
    style.configure('PanelMuted.TLabel', background=BG, foreground=MUTED, font=(BODY, 9))
    style.configure('TButton', background=SURFACE_2, foreground=TEXT, bordercolor=LINE, lightcolor=SURFACE_2,
                    darkcolor=SURFACE_2, focuscolor=SURFACE_2, font=(BODY_BOLD, 9), padding=(12, 7), relief='flat')
    style.map('TButton', background=[('disabled', SURFACE), ('pressed', LINE), ('active', '#25252d')],
              foreground=[('disabled', MUTED)], bordercolor=[('active', GOLD_DIM), ('focus', GOLD_DIM)],
              lightcolor=[('active', '#25252d')], darkcolor=[('active', '#25252d')])
    style.configure('Accent.TButton', background=GOLD, foreground=INK, bordercolor=GOLD,
                    lightcolor=GOLD, darkcolor=GOLD, focuscolor=GOLD)
    style.map('Accent.TButton', background=[('disabled', GOLD_DIM), ('pressed', GOLD), ('active', GOLD_BRIGHT)],
              foreground=[('disabled', INK)], lightcolor=[('active', GOLD_BRIGHT)], darkcolor=[('active', GOLD_BRIGHT)],
              bordercolor=[('active', GOLD_BRIGHT)])
    for name in ('TCheckbutton', 'TRadiobutton'):
        style.configure(name, background=BG, foreground=TEXT, indicatorbackground=SURFACE,
                        indicatorforeground=GOLD, font=(BODY, 10))
        style.map(name, background=[('active', BG)], foreground=[('active', TEXT)],
                  indicatorbackground=[('selected', GOLD), ('active', SURFACE_2)],
                  indicatorforeground=[('selected', INK)])
    style.configure('TEntry', fieldbackground=SURFACE, foreground=TEXT, bordercolor=LINE,
                    lightcolor=SURFACE, darkcolor=SURFACE, insertcolor=GOLD, padding=6)
    style.map('TEntry', bordercolor=[('focus', GOLD_DIM)], lightcolor=[('focus', GOLD_DIM)])
    style.configure('TCombobox', fieldbackground=SURFACE, background=SURFACE_2, foreground=TEXT,
                    arrowcolor=GOLD, bordercolor=LINE, lightcolor=SURFACE, darkcolor=SURFACE, padding=5)
    style.map('TCombobox', fieldbackground=[('readonly', SURFACE)], foreground=[('readonly', TEXT)],
              bordercolor=[('focus', GOLD_DIM)])
    app.option_add('*TCombobox*Listbox.background', SURFACE)
    app.option_add('*TCombobox*Listbox.foreground', TEXT)
    app.option_add('*TCombobox*Listbox.selectBackground', SELECT)
    app.option_add('*TCombobox*Listbox.selectForeground', TEXT)
    style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                    bordercolor=LINE, rowheight=28, font=(BODY, 10))
    style.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', GOLD_BRIGHT)])
    style.configure('Treeview.Heading', background=BG, foreground=MUTED, bordercolor=LINE,
                    relief='flat', font=(BODY_BOLD, 9))
    style.map('Treeview.Heading', background=[('active', SURFACE)])
    style.configure('TLabelframe', background=BG, bordercolor=LINE, lightcolor=BG, darkcolor=BG)
    style.configure('TLabelframe.Label', background=BG, foreground=GOLD, font=(BODY_BOLD, 9))
    for orient in ('Vertical', 'Horizontal'):
        style.configure(f'{orient}.TScrollbar', background=LINE, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, lightcolor=LINE, darkcolor=LINE, gripcount=0)
        style.map(f'{orient}.TScrollbar', background=[('active', GOLD_DIM)])
    style.configure('Horizontal.TProgressbar', background=GOLD, troughcolor=BG,  # a thin gold line, no grey track
                    bordercolor=BG, lightcolor=GOLD, darkcolor=GOLD, thickness=2)
    for key, value in {'background': LINE, 'activeBackground': GOLD_DIM, 'troughColor': BG,
                       'borderWidth': 0, 'relief': 'flat', 'width': 10}.items():
        app.option_add('*Scrollbar.' + key, value)
    for key, value in {'background': SURFACE, 'foreground': TEXT, 'selectBackground': SELECT,
                       'selectForeground': TEXT, 'insertBackground': GOLD}.items():
        app.option_add('*Listbox.' + key, value)
        app.option_add('*Text.' + key, value)
        app.option_add('*Entry.' + key, value)


def _dark_titlebar(window):
    """Windows 11: dark title bar in Doxa's background colour."""
    try:
        import ctypes
        handle = ctypes.windll.user32.GetParent(window.winfo_id())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(handle, 20, ctypes.byref(on), ctypes.sizeof(on))  # immersive dark mode
        colorref = lambda c: ctypes.c_int(int(c[5:7] + c[3:5] + c[1:3], 16))  # #rrggbb -> 0x00bbggrr
        caption, text = colorref(BG), colorref(TEXT)
        dwm.DwmSetWindowAttribute(handle, 35, ctypes.byref(caption), ctypes.sizeof(caption))  # caption colour
        dwm.DwmSetWindowAttribute(handle, 36, ctypes.byref(text), ctypes.sizeof(text))  # caption text
    except (AttributeError, OSError):
        pass


def _section(parent, text, top=0):
    tk.Label(parent, text=text, bg=parent.cget('bg'), fg=FAINT, font=(BODY_BOLD, 8),
             anchor='w').pack(fill='x', pady=(top, 6))


# ── Main window ──────────────────────────────────────────────

def attach_files(app):
    """Pick photos/documents; they're copied to Documents\\Doxa Inbox and added to the message as [Attached file: …]."""
    from tkinter import filedialog
    from .attachments import save_file
    paths = filedialog.askopenfilenames(parent=app, title="Send to Doxa", filetypes=[
        ("Photos and documents", "*.jpg *.jpeg *.png *.webp *.gif *.pdf *.docx *.txt *.csv *.md *.json"), ("All files", "*.*")])
    tags = []
    for path in paths or ():
        try:
            tags.append(save_file(path)["tag"])
        except (OSError, ValueError) as exc:
            app._set_status(f"Couldn't attach {path}: {exc}")
    if not tags:
        return
    text = app.input.get('1.0', 'end').rstrip()
    app.input.delete('1.0', 'end')
    app.input.insert('1.0', ((text or "Look at this.") + "\n" + "\n".join(tags)).strip())
    hint = getattr(app, '_composer_hint', None)
    if hint is not None:
        hint.place_forget()
    app.input.focus_set()
    app._set_status(f"Attached {len(tags)} file(s). Add your question and press Enter.")


def build(app):
    _pick_fonts(app)
    style_ttk(app)
    app.title('Doxa')
    app.geometry('1360x860')
    app.minsize(1040, 720)
    app.configure(bg=BG)
    try:  # own taskbar entry and icon instead of grouping under python.exe
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Doxa.Desktop')
    except (AttributeError, OSError):
        pass
    icon = HERE / 'doxa-icon.png'  # doxa.ico beside it is for desktop shortcuts
    if not icon.is_file():
        icon = HERE / 'jarvis-icon.png'
    if icon.is_file():
        app._jarvis_icon = tk.PhotoImage(file=str(icon))
        app.iconphoto(True, app._jarvis_icon)
    try:  # pinning to the taskbar keeps the Doxa icon and relaunches Doxa (not bare pythonw.exe)
        from .win_identity import apply_to_window
        app.update_idletasks()
        apply_to_window(int(app.wm_frame(), 16), HERE / 'doxa.ico')
    except (ImportError, ValueError, tk.TclError):
        pass
    app.columnconfigure(2, weight=1)
    app.rowconfigure(0, weight=1)

    # Sidebar: chat-first, like ChatGPT / Claude / Gemini. Everything else lives under Skills and Tools.
    sidebar = tk.Frame(app, bg=SURFACE, width=236, padx=12, pady=18)
    sidebar.grid(row=0, column=0, sticky='ns')
    sidebar.grid_propagate(False)
    sidebar.pack_propagate(False)
    tk.Frame(app, bg=LINE, width=1).grid(row=0, column=1, sticky='ns')
    brand = tk.Frame(sidebar, bg=SURFACE, cursor='hand2')
    brand.pack(fill='x', padx=(8, 0), pady=(0, 18))
    app._logo_small = logo(28)
    if app._logo_small:
        mark = tk.Label(brand, image=app._logo_small, bg=SURFACE, cursor='hand2')
    else:
        mark = tk.Label(brand, text='●', bg=SURFACE, fg=GOLD, font=(BODY, 16))
    mark.pack(side='left', padx=(0, 10))
    word = tk.Label(brand, text='Doxa', bg=SURFACE, fg=TEXT, font=(DISPLAY, 16), cursor='hand2')
    word.pack(side='left')
    for w in (brand, mark, word):
        w.bind('<Button-1>', lambda _e: app.show_home())

    nav = tk.Frame(sidebar, bg=SURFACE)
    nav.pack(fill='x')
    app._nav_current = 'Home'
    # Everything else is asked for in chat (Tools went away in 1.19.1); connections live in Plugins.
    app._nav_buttons = [_nav(app, nav, name, command, glyph) for name, command, glyph in [
        ('New chat', app.show_home, 'add'), ('Search', app.show_memory, 'search'),
        ('Team HQ', app.show_team_hq, 'team'), ('Plugins', app.show_plugins, 'plugins')]]
    tk.Label(sidebar, text='Recent', bg=SURFACE, fg=FAINT, font=(BODY_BOLD, 8), anchor='w',
             padx=12).pack(fill='x', pady=(20, 4))
    app._recents_box = tk.Frame(sidebar, bg=SURFACE)
    app._recents_box.pack(fill='x')

    foot = tk.Frame(sidebar, bg=SURFACE)
    foot.pack(side='bottom', fill='x')
    app._nav_buttons.append(_nav(app, foot, 'Settings', app.show_settings, 'settings'))
    v = version()
    tk.Label(foot, text=(f'Doxa {v}' if v else 'Doxa'), bg=SURFACE, fg=FAINT,
             font=(BODY, 8), anchor='w', padx=12).pack(fill='x', pady=(8, 0))
    set_view(app, 'Home')

    # Workspace
    workspace = tk.Frame(app, bg=BG, padx=48, pady=20)
    app._workspace = workspace
    workspace.bind('<Configure>', lambda _e: center_column(app), add='+')
    workspace.grid(row=0, column=2, sticky='nsew')
    workspace.columnconfigure(0, weight=1)
    workspace.rowconfigure(1, weight=1)
    top = tk.Frame(workspace, bg=BG)
    top.grid(row=0, column=0, sticky='ew', pady=(0, 4))
    # Chat | Work | Code in the middle, like ChatGPT's Chat | Work (1.38)
    top.columnconfigure(0, weight=1, uniform='top')
    top.columnconfigure(2, weight=1, uniform='top')
    app._mode_switch = Segmented(top, [('chat', 'Chat'), ('work', 'Work'), ('code', 'Code')], app.set_mode)
    app._mode_switch.grid(row=0, column=1)
    app._mode_buttons = {}
    right = tk.Frame(top, bg=BG)
    right.grid(row=0, column=2, sticky='e')
    tk.Label(right, text='●', bg=BG, fg=GOLD, font=(BODY, 7)).pack(side='left', padx=(0, 6))
    app.model_label = ttk.Label(right, text='Local brain · Choose a model', style='Muted.TLabel')
    app.model_label.pack(side='left')

    body = tk.Frame(workspace, bg=BG)
    body.grid(row=1, column=0, sticky='nsew')
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    conversation = tk.Frame(body, bg=BG)
    conversation.grid(row=0, column=0, sticky='nsew')
    app._conversation = conversation
    from . import code_view
    app.code_frame = code_view.build(app, body)
    app.code_frame.grid(row=0, column=0, sticky='nsew')
    app.code_frame.grid_remove()

    # Home (1.38, after ChatGPT's Work screen): a small orb, one question, the message box in the middle,
    # a tray (Files · Plugins · Team HQ · AI brains) and a few suggestions as quiet rows.
    app.hero = tk.Frame(conversation, bg=BG)
    app.hero.pack(fill='both', expand=True)
    center = tk.Frame(app.hero, bg=BG)
    center.pack(expand=True)
    app.wave = Orb(center, app)
    app.wave.configure(width=420, height=150)
    app.wave.pack()
    app.hero_title = tk.Label(center, text=_greeting(app.settings_data.display_name), bg=BG, fg=TEXT,
                              font=(DISPLAY, 26))
    app.hero_title.pack(pady=(0, 4))
    app.hero_sub = tk.Label(center, text='', bg=BG, fg=MUTED, font=(BODY, 10))
    app.hero_sub.pack()
    # Kept for the voice code (it updates them); the footer shows the same state, so they aren't drawn.
    app.voice_label = tk.Label(center, text='', bg=BG)
    app.voice_hint = tk.Label(center, text='', bg=BG)
    app._composer_slot = tk.Frame(center, bg=BG, width=HERO_WIDTH, height=96)
    app._composer_slot.pack(pady=(22, 0))
    app._composer_slot.pack_propagate(False)
    tray = tk.Frame(center, bg=BG)
    tray.pack(fill='x', padx=18, pady=(8, 0))
    for glyph, label, action in (('attach', 'Files', lambda: attach_files(app)), ('plugins', 'Plugins', app.show_plugins),
                                 ('team', 'Team HQ', app.show_team_hq), ('settings', 'AI brains', app.show_brains)):
        _tray_link(tray, glyph, label, action).pack(side='left', padx=(0, 18))

    def ask(text):
        app.input.delete('1.0', 'end')
        app.input.insert('1.0', text)
        app.send()
    starters = [
        ('search', 'Find products to sell', 'Trending products with hooks, suppliers and profit',
         lambda: ask('Find winning products for me')),
        ('folder', 'Build a website', 'A site for a local business from your footage', app.show_website_builder),
        ('code', 'Break down a reel', 'Paste a link: why it works and how to copy it',
         lambda: app.run_skill('reel_breakdown')),
        ('attach', 'Contest a ticket', 'Photo of a CA ticket → TR-205 paperwork', app.show_ticket_helper),
    ]
    suggestions = tk.Frame(center, bg=BG, width=HERO_WIDTH)
    suggestions.pack(fill='x', pady=(22, 0))
    for glyph, title, subtitle, action in starters:
        _suggestion(suggestions, glyph, title, subtitle, action).pack(fill='x')

    app.chat_frame = tk.Frame(conversation, bg=BG)
    app.chat = tk.Text(app.chat_frame, wrap='word', bg=BG, fg=TEXT, insertbackground=GOLD,
        relief='flat', borderwidth=0, highlightthickness=0, font=(BODY, 12),
        padx=8, pady=12, spacing1=5, spacing3=12, selectbackground=SELECT)
    scroll = ThinScroll(app.chat_frame, command=app.chat.yview)
    app.chat.configure(yscrollcommand=scroll.set, state='disabled')
    scroll.pack(side='right', fill='y')
    app.chat.pack(side='left', fill='both', expand=True)
    for name, color, font in [('user', MUTED, (BODY_BOLD, 9)),
                              ('assistant', GOLD, (BODY_BOLD, 9)),
                              ('body', TEXT, (BODY, 12)),
                              ('muted', MUTED, (BODY, 10)),
                              ('error', ERROR, (BODY, 11))]:
        app.chat.tag_configure(name, foreground=color, font=font, spacing3=12)

    # System details are kept (other code updates them) and shown in Tools instead of a side rail.
    app.right_panel = system = tk.Frame(app, bg=SURFACE)
    app.capability_label = tk.Label(system, text='Screen vision · checking', bg=SURFACE, fg=MUTED, font=(BODY, 9))
    app.stats_label = ttk.Label(system, style='CardMuted.TLabel')
    app.growth_label = ttk.Label(system, text='', style='CardMuted.TLabel')
    app.learning_label = ttk.Label(system, text='Model experiments paused', style='CardMuted.TLabel')
    app.memory_list = tk.Listbox(system, bg=SURFACE, fg=TEXT, selectbackground=SELECT,
        relief='flat', borderwidth=0, highlightthickness=0, font=(BODY, 10), height=5)
    progress_row = tk.Frame(workspace, bg=BG)
    progress_row.grid(row=2, column=0, sticky='ew')
    app.progress = ttk.Progressbar(progress_row, mode='determinate')

    # Composer: centered on the home screen, docked at the bottom once a conversation starts (dock_composer)
    composer = Rounded(workspace, fill=SURFACE, outline=SURFACE, radius=22, padx=16, pady=10)
    composer.grid(row=3, column=0, sticky='ew', pady=(14, 0))
    app._composer = composer
    row = composer.inner
    row.columnconfigure(0, weight=1)
    app.input = tk.Text(row, height=2, bg=SURFACE, fg=TEXT, insertbackground=GOLD,
        relief='flat', highlightthickness=0, borderwidth=0, wrap='word',
        font=(BODY, 12), padx=8, pady=10, selectbackground=SELECT)
    app.input.grid(row=0, column=0, sticky='ew')
    hint = tk.Label(app.input, text='Ask Doxa anything…', bg=SURFACE, fg=FAINT,
                    font=(BODY, 12), cursor='xterm')
    app._composer_hint = hint
    hint.place(x=8, y=10)
    hint.bind('<Button-1>', lambda _e: app.input.focus_set())

    def update_hint(_event=None):
        focused = app.focus_get() == app.input
        composer.recolor(outline=LINE if focused else SURFACE)
        if app.input.get('1.0', 'end').strip() or focused:
            hint.place_forget()
        else:
            hint.place(x=8, y=10)
    app.input.bind('<FocusIn>', update_hint)
    app.input.bind('<FocusOut>', update_hint)
    app.input.bind('<KeyRelease>', update_hint)
    app.input.bind('<Control-Return>', lambda _e: app.send())
    # which AI answers in this lane (click = AI brains), like ChatGPT's model picker in the box
    app.lane_pill = tk.Label(row, text='', bg=SURFACE, fg=MUTED, font=(BODY_BOLD, 9), cursor='hand2', padx=8)
    app.lane_pill.grid(row=0, column=1, padx=(4, 6))
    app.lane_pill.bind('<Button-1>', lambda _e: app.show_brains())
    app.lane_pill.bind('<Enter>', lambda _e: app.lane_pill.configure(fg=TEXT))
    app.lane_pill.bind('<Leave>', lambda _e: app.lane_pill.configure(fg=MUTED))
    # the paperclip (2026-11-09): photos, PDFs, documents → Doxa Inbox; Claude opens them with view_file
    IconButton(row, 'attach', lambda: attach_files(app)).grid(row=0, column=2, padx=2)
    app.mic_button = IconButton(row, 'mic', app.toggle_dictation)  # click to talk → words in the box (1.35)
    app.mic_button.grid(row=0, column=3, padx=2)
    IconButton(row, 'stop', app.stop_jarvis).grid(row=0, column=4, padx=(2, 8))
    app.send_button = IconButton(row, 'send', app.send, filled=True)
    app.send_button.grid(row=0, column=5)
    footer = tk.Frame(workspace, bg=BG)
    footer.grid(row=4, column=0, sticky='ew', pady=(8, 0), padx=(14, 4))
    app.status_label = ttk.Label(footer, text='Ready', style='Faint.TLabel')
    app.status_label.pack(side='left')
    app.live_voice = tk.Label(footer, text='Ctrl+Enter to send  ·  Esc to stop',
        bg=BG, fg=FAINT, font=(BODY, 9), anchor='e')
    app.live_voice.pack(side='right')
    app.bind('<Escape>', lambda _e: app.stop_jarvis())
    app.bind('<Control-k>', lambda _e: app.show_quick_actions())
    app.bind('<Control-p>', lambda _e: app.show_memory())
    app.after(50, lambda: _dark_titlebar(app))
    paint_mode(app, getattr(app, 'mode', 'chat'))
    app.after(80, lambda: dock_composer(app))


HERO_WIDTH = 720
LANES = {
    'chat': ('Free and private: answers come from the AI on your PC.', 'Ask Doxa anything…'),
    'work': ('Claude, ChatGPT and your other paid AIs. When one runs out, the next one takes over.',
             'Give Doxa a task: research, write, build, plan…'),
}


def _tray_link(parent, glyph, label, action):
    box = tk.Frame(parent, bg=BG, cursor='hand2')
    icon = tk.Label(box, text=GLYPH.get(glyph, ''), bg=BG, fg=MUTED, font=(ICONS, 9), cursor='hand2')
    icon.pack(side='left', padx=(0, 6))
    text = tk.Label(box, text=label, bg=BG, fg=MUTED, font=(BODY_BOLD, 9), cursor='hand2')
    text.pack(side='left')
    for widget in (box, icon, text):
        widget.bind('<Button-1>', lambda _e: action())
        widget.bind('<Enter>', lambda _e: (icon.configure(fg=TEXT), text.configure(fg=TEXT)))
        widget.bind('<Leave>', lambda _e: (icon.configure(fg=MUTED), text.configure(fg=MUTED)))
    return box


def _suggestion(parent, glyph, title, subtitle, action):
    """One quiet row (icon · title · what it does), lit on hover: ChatGPT's suggestion list."""
    row = tk.Frame(parent, bg=BG, padx=18, pady=9, cursor='hand2')
    icon = tk.Label(row, text=GLYPH.get(glyph, ''), bg=BG, fg=GOLD, font=(ICONS, 11), width=2, cursor='hand2')
    icon.pack(side='left', padx=(0, 10))
    name = tk.Label(row, text=title, bg=BG, fg=TEXT, font=(BODY_BOLD, 10), cursor='hand2')
    name.pack(side='left')
    note = tk.Label(row, text='  ·  ' + subtitle, bg=BG, fg=FAINT, font=(BODY, 10), cursor='hand2')
    note.pack(side='left')
    parts = (row, icon, name, note)

    def paint(color):
        for widget in parts:
            widget.configure(bg=color)
    for widget in parts:
        widget.bind('<Button-1>', lambda _e: action())
        widget.bind('<Enter>', lambda _e: paint(SURFACE))
        widget.bind('<Leave>', lambda _e: paint(BG))
    return row


def dock_composer(app):
    """Composer in the middle of the home screen (Chat/Work, nothing said yet), at the bottom otherwise."""
    composer = getattr(app, '_composer', None)
    slot = getattr(app, '_composer_slot', None)
    if composer is None or slot is None:
        return
    centered = getattr(app, 'mode', 'chat') != 'code' and bool(app.hero.winfo_manager())
    if centered:
        composer.grid_remove()
        composer.place(in_=slot, x=0, y=0, relwidth=1)
        composer.tk.call('raise', composer._w)  # Canvas.lift() raises canvas items, not the widget
        app.update_idletasks()
        slot.configure(height=max(60, composer.winfo_reqheight()))
    else:
        composer.place_forget()
        composer.grid()
    center_column(app)


READ_WIDTH = 820  # ChatGPT-style reading column: conversation and message box stay this wide, centered


def center_column(app):
    """Keep the conversation and the docked message box in a centered column on wide windows."""
    workspace = getattr(app, '_workspace', None)
    if workspace is None:
        return
    width = workspace.winfo_width()
    if width <= 1:
        return
    side = max(0, (width - 96 - READ_WIDTH) // 2)
    composer = getattr(app, '_composer', None)
    if composer is not None and composer.winfo_manager() == 'grid':
        composer.grid_configure(padx=side)
    chat = getattr(app, 'chat', None)
    if chat is not None:
        chat.configure(padx=8 + side)


def lane_text(app, mode):
    """What the pill in the message box says: which AI answers in this lane right now."""
    brain = getattr(app, 'brain', None)
    if mode == 'code':
        return 'Codex · Claude Code'
    if brain is None:
        return ''
    try:
        if mode == 'chat':
            if brain.local.loaded:
                return 'On your PC'
            free = brain.lane_brains(app.settings_data, 'chat')
            return (free[0].display_name + ' · free') if free else 'PC model not loaded'
        paid = brain.lane_brains(app.settings_data, 'work')
        if not paid:
            return 'No paid AI left'
        names = [b.display_name.replace('OpenAI', 'ChatGPT') for b in paid]
        return names[0] + (f'  +{len(names) - 1} backup' if len(names) > 1 else '')
    except Exception:
        return ''


def paint_mode(app, mode):
    switch = getattr(app, '_mode_switch', None)
    if switch is not None:
        switch.select(mode)
    sub, hint_text = LANES.get(mode, LANES['chat'])
    hint = getattr(app, '_composer_hint', None)
    if hint is not None:
        hint.configure(text={'code': 'Tell Codex or Claude Code what to build, fix or reverse-engineer…',
                             'team': 'Ask Doxa about the campaign, or tell the team what to do…'}.get(mode, hint_text))
    title = getattr(app, 'hero_title', None)
    if title is not None:
        title.configure(text='What should we work on?' if mode == 'work'
                        else _greeting(app.settings_data.display_name))
    if getattr(app, 'hero_sub', None) is not None:
        app.hero_sub.configure(text=sub)
    if getattr(app, 'lane_pill', None) is not None:
        app.lane_pill.configure(text=lane_text(app, mode))
    dock_composer(app)


def show_chat(app):
    set_view(app, 'Conversation')
    if app.hero.winfo_manager():
        app.hero.pack_forget()
        app.chat_frame.pack(fill='both', expand=True)
    dock_composer(app)


def show_hero(app):
    app.chat_frame.pack_forget()
    app.hero.pack(fill='both', expand=True)
    dock_composer(app)


def settings_window(app, groups):
    window, content = _panel(app, 'Settings', 'Connections, brains, voice and your phone.', size='600x760')
    for group, items in groups:
        _section(content, group.upper(), top=12)
        for title, subtitle, action in items:
            def run(action=action):
                window.destroy()
                action()
            card(content, title, subtitle, run, ghost=True).pack(fill='x', pady=1)
    return window


def tools_window(app, title, actions):
    window = tk.Toplevel(app)
    window.title('Doxa · ' + title)
    window.geometry('560x660')
    window.configure(bg=BG)
    window.transient(app)
    window.after(50, lambda: _dark_titlebar(window))
    pop_in(window)
    content = tk.Frame(window, bg=BG, padx=28, pady=24)
    content.pack(fill='both', expand=True)
    tk.Label(content, text=title, bg=BG, fg=TEXT, font=(DISPLAY, 22)).pack(anchor='w', pady=(0, 18))
    for label, action in actions:
        button(content, label, action).pack(fill='x', pady=2)
    return window


def refresh_recents(app, limit=8):
    """Sidebar 'Recent': the last few things the owner asked (click to reopen the conversation)."""
    box = getattr(app, '_recents_box', None)
    if box is None:
        return
    for child in box.winfo_children():
        child.destroy()
    shown = 0
    try:
        chats = app.db.chats(limit)
    except Exception:
        chats = []
    for chat in chats:  # past chats, newest first (like ChatGPT/Claude)
        text = chat.get('title') or 'Chat'
        label = tk.Label(box, text=text[:30] + ('…' if len(text) > 30 else ''), bg=box.cget('bg'), fg=MUTED,
                         font=(BODY, 9), anchor='w', padx=12, pady=4, cursor='hand2')
        label.pack(fill='x')
        label.bind('<Button-1>', lambda _e, cid=chat['id']: app.open_chat(cid))
        label.bind('<Enter>', lambda _e, w=label: w.configure(fg=TEXT, bg=SURFACE_2))
        label.bind('<Leave>', lambda _e, w=label: w.configure(fg=MUTED, bg=box.cget('bg')))
        shown += 1
        if shown >= limit:
            break
    if not shown:
        tk.Label(box, text='Your chats will show here.', bg=box.cget('bg'), fg=FAINT, font=(BODY, 9),
                 anchor='w', padx=12).pack(fill='x')


def pop_in(window, steps=(0.0, 0.35, 0.7, 0.9, 1.0), delay=22):
    """Panels pop in (a quick fade) instead of just appearing. Not for windows that host another app's window."""
    try:
        window.attributes('-alpha', steps[0])
    except tk.TclError:
        return

    # Own timer commands on the interpreter's root. Cancelling a child-owned
    # timer through the root can otherwise leave a stale Tcl command on teardown.
    scheduler = window._root()
    pending = None

    def cancel(event):
        if event.widget is window and pending is not None:
            try:
                scheduler.after_cancel(pending)
            except tk.TclError:
                pass

    window.bind('<Destroy>', cancel, add='+')

    def step(i=1):
        nonlocal pending
        pending = None
        if i >= len(steps) or not window.winfo_exists():
            return
        try:
            window.attributes('-alpha', steps[i])
        except tk.TclError:
            return
        if i + 1 < len(steps):
            pending = scheduler.after(delay, lambda: step(i + 1))
    pending = scheduler.after(delay, step)


def _panel(app, title, subtitle, size='620x700'):
    window = tk.Toplevel(app)
    window.title('Doxa · ' + title)
    window.geometry(size)
    window.configure(bg=BG)
    window.transient(app)
    window.after(50, lambda: _dark_titlebar(window))
    pop_in(window)
    outer = tk.Frame(window, bg=BG)
    outer.pack(fill='both', expand=True)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, borderwidth=0)
    bar = ThinScroll(outer, command=canvas.yview)
    content = tk.Frame(canvas, bg=BG, padx=28, pady=22)
    item = canvas.create_window(0, 0, window=content, anchor='nw')
    content.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    window.bind('<MouseWheel>', lambda e: canvas.yview_scroll(int(-e.delta / 120), 'units'))
    tk.Label(content, text=title, bg=BG, fg=TEXT, font=(DISPLAY, 22), anchor='w').pack(fill='x')
    tk.Label(content, text=subtitle, bg=BG, fg=MUTED, font=(BODY, 10), anchor='w', justify='left',
             wraplength=540).pack(fill='x', pady=(4, 10))
    return window, content


def open_skills(app):
    from . import skills
    window, content = _panel(app, 'Skills', 'Ready-made workflows. Checklists answer instantly; the others fill in '
                                            'the message box so you can add your details and press Send.')
    for group, items in skills.groups():
        _section(content, group.upper(), top=12)
        for skill in items:
            def run(key=skill.key):
                window.destroy()
                app.run_skill(key)
            card(content, skill.title, skill.subtitle, run, ghost=True).pack(fill='x', pady=1)
    return window


def open_tools(app, groups):
    """Everything that used to sit in the sidebar and side rail, in one place."""
    window, content = _panel(app, 'Tools', 'Everything Doxa can do besides chat.')
    for group, items in groups:
        _section(content, group.upper(), top=12)
        for title, subtitle, action in items:
            def run(action=action):
                window.destroy()
                action()
            card(content, title, subtitle, run, ghost=True).pack(fill='x', pady=1)
    _section(content, 'SYSTEM', top=16)
    for widget in (app.capability_label, app.stats_label, app.growth_label, app.learning_label):
        text = widget.cget('text')
        if text:
            tk.Label(content, text=text, bg=BG, fg=MUTED, font=(BODY, 9), anchor='w', justify='left',
                     padx=12).pack(fill='x', pady=1)
    return window
