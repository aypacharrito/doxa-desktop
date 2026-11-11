"""Model boundary for local chat and drafts, with content-free measurements."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
import sqlite3
import time
import uuid


class TextProvider(Protocol):
    provider_id: str
    local: bool

    @property
    def loaded(self) -> bool: ...

    @property
    def model_name(self) -> str: ...

    def stream(self, history, text, settings, memories, web, stop_event=None) -> Iterator[str]: ...


class LlamaCppProvider:
    provider_id = 'llama.cpp'
    local = True

    def __init__(self, engine):
        self.engine = engine

    @property
    def loaded(self):
        return self.engine.loaded

    @property
    def model_name(self):
        return self.engine.model_name

    def stream(self, history, text, settings, memories, web, stop_event=None):
        return self.engine.stream(history, text, settings, memories, web, stop_event=stop_event)


class ModelUsage:
    """Metadata only: no prompt, response, memory, file paths or raw errors."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS model_calls (
                id TEXT PRIMARY KEY, started REAL NOT NULL, provider TEXT NOT NULL,
                model TEXT NOT NULL, state TEXT NOT NULL, elapsed_ms INTEGER,
                first_text_ms INTEGER, output_chars INTEGER NOT NULL DEFAULT 0,
                api_cost_usd REAL NOT NULL DEFAULT 0)''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def start(self, provider, model):
        identifier = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO model_calls(id,started,provider,model,state) VALUES(?,?,?,?,?)',
                       (identifier, time.time(), provider, Path(model).name, 'running'))
        return identifier

    def finish(self, identifier, state, elapsed, first, chars):
        with self.connect() as db:
            db.execute('UPDATE model_calls SET state=?,elapsed_ms=?,first_text_ms=?,output_chars=? WHERE id=?',
                       (state, round(elapsed*1000), None if first is None else round(first*1000), chars, identifier))

    def recent(self, limit=12):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM model_calls ORDER BY started DESC, rowid DESC LIMIT ?', (limit,))]

    def recover(self):
        # Called once at app startup: interrupted generations are not replayed.
        with self.connect() as db:
            db.execute("UPDATE model_calls SET state='interrupted' WHERE state='running'")


class LocalInference:
    """Explicit local route. Unsupported providers fail without cloud fallback."""
    def __init__(self, provider: TextProvider, usage: ModelUsage):
        if not provider.local:
            raise ValueError('This installation uses local inference only')
        self.provider, self.usage = provider, usage

    @property
    def loaded(self):
        return self.provider.loaded

    @property
    def model_name(self):
        return self.provider.model_name

    def stream(self, history, text, settings, memories, web, stop_event=None):
        if not self.provider.local:
            raise ValueError('Local-only policy rejects this provider')
        identifier = self.usage.start(self.provider.provider_id, self.model_name)
        started, first, chars, state = time.monotonic(), None, 0, 'interrupted'
        response = None
        try:
            if stop_event is not None and stop_event.is_set():
                state = 'stopped'
                return
            if not self.loaded:
                raise RuntimeError('Load the local model first')
            response = iter(self.provider.stream(history, text, settings, memories, web, stop_event=stop_event))
            for chunk in response:
                if stop_event is not None and stop_event.is_set():
                    state = 'stopped'
                    return
                if chunk:
                    if first is None:
                        first = time.monotonic()-started
                    chars += len(chunk)
                    yield chunk
            state = 'stopped' if stop_event is not None and stop_event.is_set() else 'generated' if chars else 'empty'
        except Exception:
            state = 'error'
            raise
        finally:
            try:
                if response is not None and hasattr(response, 'close'):
                    response.close()
            finally:
                self.usage.finish(identifier, state, time.monotonic()-started, first, chars)
