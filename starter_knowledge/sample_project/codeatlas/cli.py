from __future__ import annotations

import argparse
from pathlib import Path

from .analyzer import analyze_project


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a Python project")
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    report = analyze_project(args.folder)
    print(f"Project: {report.root}")
    print(f"Files: {len(report.files)} | Lines: {report.total_lines}")
    for item in report.files:
        status = f"error: {item.error}" if item.error else f"{len(item.functions)} functions, {len(item.classes)} classes"
        print(f"- {item.path}: {status}")


if __name__ == "__main__":
    main()
