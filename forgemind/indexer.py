from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
import zipfile
from xml.etree import ElementTree

from .database import MemoryDB


TEXT_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".csv", ".go", ".h", ".hpp", ".html",
    ".ini", ".java", ".js", ".json", ".jsx", ".kt", ".lua", ".md", ".php", ".ps1",
    ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt", ".xml",
    ".yaml", ".yml", ".log", ".rst",
}
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
SKIP_DIRS = {
    ".git", ".hg", ".idea", ".mypy_cache", ".next", ".pytest_cache", ".venv",
    "__pycache__", "build", "coverage", "dist", "node_modules", "target", "venv",
}
MAX_FILE_BYTES = 32 * 1024 * 1024


def chunk_text(text: str, size: int = 2400, overlap: int = 300) -> list[str]:
    text = text.replace("\x00", "").strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            split = max(text.rfind("\n", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            if split > start:
                end = split
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [c for c in chunks if c]


def iter_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS | OFFICE_EXTENSIONS | {".pdf"}:
            try:
                if path.stat().st_size <= MAX_FILE_BYTES:
                    yield path
            except OSError:
                continue


def read_document(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if path.suffix.lower() in OFFICE_EXTENSIONS:
        return read_office_document(path)
    return path.read_text(encoding="utf-8", errors="replace")


def read_office_document(path: Path) -> str:
    """Extract visible text from modern Office Open XML files without editing the original."""
    suffix = path.suffix.lower()
    prefixes = {
        ".docx": ("word/document.xml", "word/header", "word/footer"),
        ".pptx": ("ppt/slides/slide", "ppt/notesSlides/notesSlide"),
        ".xlsx": ("xl/sharedStrings.xml", "xl/worksheets/sheet"),
    }[suffix]
    sections: list[str] = []
    with zipfile.ZipFile(path) as bundle:
        for name in sorted(bundle.namelist()):
            if not name.endswith(".xml") or not any(name.startswith(prefix) for prefix in prefixes):
                continue
            try:
                root = ElementTree.fromstring(bundle.read(name))
            except ElementTree.ParseError:
                continue
            text = " ".join(piece.strip() for piece in root.itertext() if piece.strip())
            if text:
                sections.append(text)
    return "\n\n".join(sections)


def index_folder(
    db: MemoryDB, root: Path, progress: Callable[[str], None] | None = None
) -> tuple[int, int]:
    indexed = skipped = 0
    seen: set[Path] = set()
    for path in iter_files(root):
        seen.add(path.resolve())
        try:
            stat = path.stat()
            if db.document_is_current(path, stat.st_mtime_ns, stat.st_size):
                skipped += 1
                continue
            if progress:
                progress(str(path.relative_to(root)))
            chunks = chunk_text(read_document(path))
            if chunks:
                db.replace_document(path, stat.st_mtime_ns, stat.st_size, chunks)
                indexed += 1
        except (OSError, ValueError):
            skipped += 1
        except Exception:
            skipped += 1
    db.prune_documents_under(root, seen)
    return indexed, skipped


def index_files(
    db: MemoryDB, paths: list[Path], progress: Callable[[str], None] | None = None
) -> tuple[int, int]:
    """Index explicitly selected files without modifying or pruning their source folders."""
    indexed = skipped = 0
    for path in paths:
        try:
            path = path.resolve()
            if not path.is_file():
                skipped += 1
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS | OFFICE_EXTENSIONS | {".pdf"}:
                skipped += 1
                continue
            stat = path.stat()
            if stat.st_size > MAX_FILE_BYTES or db.document_is_current(path, stat.st_mtime_ns, stat.st_size):
                skipped += 1
                continue
            if progress:
                progress(path.name)
            chunks = chunk_text(read_document(path))
            if not chunks:
                skipped += 1
                continue
            db.replace_document(path, stat.st_mtime_ns, stat.st_size, chunks)
            indexed += 1
        except Exception:
            skipped += 1
    return indexed, skipped
