"""Show a web page *inside* a Tk frame on Windows (the owner 2026-11-08: the 3D team should be in Doxa, not a separate
window). Tk can't render modern HTML, so Doxa starts Microsoft Edge in app mode with its own small profile, finds that
window and makes it a child of the frame (Win32 SetParent), resized with the frame. If anything fails, the page simply
stays a normal window (the caller is told through `on_state`).
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

GWL_STYLE = -16
WS_CHILD, WS_POPUP, WS_CAPTION, WS_THICKFRAME = 0x40000000, 0x80000000, 0x00C00000, 0x00040000
WS_SYSMENU, WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_VISIBLE = 0x00080000, 0x00020000, 0x00010000, 0x10000000
SWP_NOZORDER, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0004, 0x0020, 0x0040
EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")


def edge_path() -> str | None:
    return shutil.which("msedge") or next((p for p in EDGE_PATHS if Path(p).is_file()), None)


def _user32():
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetParent.restype = wintypes.HWND
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    return user32


def find_window(title_part: str, pids=None, timeout: float = 20.0, stop=None) -> int | None:
    """Top-level window whose title contains `title_part` (a Chromium window, preferably from one of `pids`)."""
    if sys.platform != "win32":
        return None
    user32 = _user32()
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not (stop and stop.is_set()):
        found = []

        def visit(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if title_part in buffer.value:
                    klass = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(hwnd, klass, 64)
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if klass.value.startswith("Chrome_WidgetWin"):
                        found.append((0 if pids and pid.value in pids else 1, hwnd))
            return True
        user32.EnumWindows(proto(visit), 0)
        if found:
            return sorted(found)[0][1]
        time.sleep(0.25)
    return None


class EmbeddedPage:
    """One Edge app window living inside `frame`. `on_state(text)` reports "starting", "embedded" or a problem."""

    def __init__(self, frame, url: str, profile_dir: Path, title: str = "Doxa HQ", on_state=None):
        self.frame, self.url, self.profile_dir, self.title = frame, url, Path(profile_dir), title
        self.on_state = on_state or (lambda text: None)
        self.process = None
        self.hwnd = None
        self._stop = threading.Event()

    @property
    def embedded(self) -> bool:
        return bool(self.hwnd) and sys.platform == "win32" and bool(_user32().IsWindow(self.hwnd))

    def start(self) -> bool:
        edge = edge_path()
        if sys.platform != "win32" or not edge:
            self.on_state("Microsoft Edge wasn't found, so the 3D team can't be shown inside Doxa.")
            return False
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        end_profile_processes(self.profile_dir)  # a leftover HQ from a crash would hijack the new launch
        # Kiosk = no title bar or browser frame at all (an app window keeps Edge's own caption even as a child).
        args = [edge, "--kiosk", self.url, "--edge-kiosk-type=fullscreen", f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check", "--disable-sync", "--window-position=-3000,-3000", "--window-size=1200,800",
                "--disable-features=msEdgeSidebarV2,Translate,msUndersideButton"]
        try:
            self.process = subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.on_state(f"Couldn't start Edge for the 3D team: {exc}")
            return False
        self.on_state("starting")
        threading.Thread(target=self._wait, daemon=True, name="doxa-embed").start()
        return True

    def _wait(self):
        hwnd = find_window(self.title, pids={self.process.pid} if self.process else None, stop=self._stop)
        if self._stop.is_set():
            return
        try:
            self.frame.after(0, lambda: self._attach(hwnd))
        except RuntimeError:  # Tk is gone
            pass

    def _attach(self, hwnd):
        if not hwnd:
            self.on_state("The 3D team opened in its own window (Doxa couldn't place it inside).")
            return
        user32 = _user32()
        parent = self.frame.winfo_id()
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        style |= WS_CHILD | WS_VISIBLE
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        user32.SetParent(hwnd, parent)
        self.hwnd = hwnd
        self.resize()
        self.frame.bind("<Configure>", lambda _e: self.resize(), add="+")
        self.on_state("embedded")

    def resize(self):
        if not self.hwnd:
            return
        width, height = max(1, self.frame.winfo_width()), max(1, self.frame.winfo_height())
        _user32().SetWindowPos(self.hwnd, None, 0, 0, width, height, SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)

    def close(self):
        """End the HQ's Edge for real. Edge's starter process exits at once and hands off to another process, so the
        Popen pid alone isn't enough (that left a full-screen HQ behind after Doxa closed): end everything that was
        started with Doxa's own HQ profile."""
        self._stop.set()
        end_profile_processes(self.profile_dir)
        self.process, self.hwnd = None, None


def end_profile_processes(profile: Path) -> None:
    """Stop every msedge.exe started with this (Doxa-only) profile folder, including orphans from a crash."""
    if sys.platform != "win32":
        return
    profile = Path(profile).resolve()
    if profile.name.lower() != "hq-browser":
        return  # Never terminate a normal browser profile.
    needle = str(profile).lower().replace("'", "''")
    script = ("$n = '" + needle + "'; Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
              "Where-Object { $_.CommandLine -and "
              "$_.CommandLine -match '--user-data-dir=(?:\"([^\"]+)\"|([^\\s]+))' -and "
              "(($matches[1] + $matches[2]).TrimEnd('\\').ToLower() -eq $n) } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def profile_dir(data_dir) -> Path:
    return Path(data_dir) / "hq-browser"
