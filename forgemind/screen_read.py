"""Fast screen reading: the text of a window through Windows UI Automation (the accessibility tree screen readers use).
No screenshots, no clicks, no typing (the owner 2026-11-09: "make the fast screen read the default whenever I ask what's on
my screen"; Doxa's own upgrade request: "the last read missed numbered list items").

`read_window(app_hint)` picks a window (the named app, e.g. "Claude"/"ChatGPT", otherwise the front-most window that
isn't Doxa itself), fetches its whole accessibility subtree in ONE cached call, then walks it locally in reading order:
inline text runs are joined into lines, every block element (paragraph, list item, heading, cell…) starts a new line,
list items get their number or a bullet, buttons and input boxes are reported separately, and a "Stop" button or a
permission prompt becomes a status line. Typically well under a second.

`screen_question(text)` recognizes "what's on my screen", "read my screen", "what is Claude saying" etc. and returns
the app hint ("" = front window) or None.
"""
from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes

# UIA control type ids
BUTTON, CHECKBOX, EDIT, HYPERLINK, LIST, LISTITEM, TEXT, GROUP, DOCUMENT, PANE, HEADER, TABLE, DATAITEM, TREEITEM, \
    MENUITEM, HEADERITEM, CUSTOM, WINDOW = (50000, 50002, 50004, 50005, 50008, 50007, 50020, 50026, 50030, 50033,
                                             50034, 50036, 50029, 50024, 50011, 50035, 50025, 50032)
INLINE = {TEXT, HYPERLINK}
BLOCKS = {GROUP, LISTITEM, DOCUMENT, PANE, LIST, TABLE, DATAITEM, TREEITEM, HEADER, CUSTOM, WINDOW}
PROPS = {"name": 30005, "type": 30003, "offscreen": 30022, "value": 30045, "class": 30012}
SKIP_TITLES = re.compile(r"^(Doxa|Doxa HQ|Program Manager|Windows Input Experience|)$")
# system overlays that sit "in front" but aren't what the owner is looking at
SKIP_PROCESSES = {"clicktodo.exe", "textinputhost.exe", "shellexperiencehost.exe", "searchhost.exe",
                  "startmenuexperiencehost.exe", "lockapp.exe", "widgets.exe", "nvidia overlay.exe"}
STATUS_BUTTONS = re.compile(r"^(stop|stop generating|stop response|cancel)$", re.I)
PROMPT_BUTTONS = re.compile(r"^(allow|allow once|always allow|deny|approve|reject|yes|no|continue|accept|run|confirm)\b", re.I)
MARKER = re.compile(r"^\s*(?:\d{1,3}[.)]|[•\-–*·▪◦])\s")

ASK = re.compile(
    r"\b(?:what(?:'s| is| does| do)?|read|tell me|show me|look at|check|whats)\b[^.?!]{0,40}?\b(?:my |the )?"
    r"(?:screen|window|laptop|monitor|display)\b"
    r"|\b(?:what(?:'s|s| is)?|read)\b[^.?!]{0,30}?\b(claude|chatgpt|codex|gemini|outlook|chrome|edge|excel|word|teams|slack)"
    r"\b[^.?!]{0,30}?\b(?:say|saying|says|said|wrote|writing|answer|reply|replied|show|showing|on)\b"
    r"|\bread (?:me )?(?:the |my )?(claude|chatgpt|codex|gemini|outlook|chrome|edge|excel|word|teams|slack)\b", re.I)
DOING = re.compile(r"\b(?:click|type|press|open|close|scroll|drag|fill|send|reply|move|install|delete)\b", re.I)


def screen_question(text: str):
    """"" = read the front window, "claude" etc. = that app's window, None = not a screen-reading question.
    Requests to DO something on the screen ("click…", "type…") are left to screen control."""
    text = text or ""
    match = ASK.search(text)
    if not match or DOING.search(text.split("?")[0][:match.start()] + text[match.end():match.end() + 40]):
        return None
    app = next((g for g in match.groups() if g), "")
    return app.lower()


