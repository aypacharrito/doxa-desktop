"""Wrap a secret so only this computer's account can read it back.

Windows: account-bound DPAPI (unchanged). Mac / Linux: the secret goes into the system keychain (macOS Keychain via
`keyring`) and the file only keeps a reference, so callers can keep writing "encrypted" bytes to disk as before.
"""
import base64
import os
import secrets

SERVICE = "Doxa Vault"
MARK = b"KEYRING:"


if os.name == "nt":
    import ctypes
    from ctypes import wintypes


    def windows_key(data: bytes, encrypt: bool) -> bytes:
        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        source = Blob(len(data), buffer)
        output = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        proc = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
        proc.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        proc.restype = wintypes.BOOL
        if not proc(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise RuntimeError('The Windows account could not unlock the local connection vault.')
        try:
            return ctypes.string_at(output.data, output.size)
        finally:
            kernel.LocalFree(output.data)


def keychain_key(data: bytes, encrypt: bool) -> bytes:
    """Mac / Linux: keep the secret in the system keychain; return a reference to store on disk."""
    import keyring
    if encrypt:
        ref = secrets.token_hex(16)
        keyring.set_password(SERVICE, ref, base64.b64encode(data).decode("ascii"))
        return MARK + ref.encode("ascii")
    if not data.startswith(MARK):
        raise RuntimeError("This secret was saved on another computer; add it again in Settings.")
    value = keyring.get_password(SERVICE, data[len(MARK):].decode("ascii", "replace"))
    if value is None:
        raise RuntimeError("The keychain no longer has this secret; add it again in Settings.")
    return base64.b64decode(value)


if os.name != "nt":
    windows_key = keychain_key
