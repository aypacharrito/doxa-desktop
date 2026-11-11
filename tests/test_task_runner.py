import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from forgemind.config import Settings
from forgemind.task_queue import TaskQueue
from forgemind.task_runner import run_selected


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.queue=TaskQueue(Path(self.temp.name)/'jobs.db')
        self.engine=Mock(loaded=True,model_name='test local model')
        self.engine.stream.return_value=iter(['Hello, ','review this draft.'])
        self.memory=Mock();self.memory.retrieve.return_value=[]
        self.stop=threading.Event()

    def run_draft(self):
        identifier=self.queue.submit('local_draft',{'prompt':'Prepare a follow-up draft'})
        return run_selected(self.queue,identifier,self.engine,self.memory,Settings(),self.stop)

    def test_local_draft_has_no_web_or_actions(self):
        row=self.run_draft()
        self.assertEqual(row['state'],'succeeded')
        self.assertIn('review_required',row['result'])
        args=self.engine.stream.call_args.args
        self.assertEqual(args[0],[]);self.assertEqual(args[4],[])
        self.assertFalse(args[2].auto_research)
        self.memory.retrieve.assert_called_once_with('Prepare a follow-up draft')

    def test_stop_never_saves_partial_success(self):
        def stream(*args,**kwargs):
            yield 'partial'
            self.stop.set()
            yield 'not complete'
        self.engine.stream.side_effect=stream
        row=self.run_draft()
        self.assertEqual(row['state'],'cancelled');self.assertIsNone(row['result'])

    def test_unloaded_model_and_empty_result_fail(self):
        self.engine.loaded=False
        self.assertEqual(self.run_draft()['state'],'failed')
        self.engine.loaded=True;self.engine.stream.return_value=iter([])
        self.assertEqual(self.run_draft()['state'],'failed')

    def test_selected_job_does_not_claim_other_work(self):
        first=self.queue.submit('calculate',{'expression':'1+1'})
        second=self.queue.submit('calculate',{'expression':'17*23'})
        row=run_selected(self.queue,second,self.engine,self.memory,Settings(),self.stop)
        self.assertIn('391',row['result']);self.assertEqual(self.queue.get(first)['state'],'queued')

    def test_timeout_cancels(self):
        def stream(*args,**kwargs):
            self.stop.wait(1)
            yield 'late'
        self.engine.stream.side_effect=stream
        identifier=self.queue.submit('local_draft',{'prompt':'test'})
        row=run_selected(self.queue,identifier,self.engine,self.memory,Settings(),self.stop,timeout=.02)
        self.assertEqual(row['state'],'cancelled')
