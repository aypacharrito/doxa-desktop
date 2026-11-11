from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileReport:
    path: str
    lines: int
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    todos: list[int] = field(default_factory=list)
    error: str | None = None


@dataclass
class ProjectReport:
    root: str
    files: list[FileReport]

    @property
    def total_lines(self) -> int:
        return sum(item.lines for item in self.files)


def analyze_file(path: Path, root: Path) -> FileReport:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        return FileReport(
            path=str(path.relative_to(root)),
            lines=len(text.splitlines()),
            functions=[node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))],
            classes=[node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)],
            todos=[number for number, line in enumerate(text.splitlines(), 1) if "TODO" in line.upper()],
        )
    except (OSError, UnicodeError, SyntaxError) as exc:
        return FileReport(path=str(path.relative_to(root)), lines=0, error=str(exc))


def analyze_project(root: Path) -> ProjectReport:
    root = root.resolve()
    files = [
        analyze_file(path, root)
        for path in sorted(root.rglob("*.py"))
        if ".venv" not in path.parts and "__pycache__" not in path.parts
    ]
    return ProjectReport(root=str(root), files=files)
