"""Give Doxa's window its own taskbar identity, so pinning it shows the Doxa icon and relaunches Doxa.

Without this, Windows sees the running program (pythonw.exe): a pinned Doxa showed the Python icon and
the pin would have started bare Python. Windows reads these window properties when the owner pins:
  System.AppUserModel.ID                           -> "Doxa.Desktop" (same as the process ID)
  System.AppUserModel.RelaunchCommand              -> "...pythonw.exe" "...app.py"
  System.AppUserModel.RelaunchDisplayNameResource  -> "Doxa"
  System.AppUserModel.RelaunchIconResource         -> "...doxa.ico,0"
Plain ctypes (no pywin32 in the runtime). Every failure is ignored: the app works without it.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

APP_ID = "Doxa.Desktop"
_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"  # PKEY_AppUserModel_*
_PID = {"RelaunchCommand": 2, "RelaunchIconResource": 3, "RelaunchDisplayNameResource": 4, "ID": 5}
VT_LPWSTR = 31


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        guid = cls()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
        return guid


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


LAUNCHER = "doxa_launcher.pyw"   # in %LOCALAPPDATA%\Programs\Jarvis, opens the version named in current.txt
STABLE_ICON = "doxa.ico"         # copy beside the launcher, so pins survive upgrades


def _app_py(app_py: Path | None) -> Path:
    return Path(app_py) if app_py else Path(__file__).resolve().parent.parent / "app.py"


def relaunch_command(app_py: Path | None = None) -> str:
    """The command a pinned Doxa runs: the stable launcher if installed, else this version's app.py."""
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    if windowless.is_file():
        exe = windowless
    script = _app_py(app_py)
    launcher = script.parent.parent / LAUNCHER
    return f'"{exe}" "{launcher if launcher.is_file() else script}"'


def stable_icon(icon: Path, app_py: Path | None = None) -> Path:
    candidate = _app_py(app_py).parent.parent / STABLE_ICON
    return candidate if candidate.is_file() else Path(icon)


def window_properties(icon: Path, app_py: Path | None = None) -> dict[str, str]:
    return {"ID": APP_ID, "RelaunchCommand": relaunch_command(app_py),
            "RelaunchDisplayNameResource": "Doxa", "RelaunchIconResource": f"{stable_icon(icon, app_py)},0"}


def apply_to_window(hwnd: int, icon: Path, app_py: Path | None = None) -> bool:
    """Set the taskbar identity properties on a top-level window. Returns True on success."""
    if sys.platform != "win32" or not hwnd or not Path(icon).is_file():
        return False
    try:
        store = ctypes.c_void_p()
        iid = GUID.parse("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")  # IPropertyStore
        ctypes.oledll.shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(iid), ctypes.byref(store))
        vtable = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        set_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtable[6])
        commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        fmtid = GUID.parse(_FMTID)
        try:
            # The ID must be set last-but-not-first per Windows docs: relaunch values, then the ID.
            values = window_properties(Path(icon), app_py)
            for name in ("RelaunchCommand", "RelaunchIconResource", "RelaunchDisplayNameResource", "ID"):
                key = PROPERTYKEY(fmtid, _PID[name])
                value = PROPVARIANT(vt=VT_LPWSTR, pwszVal=values[name])
                set_value(store, ctypes.byref(key), ctypes.byref(value))
            commit(store)
        finally:
            release(store)
        return True
    except OSError:
        return False


def read_window_property(hwnd: int, name: str) -> str:
    """Read one of the properties back (used by tests and diagnostics)."""
    store = ctypes.c_void_p()
    iid = GUID.parse("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    ctypes.oledll.shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(iid), ctypes.byref(store))
    vtable = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    get_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                   ctypes.POINTER(PROPVARIANT))(vtable[5])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    try:
        value = PROPVARIANT()
        get_value(store, ctypes.byref(PROPERTYKEY(GUID.parse(_FMTID), _PID[name])), ctypes.byref(value))
        return value.pwszVal or "" if value.vt == VT_LPWSTR else ""
    finally:
        release(store)


def _file_store(path: Path, writable: bool):
    store = ctypes.c_void_p()
    iid = GUID.parse("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    ctypes.oledll.shell32.SHGetPropertyStoreFromParsingName(ctypes.c_wchar_p(str(path)), None,
                                                            2 if writable else 0, ctypes.byref(iid),
                                                            ctypes.byref(store))
    vtable = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    return store, vtable


def set_shortcut_app_id(lnk: Path, app_id: str = APP_ID) -> bool:
    """Stamp a .lnk with Doxa's AppUserModelID so Windows groups and pins it as Doxa."""
    if sys.platform != "win32" or not Path(lnk).is_file():
        return False
    ctypes.windll.ole32.CoInitialize(None)
    try:
        store, vtable = _file_store(Path(lnk), True)
        set_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtable[6])
        commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        try:
            set_value(store, ctypes.byref(PROPERTYKEY(GUID.parse(_FMTID), _PID["ID"])),
                      ctypes.byref(PROPVARIANT(vt=VT_LPWSTR, pwszVal=app_id)))
            commit(store)
        finally:
            release(store)
        return shortcut_app_id(lnk) == app_id
    except OSError:
        return False


def shortcut_app_id(lnk: Path) -> str:
    ctypes.windll.ole32.CoInitialize(None)
    store, vtable = _file_store(Path(lnk), False)
    get_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                   ctypes.POINTER(PROPVARIANT))(vtable[5])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    try:
        value = PROPVARIANT()
        get_value(store, ctypes.byref(PROPERTYKEY(GUID.parse(_FMTID), _PID["ID"])), ctypes.byref(value))
        return value.pwszVal or "" if value.vt == VT_LPWSTR else ""
    finally:
        release(store)
