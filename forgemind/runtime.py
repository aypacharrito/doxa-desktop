from __future__ import annotations

import os
import site
from pathlib import Path


_DLL_HANDLES: list[object] = []
_DLL_PATHS: set[str] = set()


def prepare_windows_dlls() -> list[Path]:
    """Make pip-installed NVIDIA runtime DLLs visible to Windows' loader."""
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return []
    candidates: list[Path] = []
    for root_text in site.getsitepackages():
        root = Path(root_text)
        candidates.extend(
            [
                root / "nvidia" / "cuda_runtime" / "bin",
                root / "nvidia" / "cublas" / "bin",
                root / "llama_cpp" / "lib",
            ]
        )
    added: list[Path] = []
    for path in candidates:
        key = str(path).lower()
        if path.is_dir() and key not in _DLL_PATHS:
            _DLL_HANDLES.append(os.add_dll_directory(str(path)))
            os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")
            added.append(path)
            _DLL_PATHS.add(key)
    return added