# --- windows ---------------------------------------------------------------------------------------------------------
def _windows():
    """Visible top-level windows, front-most first: (hwnd, title, process name)."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    out = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        cloaked = wintypes.DWORD(0)  # hidden UWP/system windows report visible but are cloaked by the compositor
        if not ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) and cloaked.value:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left < 200 or rect.bottom - rect.top < 150 or SKIP_TITLES.match(title.value):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ""
        handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                name = buf.value.rsplit("\\", 1)[-1].lower()
            kernel32.CloseHandle(handle)
        if (name in ("pythonw.exe", "python.exe") and title.value.startswith("Doxa")) or name in SKIP_PROCESSES:
            return True
        out.append((hwnd, title.value, name))
        return True

    user32.EnumWindows(proto(visit), 0)  # EnumWindows walks top-level windows in z-order (front first)
    return out


def pick_window(app_hint: str = "", windows=None):
    windows = _windows() if windows is None else windows
    if app_hint:
        hint = app_hint.lower()
        for window in windows:
            if hint in window[1].lower() or window[2].startswith(hint):
                return window
        return None
    return windows[0] if windows else None


# --- the accessibility tree --------------------------------------------------------------------------------------
_uia = None


def _automation():
    global _uia
    if _uia is None:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U
        _uia = (comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation), U)
    return _uia


def _tree(hwnd):
    """The whole subtree with names/types/values cached in one cross-process call: [(type, name, value, offscreen, children)]."""
    import comtypes
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except OSError:
        pass
    uia, U = _automation()
    cache = uia.CreateCacheRequest()
    for prop in PROPS.values():
        cache.AddProperty(prop)
    cache.TreeScope = 7  # element + children + descendants
    cache.TreeFilter = uia.RawViewCondition
    root = uia.ElementFromHandleBuildCache(hwnd, cache)

    def node(element, depth=0):
        kids = []
        if depth < 80:
            children = element.GetCachedChildren()
            if children:
                for i in range(children.Length):
                    kids.append(node(children.GetElement(i), depth + 1))
        value = ""
        try:
            value = element.GetCachedPropertyValue(PROPS["value"]) or ""
        except Exception:
            pass
        return (element.CachedControlType, element.CachedName or "", str(value), bool(element.CachedIsOffscreen), kids)

    return node(root)


def flatten(tree):
    """Reading order: (lines, buttons, inputs). Pure function (tests feed it hand-built trees)."""
    lines, buttons, inputs, buffer = [], [], [], []

    def flush(prefix=""):
        text = " ".join("".join(buffer).split())
        buffer.clear()
        if text:
            if prefix and not MARKER.match(text):
                text = prefix + text
            if not lines or lines[-1] != text:
                lines.append(text)

    def walk(item, list_counter=None):
        kind, name, value, offscreen, kids = item
        name = name.strip()
        if kind == BUTTON:
            if name:
                buttons.append(name)
            return
        if kind == EDIT:
            if value.strip():
                inputs.append(value.strip()[:500])
            return
        if kind in INLINE:
            if name and not any(k[0] in INLINE for k in kids):
                buffer.append(name if not buffer or buffer[-1].endswith((" ", "\n")) or name.startswith((" ", ",", ".", ";", ":", ")", "!", "?"))
                              else " " + name)
            for kid in kids:
                walk(kid)
            return
        if kind == LISTITEM:
            flush()
            counter = list_counter if list_counter is not None else [0, False]
            counter[0] += 1
            start = len(lines)
            has_text_kids = any(k[1].strip() or k[4] for k in kids)
            if not has_text_kids and name:
                buffer.append(name)
            for kid in kids:
                walk(kid)
            prefix = f"{counter[0]}. " if counter[1] else "• "
            flush(prefix)
            if len(lines) > start and not MARKER.match(lines[start]):
                lines[start] = prefix + lines[start]
            return
        if kind == LIST:
            flush()
            counter = [0, False]
            # Chromium names ordered lists' markers "1." etc. as text; otherwise guess from the first item's text
            for kid in kids:
                walk(kid, counter)
            flush()
            return
        if kind in BLOCKS or kind == HEADER:
            flush()
            if not kids and name and kind not in (WINDOW, PANE, DOCUMENT):
                buffer.append(name)
            for kid in kids:
                walk(kid, list_counter if kind == GROUP else None)
            flush()
            return
        # anything else (images, separators, menus…): keep a meaningful name as its own line
        if name and kind not in (MENUITEM, HEADERITEM, CHECKBOX) and not kids:
            flush()
            buffer.append(name)
            flush()
        for kid in kids:
            walk(kid)

    walk(tree)
    flush()
    return lines, buttons, inputs


def status_of(buttons):
    if any(STATUS_BUTTONS.match(b) for b in buttons):
        return "Still writing (a Stop button is showing)."
    waiting = [b for b in buttons if PROMPT_BUTTONS.match(b)]
    if waiting:
        return "Waiting for a choice: " + ", ".join(dict.fromkeys(waiting)) + "."
    return "Finished (no Stop button showing)."


def read_window(app_hint: str = "", max_chars: int = 12000, tree_source=None, windows=None) -> dict:
    """Read a window's text. Keeps the END of long windows (the latest messages are at the bottom)."""
    started = time.perf_counter()
    windows = _windows() if windows is None else windows
    window = pick_window(app_hint, windows)
    if window is None:
        raise ValueError(f"No open {app_hint.title()} window found." if app_hint else "No window is open on the screen.")
    candidates = [window] if app_hint else windows[:3]  # front window empty (an overlay)? try the next ones
    for hwnd, title, process in candidates:
        tree = (tree_source or _tree)(hwnd)
        lines, buttons, inputs = flatten(tree)
        if sum(len(l) for l in lines) < 40 and tree_source is None:
            time.sleep(0.4)  # Chromium/Electron apps build their accessibility tree on the first request: ask again
            lines, buttons, inputs = flatten(_tree(hwnd))
        if sum(len(l) for l in lines) >= 40:
            break
    text = "\n".join(lines)
    cut = len(text) > max_chars
    if cut:
        text = "…\n" + text[-max_chars:].split("\n", 1)[-1]
    return {"window": title, "app": process, "text": text, "truncated": cut, "buttons": list(dict.fromkeys(buttons))[:30],
            "inputs": inputs[:5], "status": status_of(buttons), "ms": round((time.perf_counter() - started) * 1000)}


def as_text(result: dict) -> str:
    parts = [f"Window: {result['window']} ({result['app']}), read in {result['ms']} ms through accessibility "
             f"(no screenshot). Status: {result['status']}"]
    if result["inputs"]:
        parts.append("Text typed in its input box: " + " | ".join(result["inputs"]))
    if result["buttons"]:
        parts.append("Buttons: " + ", ".join(result["buttons"][:20]))
    parts.append("Text (in reading order" + (", earlier part cut" if result["truncated"] else "") + "):\n" +
                 (result["text"] or "(this window exposes no text; use control_screen to look at it)"))
    return "\n".join(parts)
