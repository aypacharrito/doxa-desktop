"""Durable, bounded architecture experiments; never replaces the chat model."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from .config import app_data_dir
from .growth import _alive


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def starter_corpus() -> bytes:
    """Original synthetic code examples, not downloaded proprietary training data."""
    examples = []
    for index in range(600):
        name = ("total", "count", "price", "score", "size", "value")[index % 6]
        examples.append(
            f"# Example {index}: validate and calculate {name}\n"
            f"def calculate_{name}_{index}(items, factor={index % 11 + 1}):\n"
            "    if not isinstance(items, list):\n"
            "        raise TypeError('items must be a list')\n"
            "    return sum(items) * factor\n\n"
            f"assert calculate_{name}_{index}([1, 2, 3], 2) == 12\n\n"
        )
    return "".join(examples).encode("utf-8")


def validate_spec(spec: dict) -> dict:
    allowed = {"family", "width", "layers", "heads", "learning_rate", "order"}
    if not isinstance(spec, dict) or set(spec) - allowed:
        raise ValueError("A candidate must use the registered experiment fields.")
    family = spec.get("family")
    if family not in {"gru", "transformer", "ngram"}:
        raise ValueError("Unknown architecture; add a tested worker adapter before using it.")
    if family == "ngram":
        order = spec.get("order", 3)
        if type(order) is not int or order not in (1, 2, 3, 4):
            raise ValueError("N-gram order must be 1–4.")
        return {"family": family, "order": order}
    width, layers, heads = spec.get("width", 64), spec.get("layers", 1), spec.get("heads", 4)
    rate = spec.get("learning_rate", 0.003)
    if type(width) is not int or width not in (32, 64, 96, 128):
        raise ValueError("Width must be a registered 32–128 setting.")
    if type(layers) is not int or layers not in (1, 2, 3):
        raise ValueError("Layer count must be 1–3.")
    if type(heads) is not int or heads not in (1, 2, 4) or width % heads:
        raise ValueError("Attention heads must divide the width.")
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 0.0001 <= rate <= 0.02:
        raise ValueError("Learning rate must be finite and within the experiment space.")
    return dict(family=family, width=width, layers=layers, heads=heads, learning_rate=rate)


class ResearchLab:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else app_data_dir() / "research_lab"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "experiments.sqlite3"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs(
                    id INTEGER PRIMARY KEY, corpus TEXT NOT NULL, spec TEXT NOT NULL,
                    seed INTEGER NOT NULL, parent INTEGER, status TEXT NOT NULL,
                    created REAL NOT NULL, result TEXT, owner_pid INTEGER);
                CREATE TABLE IF NOT EXISTS session(
                    id INTEGER PRIMARY KEY CHECK(id=1), owner_pid INTEGER);
                INSERT OR IGNORE INTO session VALUES(1,NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def acquire(self) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute("SELECT owner_pid FROM session WHERE id=1").fetchone()[0]
            workers = db.execute("SELECT owner_pid FROM runs WHERE status='running'").fetchall()
            if (owner and _alive(owner)) or any(_alive(row[0] or 0) for row in workers):
                raise RuntimeError("A research session is already active. Stop that session first.")
            db.execute("UPDATE session SET owner_pid=? WHERE id=1", (os.getpid(),))

    def release(self) -> None:
        with self.connection() as db:
            db.execute("UPDATE session SET owner_pid=NULL WHERE id=1 AND owner_pid=?", (os.getpid(),))

    def corpus(self, source: Path | None = None) -> str:
        if source and (not source.is_file() or source.stat().st_size > 16 * 1024 * 1024):
            raise ValueError("Choose a text corpus no larger than 16 MB for this prototype.")
        data = source.read_bytes() if source else starter_corpus()
        if len(data) < 4096:
            raise ValueError("Use at least 4 KB of training text so all three splits are usable.")
        digest = hashlib.sha256(data).hexdigest()
        folder = self.root / "corpora"
        folder.mkdir(exist_ok=True)
        path = folder / (digest + ".txt")
        if not path.exists():
            path.write_bytes(data)
        return digest

    def run_dir(self, identifier: int) -> Path:
        if type(identifier) is not int or identifier <= 0:
            raise ValueError("Invalid experiment ID.")
        return self.root / "runs" / f"{identifier:06d}"

    def runs(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
        records = []
        for row in rows:
            item = dict(row)
            item["spec"] = json.loads(item["spec"])
            item["result"] = json.loads(item["result"]) if item["result"] else {}
            records.append(item)
        return records

    def recover(self) -> None:
        for run in self.runs():
            if run["status"] == "running" and not _alive(run["owner_pid"] or 0):
                result_path = self.run_dir(run["id"]) / "result.json"
                if result_path.exists():
                    self.finish(run["id"], json.loads(result_path.read_text(encoding="utf-8")))
                else:
                    self.finish(run["id"], {"status": "paused", "error": "Worker interrupted; resume its checkpoint."})

    def propose(self, digest: str) -> tuple[dict, int | None]:
        """Reproducible evolutionary search over a typed, finite research space."""
        records = [run for run in self.runs() if run["corpus"] == digest]
        family = ("ngram", "gru", "transformer")[len(records) % 3]
        rng = random.Random(9173 + len(records))
        winners = [run for run in records if run["status"] == "completed"
                   and run["spec"]["family"] == family and "validation_nll" in run["result"]]
        winner = min(winners, key=lambda run: run["result"]["validation_nll"]) if winners else None
        parent = None
        if winner and rng.random() < 0.7:
            spec, parent = dict(winner["spec"]), winner["id"]
        elif family == "ngram":
            spec = {"family": family, "order": 2}
        else:
            spec = dict(family=family, width=64, layers=1, heads=4, learning_rate=0.003)
        key = rng.choice(["width", "layers", "learning_rate"]) if family != "ngram" else "order"
        choices = {"width": [32, 64, 96, 128], "layers": [1, 2, 3],
                   "learning_rate": [0.001, 0.003, 0.006], "order": [1, 2, 3, 4]}
        spec[key] = rng.choice(choices[key])
        return validate_spec(spec), parent

    def create(self, digest: str, spec: dict, *, steps: int = 300, seconds: int = 60,
               device: str = "cuda", parent: int | None = None) -> int:
        if device not in {"cpu", "cuda"} or type(steps) is not int or not 1 <= steps <= 100000:
            raise ValueError("Choose CPU or CUDA and a positive training step budget.")
        if type(seconds) is not int or not 1 <= seconds <= 86400:
            raise ValueError("Set a per-trial time budget of 1–86400 seconds.")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Invalid dataset fingerprint.")
        corpus = self.root / "corpora" / (digest + ".txt")
        if not corpus.is_file() or hashlib.sha256(corpus.read_bytes()).hexdigest() != digest:
            raise ValueError("The dataset snapshot is missing or changed.")
        spec = validate_spec(spec)
        lineage = {}
        if parent is not None and spec['family'] != 'ngram':
            previous = next((run for run in self.runs() if run['id'] == parent), None)
            if not previous or previous['status'] != 'completed' or previous['corpus'] != digest or previous['spec']['family'] != spec['family']:
                raise ValueError('A parent must be a completed neural candidate from this dataset and family.')
            weights = self.run_dir(parent) / 'weights.pt'
            if not weights.is_file():
                raise ValueError('Parent weights are missing.')
            lineage = {'parent_checkpoint': str(weights.resolve()), 'parent_sha256': hashlib.sha256(weights.read_bytes()).hexdigest()}
        with self.connection() as db:
            cursor = db.execute("INSERT INTO runs(corpus,spec,seed,parent,status,created) VALUES(?,?,?,?,?,?)",
                                (digest, json.dumps(spec), 1234, parent, "queued", time.time()))
            identifier = cursor.lastrowid
            db.execute("UPDATE runs SET seed=? WHERE id=?", (1234 + identifier, identifier))
        folder = self.run_dir(identifier)
        folder.mkdir(parents=True)
        atomic_json(folder / "job.json", dict(id=identifier, corpus=str(corpus.resolve()), digest=digest,
            spec=spec, seed=1234 + identifier, steps=steps, seconds=seconds, device=device,
            protocol="byte-lm-v1", sequence_length=48, batch_size=16, **lineage))
        return identifier

    def finish(self, identifier: int, result: dict) -> None:
        status = result.get("status")
        if status not in {"completed", "paused", "error"}:
            raise ValueError("A worker must report a real completion, pause, or error.")
        if status == "completed":
            if any(type(result.get(key)) not in (int, float) or not math.isfinite(result[key])
                   or result[key] < 0 for key in ("validation_nll", "elapsed_seconds", "parameters")):
                raise ValueError("A completed experiment needs finite measured metrics.")
            checkpoint = result.get("checkpoint", "missing")
            if checkpoint not in {"weights.pt", "ngram.json"} or not (self.run_dir(identifier) / checkpoint).is_file():
                raise ValueError("A completed experiment needs its saved checkpoint.")
        with self.connection() as db:
            db.execute("UPDATE runs SET status=?,result=?,owner_pid=NULL WHERE id=?",
                       (status, json.dumps(result, allow_nan=False), identifier))


class LabSession:
    """One trusted worker process at a time; process isolation is NOT a security sandbox."""
    def __init__(self, lab: ResearchLab, digest: str, *, continuous: bool = False,
                 steps: int = 300, seconds: int = 60, device: str = "cuda", resume_id: int | None = None,
                 audit_id: int | None = None, background: bool = False, cooldown_seconds: int = 5):
        lab.acquire()
        self.lab, self.digest = lab, digest
        self.continuous, self.steps, self.seconds, self.device = continuous, steps, seconds, device
        self.background = background
        self.cooldown_seconds = max(5, min(3600, cooldown_seconds))
        self.process = None
        self.log = None
        self.identifier = None
        self.stopping_at = None
        self.active = True
        self.message = "Research session starting"
        self.resume_id = resume_id
        self.audit_id = audit_id
        self._next_at = 0.0

    def stop(self):
        if self.stopping_at is None:
            self.stopping_at = time.monotonic()
        if self.identifier:
            (self.lab.run_dir(self.identifier) / "STOP").touch()

    def _launch(self):
        if self.background:
            if sum(path.stat().st_size for path in (self.lab.root/'runs').glob('*/*') if path.is_file()) > 512*1024**2:
                raise RuntimeError('Learning paused: its 512 MB experiment budget is full. Saved results are preserved.')
            if os.name == 'nt':
                import ctypes
                class MemoryStatus(ctypes.Structure):
                    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),
                              ('available',ctypes.c_ulonglong),('page',ctypes.c_ulonglong),('page_available',ctypes.c_ulonglong),
                              ('virtual',ctypes.c_ulonglong),('virtual_available',ctypes.c_ulonglong),('extended',ctypes.c_ulonglong)]
                memory=MemoryStatus();memory.length=ctypes.sizeof(memory)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)) and memory.available < 1536*1024**2:
                    self.message='Waiting for RAM · chat stays available; checking again in one minute'
                    self._next_at=time.monotonic()+60
                    return
        if shutil.disk_usage(self.lab.root).free < 1024 ** 3:
            raise RuntimeError("Less than 1 GB free space; make room before another experiment.")
        if self.audit_id:
            self.identifier = self.audit_id
            run = next((run for run in self.lab.runs() if run["id"] == self.identifier), None)
            if not run or run["status"] != "completed" or run["corpus"] != self.digest:
                raise ValueError("Select a completed run from this dataset to audit.")
        elif self.resume_id:
            self.identifier, self.resume_id = self.resume_id, None
            run = next((run for run in self.lab.runs() if run["id"] == self.identifier), None)
            if not run or run["status"] != "paused" or run["corpus"] != self.digest:
                raise ValueError("Select a paused run from this dataset to resume.")
        else:
            spec, parent = self.lab.propose(self.digest)
            self.identifier = self.lab.create(self.digest, spec, steps=self.steps, seconds=self.seconds,
                                               device=self.device, parent=parent)
        folder = self.lab.run_dir(self.identifier)
        # These are only our generated per-run control/output files, never owner sources.
        for name in ("STOP", "audit.json" if self.audit_id else "result.json"):
            (folder / name).unlink(missing_ok=True)
        self.log = (folder / "worker.log").open("a", encoding="utf-8")
        env = dict(os.environ, CUBLAS_WORKSPACE_CONFIG=":4096:8", PYTHONUNBUFFERED="1",
                   FORGEMIND_RESEARCH_THREADS='1' if self.background else '4')
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        command = [sys.executable, "-m", "forgemind.lab_worker", str(folder / "job.json")]
        if self.audit_id:
            command.append("--audit")
        self.process = subprocess.Popen(command,
            cwd=Path(__file__).resolve().parents[1], env=env, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=flags)
        if not self.audit_id:
            with self.lab.connection() as db:
                db.execute("UPDATE runs SET status='running',owner_pid=? WHERE id=?",
                           (self.process.pid, self.identifier))

    def tick(self):
        if not self.active:
            return
        try:
            if self.process is None:
                if self.stopping_at is not None:
                    return self.close()
                if time.monotonic() < self._next_at:
                    return
                self._launch()
                if self.process is None:
                    return
            if self.process.poll() is None:
                if self.stopping_at is not None and time.monotonic() - self.stopping_at > 10:
                    self.process.terminate()
                progress = self.lab.run_dir(self.identifier) / "progress.json"
                if progress.exists():
                    try:
                        self.message = json.loads(progress.read_text(encoding="utf-8"))["message"]
                    except (ValueError, OSError, KeyError):
                        pass
                return
            self.log.close()
            path = self.lab.run_dir(self.identifier) / ("audit.json" if self.audit_id else "result.json")
            result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
                "status": "paused" if self.stopping_at else "error",
                "error": f"Worker exited ({self.process.returncode}); see {path.parent / 'worker.log'}"}
            if self.audit_id:
                self.message = f"Holdout audit for run {self.identifier}: " + str(result)
                self.process = None
                return self.close()
            self.lab.finish(self.identifier, result)
            self.message = f"Run {self.identifier}: {result['status']} — " + result.get("error", str(result.get("validation_nll", "")))
            self.process = None
            if self.stopping_at is not None or not self.continuous or result["status"] != "completed":
                return self.close()
            self._next_at = time.monotonic() + self.cooldown_seconds
        except Exception as exc:
            self.message = str(exc)
            self.stop()
            if self.process is None or self.process.poll() is not None:
                self.close()

    def close(self):
        if self.log and not self.log.closed:
            self.log.close()
        self.active = False
        self.lab.release()
