from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from .config import app_data_dir


GITHUB_RE = re.compile(
    r"^(?:https?://)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def parse_github_repository(value: str) -> tuple[str, str]:
    match = GITHUB_RE.match(value.strip())
    if not match:
        raise ValueError("Use a repository URL such as https://github.com/owner/project")
    return match.group(1), match.group(2)


def _request(url: str) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Doxa-ReadOnly-Connector",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers, method="GET")


def _extract_repository(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            parts = PurePosixPath(member.filename).parts
            if len(parts) < 2:
                continue
            relative = Path(*parts[1:])
            target = (destination / relative).resolve()
            if destination_root != target and destination_root not in target.parents:
                raise ValueError("Repository archive contained an unsafe path.")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def connect_github_repository(
    repository_url: str,
    *,
    destination_root: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Download a read-only repository snapshot for local indexing; never pushes or mutates GitHub."""
    owner, repository = parse_github_repository(repository_url)
    if progress:
        progress("Reading repository information from GitHub…")
    api_url = f"https://api.github.com/repos/{owner}/{repository}"
    with urllib.request.urlopen(_request(api_url), timeout=30) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    branch = str(metadata.get("default_branch") or "main")
    archive_url = f"https://codeload.github.com/{owner}/{repository}/zip/refs/heads/{branch}"
    root = destination_root or app_data_dir() / "connections" / "github"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = root / f"{owner}-{repository}-{stamp}"
    if progress:
        progress(f"Downloading {owner}/{repository} ({branch})…")
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False, dir=root) as temp:
        archive = Path(temp.name)
    try:
        with urllib.request.urlopen(_request(archive_url), timeout=90) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        if progress:
            progress("Preparing the read-only repository snapshot…")
        _extract_repository(archive, destination)
    finally:
        archive.unlink(missing_ok=True)
    return destination
