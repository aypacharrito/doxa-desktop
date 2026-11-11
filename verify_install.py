from __future__ import annotations

from forgemind.runtime import prepare_windows_dlls


paths = prepare_windows_dlls()
from llama_cpp import Llama  # noqa: E402,F401
import ddgs  # noqa: E402,F401
import pypdf  # noqa: E402,F401

print("Doxa engine verified.")
if paths:
    print("Registered runtime folders:")
    for path in paths:
        print(f"  {path}")
