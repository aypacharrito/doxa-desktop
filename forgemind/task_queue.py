"""Durable local jobs. Expired work requires review, never silent replay."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class TaskQueue:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, tool TEXT NOT NULL, payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                lease TEXT, expires REAL, result TEXT, error TEXT)''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def submit(self, tool, payload, max_attempts=2):
        if not isinstance(tool, str) or not tool.strip() or len(tool) > 80:
            raise ValueError('Invalid tool name')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError('Choose one to three attempts')
        encoded = json.dumps(payload, allow_nan=False)
        if len(encoded) > 16000:
            raise ValueError('Task input exceeds 16000 characters')
        identifier, now = uuid.uuid4().hex, self.clock()
        with self.connection() as db:
            db.execute('INSERT INTO jobs(id,tool,payload,max_attempts,created,updated) VALUES(?,?,?,?,?,?)',
                       (identifier, tool, encoded, max_attempts, now, now))
        return identifier

    def claim(self, lease_seconds=60):
        if not 1 <= lease_seconds <= 300:
            raise ValueError('Lease must be between 1 and 300 seconds')
        now = self.clock()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET state='needs_review',error='Worker interrupted or lease expired',lease=NULL,expires=NULL,updated=? WHERE state='running' AND expires<=?", (now, now))
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND attempts<max_attempts ORDER BY created,rowid LIMIT 1").fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',attempts=attempts+1,lease=?,expires=?,updated=? WHERE id=?", (token, now+lease_seconds, now, row['id']))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())

    def finish(self, identifier, lease, *, result=None, error=None):
        encoded = json.dumps(result, allow_nan=False)
        if len(encoded) > 16000:
            raise ValueError('Task output exceeds 16000 characters')
        now = self.clock()
        with self.connection() as db:
            count = db.execute("UPDATE jobs SET state=?,result=?,error=?,lease=NULL,expires=NULL,updated=? WHERE id=? AND state='running' AND lease=? AND expires>?",
                ('failed' if error is not None else 'succeeded', encoded, str(error)[:500] if error is not None else None, now, identifier, lease, now)).rowcount
            if count != 1:
                raise ValueError('Task lease is no longer valid; result was not accepted')

    def retry(self, identifier):
        with self.connection() as db:
            count = db.execute("UPDATE jobs SET state='queued',result=NULL,error=NULL,updated=? WHERE id=? AND state IN ('failed','needs_review') AND attempts<max_attempts", (self.clock(), identifier)).rowcount
            if count != 1:
                raise ValueError('Task is not retryable or its attempt limit was reached')

    def cancel(self, identifier):
        with self.connection() as db:
            count = db.execute("UPDATE jobs SET state='cancelled',lease=NULL,expires=NULL,updated=? WHERE id=? AND state IN ('queued','running','needs_review','failed')", (self.clock(), identifier)).rowcount
            if count != 1:
                raise ValueError('Task is missing or already finished')

    def recent(self, limit=30):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,tool,state,attempts,max_attempts,created,updated,result,error FROM jobs ORDER BY created DESC,rowid DESC LIMIT ?', (max(1,min(100,limit)),))]

    def get(self, identifier):
        with self.connection() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            return dict(row) if row else None

    def claim_selected(self, identifier, lease_seconds=300):
        if not 1 <= lease_seconds <= 300:
            raise ValueError('Invalid lease duration')
        now, token = self.clock(), uuid.uuid4().hex
        with self.connection() as db:
            count = db.execute("UPDATE jobs SET state='running',attempts=attempts+1,lease=?,expires=?,updated=? WHERE id=? AND state='queued' AND attempts<max_attempts",
                (token,now+lease_seconds,now,identifier)).rowcount
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone()) if count else None

    def recover_expired(self):
        now = self.clock()
        with self.connection() as db:
            return db.execute("UPDATE jobs SET state='needs_review',error='Worker interrupted or lease expired',lease=NULL,expires=NULL,updated=? WHERE state='running' AND expires<=?",(now,now)).rowcount
