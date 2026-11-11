import tempfile
import threading
import unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest.mock import Mock,patch
from forgemind.autopilot import Autopilot
from forgemind.task_queue import TaskQueue
from forgemind.cloud_brain import CloudBudget,CloudBrain


class AutopilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_slots_are_durable_and_pause_does_not_enqueue(self):
        app=SimpleNamespace(task_queue=TaskQueue(self.root/'jobs.db'))
        pilot=Autopilot(app);pilot.prompt=lambda kind:kind+' useful review'
        now=datetime(2026,11,3,19,tzinfo=ZoneInfo('America/Los_Angeles'))
        pilot.enqueue_due(now);self.assertEqual(app.task_queue.recent(),[])
        pilot.configure({'enabled':True,'cloud_growth':True})
        pilot.enqueue_due(now);pilot.enqueue_due(now)
        self.assertEqual(len(app.task_queue.recent()),4)  # morning, leads, growth, evening
        self.assertEqual(sum(j['tool']=='cloud_draft' for j in app.task_queue.recent()),2)  # growth + leads
        again=Autopilot(app);again.prompt=pilot.prompt;again.enqueue_due(now)
        self.assertEqual(len(app.task_queue.recent()),4)

    def test_budget_survives_restart_and_fails_closed_at_five_dollars(self):
        budget=CloudBudget(self.root/'budget.db')
        for _ in range(100):budget.reserve()
        with self.assertRaises(ValueError):CloudBudget(budget.path).reserve()
        self.assertEqual(budget.summary()['reserved_cents'],500)

    def test_concurrent_budget_reservations_do_not_overspend(self):
        budget=CloudBudget(self.root/'budget.db')
        for _ in range(98):budget.reserve()
        results=[]
        def reserve():
            try:budget.reserve();results.append(True)
            except ValueError:results.append(False)
        threads=[threading.Thread(target=reserve) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(results),2)

    def test_cloud_sends_only_explicit_text_and_has_no_retry_or_tools(self):
        (self.root/'openai-key.dpapi').write_bytes(b'fake-encrypted')
        response=Mock(ok=True);response.json.return_value={'status':'completed','usage':{'input_tokens':100,'output_tokens':50},'output':[{'type':'message','content':[{'type':'output_text','text':'Draft'}]}]}
        transport=Mock(return_value=response);brain=CloudBrain(self.root,transport)
        with patch('forgemind.cloud_brain.windows_key',return_value=b'sk-test-secret'):
            self.assertEqual(list(brain.stream(['private-history'],'selected text',None,['private-memory'],['private-web'])),['Draft'])
        body=transport.call_args.kwargs['json']
        self.assertEqual(body['input'],'selected text');self.assertFalse(body['store'])
        self.assertNotIn('tools',body);self.assertNotIn('private',str(body))
        self.assertAlmostEqual(brain.budget.summary()['reserved_cents'],0.03)  # settled to the real cost (100 in / 50 out tokens)
        self.assertAlmostEqual(brain.budget.summary()['actual_usd'],0.0003)
        transport.assert_called_once()

    def test_stop_and_oversize_do_not_spend(self):
        (self.root/'openai-key.dpapi').write_bytes(b'x')
        brain=CloudBrain(self.root,Mock());stop=threading.Event();stop.set()
        self.assertEqual(list(brain.stream([],'x',None,[],[],stop)),[])
        with self.assertRaises(ValueError):list(brain.stream([],'x'*12001,None,[],[]))
        self.assertEqual(brain.budget.summary()['reserved_cents'],0)
