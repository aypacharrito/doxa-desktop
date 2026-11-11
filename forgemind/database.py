from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .config import app_data_dir


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "memory.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self.session() as conn:
            has_memory_index = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='memories_fts' AND type='table'"
            ).fetchone()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learnings (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    modified_ns INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(document_id, ordinal)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    content, content='chunks', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content)
                    VALUES('delete', old.id, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content)
                    VALUES('delete', old.id, old.content);
                    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content, content='memories', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES('delete', old.id, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES('delete', old.id, old.content);
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END;
                """
            )
            if not has_memory_index:
                # Existing pins become searchable once, without rewriting their content or IDs.
                conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")

    def add_message(self, role: str, content: str) -> None:
        with self._lock, self.session() as conn:
            conn.execute(
                "INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)",
                (role, content, utc_now()),
            )

    NEW_CHAT = "[new chat]"

    def recent_messages(self, limit: int = 12) -> list[dict[str, str]]:
        """The latest messages of the current chat (everything after the last "[new chat]" marker)."""
        with self.session() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE id > COALESCE((SELECT MAX(id) FROM messages "
                "WHERE role = 'system' AND content = ?), 0) ORDER BY id DESC LIMIT ?", (self.NEW_CHAT, limit)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def new_chat(self) -> bool:
        """Start a new chat (like ChatGPT/Claude). No-op when the current chat is still empty."""
        with self._lock, self.session() as conn:
            last = conn.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT 1").fetchone()
            if last is None or (last["role"] == "system" and last["content"] == self.NEW_CHAT):
                return False
            conn.execute("INSERT INTO messages(role, content, created_at) VALUES ('system', ?, ?)",
                         (self.NEW_CHAT, utc_now()))
        return True

    def chats(self, limit: int = 40) -> list[dict]:
        """Past chats, newest first: id (the marker before it, 0 for the first), title, time, message count."""
        with self.session() as conn:
            rows = conn.execute("SELECT id, role, content, created_at FROM messages ORDER BY id").fetchall()
        chats, current = [], {"id": 0, "title": "", "updated": "", "count": 0}
        for row in rows:
            if row["role"] == "system" and row["content"] == self.NEW_CHAT:
                if current["count"]:
                    chats.append(current)
                current = {"id": row["id"], "title": "", "updated": row["created_at"], "count": 0}
                continue
            current["count"] += 1
            current["updated"] = row["created_at"]
            if not current["title"] and row["role"] == "user":
                current["title"] = " ".join(str(row["content"]).split())[:80]
        if current["count"]:
            chats.append(current)
        for chat in chats:
            chat["title"] = chat["title"] or "Chat"
        return list(reversed(chats))[:limit]

    def chat_messages(self, chat_id: int, limit: int = 200) -> list[dict[str, str]]:
        """Messages of one past chat (from its marker up to the next one)."""
        with self.session() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE id > ? AND id < COALESCE((SELECT MIN(id) FROM messages "
                "WHERE id > ? AND role = 'system' AND content = ?), 9223372036854775807) AND role != 'system' "
                "ORDER BY id LIMIT ?", (chat_id, chat_id, self.NEW_CHAT, limit)).fetchall()
        return [dict(row) for row in rows]

    def long_messages(self, minimum_chars: int = 12000) -> list[sqlite3.Row]:
        with self.session() as conn:
            return conn.execute(
                "SELECT id, role, content FROM messages WHERE length(content) >= ? ORDER BY id",
                (minimum_chars,),
            ).fetchall()

    def replace_message_content(self, message_id: int, content: str) -> None:
        with self._lock, self.session() as conn:
            conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))

    def clear_messages(self) -> None:
        with self._lock, self.session() as conn:
            conn.execute("DELETE FROM messages")

    def add_memory(self, content: str) -> None:
        content = content.strip()
        if not content:
            return
        with self._lock, self.session() as conn:
            conn.execute(
                "INSERT INTO memories(content, created_at) VALUES (?, ?)",
                (content, utc_now()),
            )

    def list_memories(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.session() as conn:
            return conn.execute(
                "SELECT id, content, created_at FROM memories ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    def delete_memory(self, memory_id: int) -> None:
        with self._lock, self.session() as conn:
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

    def search_memory(self, query: str = "", *, scope: str = "all", limit: int = 60) -> list[dict]:
        """Read local pins and indexed passages, without loading files or invoking a model.

        Words are literal Unicode tokens, combined with AND. The last word is a
        prefix so results remain useful while typing. FTS operators in user text
        are never executed. An empty query browses recent pins and file excerpts.
        """
        if scope not in {"all", "pinned", "files"}:
            raise ValueError("Unknown memory search scope")
        limit = max(1, min(int(limit), 100))
        query = query.strip()[:400]
        words = list(dict.fromkeys(re.findall(r"[^\W_]+", query, re.UNICODE)))[:16]
        if query and not words:
            return []
        expression = " AND ".join('"' + word + '"' for word in words)
        if words and len(words[-1]) > 1:
            expression += "*"
        pins, files = [], []
        with self.session() as conn:
            if scope in {"all", "pinned"}:
                if query:
                    pins = conn.execute(
                        "SELECT m.id, m.content, m.created_at, "
                        "snippet(memories_fts,0,'','',' … ',32) AS excerpt "
                        "FROM memories_fts JOIN memories m ON m.id=memories_fts.rowid "
                        "WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts), m.id DESC LIMIT ?",
                        (expression, limit),
                    ).fetchall()
                else:
                    pins = conn.execute(
                        "SELECT id, content, created_at, substr(content,1,240) AS excerpt "
                        "FROM memories ORDER BY id DESC LIMIT ?", (limit,),
                    ).fetchall()
            if scope in {"all", "files"}:
                if query:
                    files = conn.execute(
                        "SELECT c.id, c.content, c.ordinal, d.path, d.indexed_at, "
                        "snippet(chunks_fts,0,'','',' … ',32) AS excerpt "
                        "FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid "
                        "JOIN documents d ON d.id=c.document_id WHERE chunks_fts MATCH ? "
                        "ORDER BY bm25(chunks_fts), d.id DESC, c.ordinal LIMIT ?",
                        (expression, limit),
                    ).fetchall()
                else:
                    files = conn.execute(
                        "SELECT c.id, c.content, c.ordinal, d.path, d.indexed_at, "
                        "substr(c.content,1,240) AS excerpt FROM documents d "
                        "JOIN chunks c ON c.document_id=d.id AND c.ordinal=0 "
                        "ORDER BY d.indexed_at DESC, d.id DESC LIMIT ?", (limit,),
                    ).fetchall()
        pinned_results = [{"kind": "pinned", "id": row["id"], "source": "Pinned memory",
                           "content": row["content"], "snippet": " ".join(row["excerpt"].split()),
                           "saved_at": row["created_at"], "ordinal": None} for row in pins]
        file_results = [{"kind": "file", "id": row["id"], "source": row["path"],
                         "content": row["content"], "snippet": " ".join(row["excerpt"].split()),
                         "saved_at": row["indexed_at"], "ordinal": row["ordinal"]} for row in files]
        # Separate FTS corpora have incomparable scores. Interleave their ranked
        # results so either source can be discovered before the result cap.
        results = []
        for index in range(max(len(pinned_results), len(file_results))):
            if index < len(pinned_results):
                results.append(pinned_results[index])
            if index < len(file_results):
                results.append(file_results[index])
        return results[:limit]

    def add_learning(
        self,
        content: str,
        *,
        source: str = "conversation",
        kind: str = "observation",
        confidence: float = 0.8,
    ) -> bool:
        content = content.strip()
        if not content:
            return False
        with self._lock, self.session() as conn:
            cursor = conn.execute(
                """
                INSERT INTO learnings(content, source, kind, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(content) DO UPDATE SET
                  source=excluded.source,
                  kind=excluded.kind,
                  confidence=max(learnings.confidence, excluded.confidence),
                  updated_at=excluded.updated_at
                """,
                (content, source, kind, max(0.0, min(1.0, confidence)), utc_now(), utc_now()),
            )
        return cursor.rowcount > 0

    def list_learnings(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.session() as conn:
            return conn.execute(
                "SELECT id, content, source, kind, confidence, updated_at "
                "FROM learnings ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    @staticmethod
    def _terms(query: str) -> list[str]:
        stop = {"the", "and", "for", "that", "this", "with", "from", "what", "how", "can", "you"}
        words = re.findall(r"[A-Za-z0-9_][A-Za-z0-9_.-]{2,}", query.lower())
        return list(dict.fromkeys(w for w in words if w not in stop))[:10]

    def retrieve(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        terms = self._terms(query)
        if not terms:
            return []
        results: list[dict[str, str]] = []
        with self.session() as conn:
            fts_query = " OR ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms)
            try:
                rows = conn.execute(
                    """
                    SELECT d.path, c.content, bm25(chunks_fts) AS score
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    JOIN documents d ON d.id = c.document_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY score LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
                results.extend({"source": row["path"], "content": row["content"]} for row in rows)
            except sqlite3.OperationalError:
                pass

            clauses = " OR ".join("lower(content) LIKE ?" for _ in terms)
            args: list[object] = [f"%{t}%" for t in terms]
            mem_rows = conn.execute(
                f"SELECT content FROM memories WHERE {clauses} ORDER BY id DESC LIMIT ?",  # noqa: S608
                (*args, 3),
            ).fetchall()
            results.extend({"source": "saved memory", "content": row["content"]} for row in mem_rows)
            learning_rows = conn.execute(
                f"SELECT content, kind FROM learnings WHERE {clauses} "  # noqa: S608
                "ORDER BY confidence DESC, id DESC LIMIT ?",
                (*args, 4),
            ).fetchall()
            results.extend(
                {"source": f"learned {row['kind']}", "content": row["content"]}
                for row in learning_rows
            )
            chat_rows = conn.execute(
                f"SELECT role, content FROM messages WHERE {clauses} ORDER BY id DESC LIMIT ?",  # noqa: S608
                (*args, 4),
            ).fetchall()
            results.extend(
                {"source": f"earlier {row['role']} message", "content": row["content"]}
                for row in chat_rows
            )
        return results[: limit + 7]

    def document_is_current(self, path: Path, modified_ns: int, size: int) -> bool:
        with self.session() as conn:
            row = conn.execute(
                "SELECT modified_ns, size FROM documents WHERE path = ?", (str(path),)
            ).fetchone()
        return bool(row and row["modified_ns"] == modified_ns and row["size"] == size)

    def replace_document(
        self, path: Path, modified_ns: int, size: int, chunks: Iterable[str]
    ) -> None:
        with self._lock, self.session() as conn:
            conn.execute(
                """
                INSERT INTO documents(path, modified_ns, size, indexed_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET modified_ns=excluded.modified_ns,
                  size=excluded.size, indexed_at=excluded.indexed_at
                """,
                (str(path), modified_ns, size, utc_now()),
            )
            doc_id = conn.execute("SELECT id FROM documents WHERE path = ?", (str(path),)).fetchone()[0]
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
            conn.executemany(
                "INSERT INTO chunks(document_id, ordinal, content) VALUES (?, ?, ?)",
                ((doc_id, i, chunk) for i, chunk in enumerate(chunks)),
            )

    def prune_documents_under(self, root: Path, current_paths: set[Path]) -> int:
        """Remove indexed documents that no longer exist beneath a synchronized root."""
        root = root.resolve()
        current = {path.resolve() for path in current_paths}
        stale_ids: list[int] = []
        with self.session() as conn:
            rows = conn.execute("SELECT id, path FROM documents").fetchall()
            for row in rows:
                path = Path(row["path"]).resolve()
                if (path == root or root in path.parents) and path not in current:
                    stale_ids.append(row["id"])
            conn.executemany("DELETE FROM documents WHERE id = ?", ((item,) for item in stale_ids))
        return len(stale_ids)

    def counts(self) -> dict[str, int]:
        with self.session() as conn:
            return {
                "messages": conn.execute("SELECT count(*) FROM messages").fetchone()[0],
                "memories": conn.execute("SELECT count(*) FROM memories").fetchone()[0],
                "learnings": conn.execute("SELECT count(*) FROM learnings").fetchone()[0],
                "documents": conn.execute("SELECT count(*) FROM documents").fetchone()[0],
                "chunks": conn.execute("SELECT count(*) FROM chunks").fetchone()[0],
            }

    def backup_to(self, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = destination / f"forgemind-memory-{stamp}.sqlite3"
        with self._lock, self.session() as source, closing(sqlite3.connect(target)) as target_conn:
            source.backup(target_conn)
        backups = sorted(destination.glob("forgemind-memory-*.sqlite3"), reverse=True)
        for old in backups[10:]:
            old.unlink(missing_ok=True)
        return target
