from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forgemind.config import app_data_dir


BLOCKED_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".next",
    "dist", "build", "coverage", ".idea", ".vscode",
}
SECRET_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials.json", "service-account.json",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt",
    ".toml", ".yaml", ".yml", ".ini", ".cfg", ".css", ".scss",
    ".html", ".sql", ".ps1", ".bat", ".sh",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _safe_relative(root: Path, path: Path) -> Path:
    relative = path.resolve().relative_to(root.resolve())
    if any(part in BLOCKED_DIRECTORIES for part in relative.parts):
        raise ValueError(f"Blocked project path: {relative.as_posix()}")
    return relative


def _is_secret(relative: Path) -> bool:
    lowered = relative.name.lower()
    return (
        lowered in SECRET_NAMES
        or lowered.startswith(".env.")
        or relative.suffix.lower() in SECRET_SUFFIXES
        or "secret" in lowered
    )


class ProjectWorkspace:
    """Isolated, reviewable project candidates with explicit apply and rollback."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else app_data_dir() / "projects"
        self.candidates = self.root / "candidates"
        self.backups = self.root / "backups"
        self.state_path = self.root / "current.json"
        self.root.mkdir(parents=True, exist_ok=True)

    def _iter_project_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in BLOCKED_DIRECTORIES for part in relative.parts) or _is_secret(relative):
                continue
            files.append(path)
        return sorted(files)

    def repository_map(self, source: Path) -> dict[str, Any]:
        source = Path(source).resolve()
        if not source.is_dir():
            raise FileNotFoundError("The selected project folder does not exist.")
        files = self._iter_project_files(source)
        suffixes: dict[str, int] = {}
        tests = 0
        todos = 0
        for path in files:
            suffix = path.suffix.lower() or "[no extension]"
            suffixes[suffix] = suffixes.get(suffix, 0) + 1
            relative = path.relative_to(source)
            if "test" in path.name.lower() or "tests" in relative.parts:
                tests += 1
            if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 2_000_000:
                text = path.read_text(encoding="utf-8", errors="ignore")
                todos += text.lower().count("todo")
        return {
            "source": str(source),
            "file_count": len(files),
            "test_files": tests,
            "todo_mentions": todos,
            "file_types": dict(sorted(suffixes.items(), key=lambda item: (-item[1], item[0]))[:20]),
            "generated_at": _now(),
        }

    def create_candidate(self, source: Path) -> dict[str, Any]:
        source = Path(source).resolve()
        if not source.is_dir():
            raise FileNotFoundError("The selected project folder does not exist.")
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        candidate = self.candidates / run_id

        def ignore(directory: str, names: list[str]) -> set[str]:
            directory_path = Path(directory)
            ignored: set[str] = set()
            for name in names:
                item = directory_path / name
                try:
                    relative = item.relative_to(source)
                except ValueError:
                    ignored.add(name)
                    continue
                if name in BLOCKED_DIRECTORIES or _is_secret(relative):
                    ignored.add(name)
            return ignored

        candidate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, candidate, ignore=ignore)
        baseline = {
            path.relative_to(source).as_posix(): _digest(path)
            for path in self._iter_project_files(source)
        }
        state = {
            "run_id": run_id,
            "source": str(source),
            "candidate": str(candidate),
            "created_at": _now(),
            "baseline": baseline,
            "checks_passed": False,
            "checks": [],
            "applied": False,
        }
        self._save_state(state)
        return state

    def load_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def changed_files(self) -> list[str]:
        state = self.load_state()
        if not state:
            return []
        source = Path(state["source"])
        candidate = Path(state["candidate"])
        source_files = {p.relative_to(source).as_posix(): p for p in self._iter_project_files(source)}
        candidate_files = {p.relative_to(candidate).as_posix(): p for p in self._iter_project_files(candidate)}
        changed: list[str] = []
        for relative in sorted(source_files.keys() | candidate_files.keys()):
            before = source_files.get(relative)
            after = candidate_files.get(relative)
            if before is None or after is None or _digest(before) != _digest(after):
                changed.append(relative)
        return changed

    def unified_diff(self, max_chars: int = 200_000) -> str:
        state = self.load_state()
        if not state:
            return "No project candidate exists."
        source = Path(state["source"])
        candidate = Path(state["candidate"])
        sections: list[str] = []
        for relative_text in self.changed_files():
            relative = Path(relative_text)
            if relative.suffix.lower() not in TEXT_SUFFIXES:
                sections.append(f"Binary or unsupported text file changed: {relative_text}\n")
                continue
            before_path = source / relative
            after_path = candidate / relative
            before = before_path.read_text(encoding="utf-8", errors="replace").splitlines(True) if before_path.exists() else []
            after = after_path.read_text(encoding="utf-8", errors="replace").splitlines(True) if after_path.exists() else []
            sections.extend(difflib.unified_diff(before, after, f"source/{relative_text}", f"candidate/{relative_text}"))
            if sum(map(len, sections)) >= max_chars:
                sections.append("\n[Diff truncated]\n")
                break
        return "".join(sections) or "No candidate changes yet."

    def suggested_checks(self) -> list[list[str]]:
        state = self.load_state()
        if not state:
            return []
        candidate = Path(state["candidate"])
        checks: list[list[str]] = []
        if any(path.suffix.lower() == ".py" for path in self._iter_project_files(candidate)):
            checks.append([sys.executable, "-m", "compileall", "-q", "."])
            if (candidate / "tests").is_dir():
                checks.append([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
        return checks

    def run_checks(self, commands: list[list[str]] | None = None, timeout: int = 300) -> dict[str, Any]:
        state = self.load_state()
        if not state:
            raise RuntimeError("Create a project candidate first.")
        candidate = Path(state["candidate"])
        commands = commands if commands is not None else self.suggested_checks()
        if not commands:
            result = {"passed": False, "logs": ["No safe automatic checks were detected."]}
            state.update({"checks_passed": False, "checks": result["logs"]})
            self._save_state(state)
            return result
        logs: list[str] = []
        passed = True
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=candidate,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    shell=False,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                log = f"> {' '.join(command)}\n{completed.stdout}\n{completed.stderr}".strip()
                logs.append(log)
                if completed.returncode != 0:
                    passed = False
                    break
            except (OSError, subprocess.TimeoutExpired) as exc:
                logs.append(f"> {' '.join(command)}\n{exc}")
                passed = False
                break
        state.update({"checks_passed": passed, "checks": logs, "checked_at": _now()})
        self._save_state(state)
        return {"passed": passed, "logs": logs}

    def _assert_source_unchanged(self, state: dict[str, Any]) -> None:
        source = Path(state["source"])
        baseline = state.get("baseline", {})
        current = {
            path.relative_to(source).as_posix(): _digest(path)
            for path in self._iter_project_files(source)
        }
        if current != baseline:
            raise RuntimeError("The original project changed after the candidate was created. Create a fresh candidate.")

    def apply_candidate(self, approved: bool = False) -> Path:
        if not approved:
            raise PermissionError("Explicit owner approval is required before applying project changes.")
        state = self.load_state()
        if not state:
            raise RuntimeError("No project candidate exists.")
        if not state.get("checks_passed"):
            raise RuntimeError("The candidate cannot be applied until its checks pass.")
        self._assert_source_unchanged(state)
        changed = self.changed_files()
        if not changed:
            raise RuntimeError("The candidate contains no changes.")
        source = Path(state["source"])
        candidate = Path(state["candidate"])
        backup = self.backups / state["run_id"]
        backup.mkdir(parents=True, exist_ok=False)
        manifest: list[dict[str, Any]] = []
        for relative_text in changed:
            relative = Path(relative_text)
            _safe_relative(source, source / relative)
            if _is_secret(relative):
                raise ValueError(f"Secret files cannot be applied: {relative_text}")
            live = source / relative
            replacement = candidate / relative
            existed = live.exists()
            manifest.append({"path": relative.as_posix(), "existed": existed})
            if existed:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(live, saved)
            if replacement.exists():
                live.parent.mkdir(parents=True, exist_ok=True)
                temporary = live.with_name(live.name + ".forgemind-new")
                shutil.copy2(replacement, temporary)
                os.replace(temporary, live)
            elif live.exists():
                live.unlink()
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        state.update({"applied": True, "applied_at": _now(), "backup": str(backup)})
        self._save_state(state)
        return backup

    def rollback_last(self) -> list[str]:
        backups = sorted((path for path in self.backups.glob("*") if path.is_dir()), reverse=True)
        if not backups:
            raise FileNotFoundError("No project rollback is available.")
        backup = backups[0]
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        state = self.load_state()
        if not state:
            raise RuntimeError("Project state is unavailable.")
        source = Path(state["source"])
        restored: list[str] = []
        for item in manifest:
            relative = Path(item["path"])
            live = source / relative
            saved = backup / relative
            if item.get("existed"):
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, live)
            elif live.exists():
                live.unlink()
            restored.append(relative.as_posix())
        return restored
