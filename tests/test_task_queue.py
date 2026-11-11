import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from forgemind.task_queue import TaskQueue
from forgemind.task_tools import calculate,run_one


class TasksTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'tasks.db';self.now=100
        self.queue=TaskQueue(self.path,clock=lambda:self.now)

    def test_survives_restart_and_executes(self):
        identifier=self.queue.submit('calculate',{'expression':'17*23'})
        restarted=TaskQueue(self.path,clock=lambda:self.now)
        self.assertEqual(run_one(restarted),identifier)
        row=restarted.recent()[0]
        self.assertEqual(row['state'],'succeeded');self.assertIn('391',row['result'])

    def test_two_workers_cannot_claim_same_task(self):
        self.queue.submit('calculate',{'expression':'1+1'})
        with ThreadPoolExecutor(2) as pool:
            claims=list(pool.map(lambda _:self.queue.claim(),range(2)))
        self.assertEqual(sum(job is not None for job in claims),1)

    def test_expired_work_is_not_replayed_and_old_worker_is_fenced(self):
        identifier=self.queue.submit('calculate',{'expression':'1'})
        job=self.queue.claim(1);self.now+=2
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.recent()[0]['state'],'needs_review')
        with self.assertRaises(ValueError):self.queue.finish(identifier,job['lease'],result=1)
        self.queue.retry(identifier)
        self.assertEqual(run_one(self.queue),identifier)

    def test_retry_budget_and_unknown_tool(self):
        identifier=self.queue.submit('shell',{})
        run_one(self.queue);self.queue.retry(identifier);run_one(self.queue)
        self.assertEqual(self.queue.recent()[0]['state'],'failed')
        with self.assertRaises(ValueError):self.queue.retry(identifier)

    def test_cancel_fences_worker(self):
        identifier=self.queue.submit('calculate',{'expression':'1'})
        job=self.queue.claim();self.queue.cancel(identifier)
        with self.assertRaises(ValueError):self.queue.finish(identifier,job['lease'],result=1)
        self.assertEqual(self.queue.recent()[0]['state'],'cancelled')

    def test_calculator_rejects_code_and_unbounded_inputs(self):
        for expression in ["__import__('os').system('whoami')",'2**100000000','True','1e999','1/0','[1]']:
            with self.subTest(expression=expression),self.assertRaises((ValueError,ZeroDivisionError)):
                calculate({'expression':expression})
        self.assertEqual(calculate({'expression':'(10+5)/3'})['answer'],5)

    def test_validation_and_no_work(self):
        self.assertIsNone(run_one(self.queue))
        for attempts in (0,4,True):
            with self.assertRaises(ValueError):self.queue.submit('calculate',{},attempts)
        with self.assertRaises(ValueError):self.queue.submit('calculate',{'x':float('nan')})
