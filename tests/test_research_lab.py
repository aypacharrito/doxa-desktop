from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forgemind.lab_worker import ngram_score, ngram_train, run_job, split_corpus
from forgemind.research_lab import LabSession, ResearchLab, starter_corpus, validate_spec


class ResearchLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.lab = ResearchLab(Path(self.temp.name) / "lab")
        self.digest = self.lab.corpus()

    def tearDown(self):
        self.temp.cleanup()

    def test_corpus_snapshot_is_content_addressed_and_source_unchanged(self):
        source = Path(self.temp.name) / "owner.txt"
        data = starter_corpus()
        source.write_bytes(data)
        self.assertEqual(self.lab.corpus(source), hashlib.sha256(data).hexdigest())
        self.assertEqual(source.read_bytes(), data)
        self.assertEqual(len(list((self.lab.root / "corpora").iterdir())), 1)

    def test_split_has_disjoint_byte_ranges(self):
        data = b"a" * 8000 + b"b" * 1000 + b"c" * 1000
        self.assertEqual(split_corpus(data), (b"a" * 8000, b"b" * 1000, b"c" * 1000))

    def test_specs_are_typed_not_arbitrary_code(self):
        for spec in ({"family": "exec", "code": "danger"}, {"family": "gru", "width": 10000},
                     {"family": "gru", "learning_rate": float("nan")}, {"family": "ngram", "order": True}):
            with self.assertRaises(ValueError):
                validate_spec(spec)
        self.assertEqual(validate_spec({"family": "ngram", "order": 3})["order"], 3)

    def test_never_completes_without_checkpoint_or_finite_metric(self):
        identifier = self.lab.create(self.digest, {"family": "ngram"})
        result = dict(status="completed", validation_nll=1.0, elapsed_seconds=0.1, parameters=20,
                      checkpoint="ngram.json")
        with self.assertRaises(ValueError):
            self.lab.finish(identifier, result)
        (self.lab.run_dir(identifier) / "ngram.json").write_text("{}")
        self.lab.finish(identifier, result)
        with self.assertRaises(ValueError):
            self.lab.finish(identifier, dict(result, validation_nll=float("nan")))

    def test_process_lease_prevents_parallel_gpu_sessions(self):
        self.lab.acquire()
        with self.assertRaises(RuntimeError):
            ResearchLab(self.lab.root).acquire()
        self.lab.release()
        self.lab.acquire()
        self.lab.release()

    def test_orphaned_live_worker_prevents_parallel_session(self):
        identifier = self.lab.create(self.digest, {"family": "ngram"})
        with self.lab.connection() as db:
            db.execute("UPDATE runs SET status='running',owner_pid=123456 WHERE id=?", (identifier,))
        with patch("forgemind.research_lab._alive", return_value=True):
            with self.assertRaises(RuntimeError):
                self.lab.acquire()

    def test_interrupted_worker_recovers_as_paused(self):
        identifier = self.lab.create(self.digest, {"family": "gru"})
        with self.lab.connection() as db:
            db.execute("UPDATE runs SET status='running',owner_pid=123456 WHERE id=?", (identifier,))
        with patch("forgemind.research_lab._alive", return_value=False):
            self.lab.recover()
        self.assertEqual(self.lab.runs()[0]["status"], "paused")

    def test_missing_or_tampered_corpus_rejected(self):
        (self.lab.root / "corpora" / (self.digest + ".txt")).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.lab.create(self.digest, {"family": "gru"})

    def test_real_non_neural_worker_and_separate_holdout(self):
        identifier = self.lab.create(self.digest, {"family": "ngram", "order": 3})
        path = self.lab.run_dir(identifier) / "job.json"
        result = run_job(path)
        self.assertLess(result["validation_nll"], 5.0)
        self.lab.finish(identifier, result)
        audit = run_job(path, audit=True)
        self.assertIn("test_nll", audit)
        self.assertNotIn("test_nll", self.lab.runs()[0]["result"])
        # Even a fake outstanding audit cannot enter the automatic proposal inputs.
        spec, _parent = self.lab.propose(self.digest)
        self.assertEqual(spec["family"], "gru")

    def test_non_neural_pause_is_reported_not_success(self):
        with self.assertRaises(InterruptedError):
            ngram_train(starter_corpus(), 3, lambda: True)

    def test_symbolic_baseline_learns_actual_counts(self):
        counts = ngram_train(b"abcdef" * 1000, 2)
        self.assertLess(ngram_score(counts, b"abcdef" * 100, 2), 1)

    def test_failed_launch_releases_lease(self):
        session = LabSession(self.lab, self.digest)
        with patch.object(session, "_launch", side_effect=RuntimeError("missing runtime")):
            session.tick()
        self.assertFalse(session.active)
        self.assertIn("missing runtime", session.message)
        self.lab.acquire()
        self.lab.release()

    def test_planner_replays_reproducibly(self):
        self.assertEqual(self.lab.propose(self.digest), self.lab.propose(self.digest))

    def test_stop_before_launch_creates_no_worker_or_trial(self):
        session = LabSession(self.lab, self.digest, continuous=True)
        session.stop()
        with patch.object(session, "_launch") as launch:
            session.tick()
            launch.assert_not_called()
        self.assertFalse(session.active)
        self.assertEqual(self.lab.runs(), [])
        self.lab.acquire()
        self.lab.release()

    def test_resource_wait_keeps_session_active_without_a_worker(self):
        session=LabSession(self.lab,self.digest,continuous=True,device='cpu',background=True)
        def wait():
            session._next_at=__import__('time').monotonic()+60
            session.message='Waiting for RAM'
        with patch.object(session,'_launch',side_effect=wait) as launch:
            session.tick()
            session.tick()
            self.assertTrue(session.active)
            self.assertIsNone(session.process)
            launch.assert_called_once()
        session.stop();session.tick()
        self.assertFalse(session.active)

    def test_recovered_real_result_survives_restart(self):
        identifier = self.lab.create(self.digest, {"family": "ngram", "order": 2})
        folder = self.lab.run_dir(identifier)
        result = run_job(folder / "job.json")
        (folder / "result.json").write_text(json.dumps(result))
        with self.lab.connection() as db:
            db.execute("UPDATE runs SET status='running',owner_pid=123456 WHERE id=?", (identifier,))
        reopened = ResearchLab(self.lab.root)
        with patch("forgemind.research_lab._alive", return_value=False):
            reopened.recover()
        self.assertEqual(reopened.runs()[0]["status"], "completed")
        self.assertEqual(reopened.runs()[0]["result"]["validation_nll"], result["validation_nll"])


if __name__ == "__main__":
    unittest.main()
