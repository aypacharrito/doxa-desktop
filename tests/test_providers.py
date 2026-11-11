import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from forgemind.config import Settings
from forgemind.providers import LlamaCppProvider, LocalInference, ModelUsage


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.usage=ModelUsage(Path(self.temp.name)/'usage.db')
        self.engine=Mock(loaded=True,model_name='local-model.gguf')
        self.engine.stream.return_value=iter(['Hello',' world'])
        self.route=LocalInference(LlamaCppProvider(self.engine),self.usage)
        self.stop=threading.Event()

    def generate(self):
        return self.route.stream([], 'private prompt', Settings(), [{'content':'private memory'}], [], stop_event=self.stop)

    def test_preserves_context_and_logs_only_metadata(self):
        self.assertEqual(''.join(self.generate()),'Hello world')
        self.assertEqual(self.engine.stream.call_args.args[1],'private prompt')
        self.assertEqual(self.engine.stream.call_args.args[3],[{'content':'private memory'}])
        self.assertIs(self.engine.stream.call_args.kwargs['stop_event'],self.stop)
        row=self.usage.recent()[0]
        self.assertEqual(row['state'],'generated');self.assertEqual(row['output_chars'],11)
        self.assertEqual(row['api_cost_usd'],0);self.assertIsNotNone(row['first_text_ms'])
        self.assertNotIn('private',str(row));self.assertNotIn('Hello',str(row))

    def test_external_provider_rejected_without_invocation(self):
        provider=Mock(local=False)
        with self.assertRaises(ValueError):LocalInference(provider,self.usage)
        provider.stream.assert_not_called()

    def test_cancel_before_start_never_invokes_model(self):
        self.stop.set();self.assertEqual(list(self.generate()),[])
        self.engine.stream.assert_not_called()
        self.assertEqual(self.usage.recent()[0]['state'],'stopped')

    def test_cancel_during_stream_closes_provider(self):
        closed=[]
        def source(*args,**kwargs):
            try:
                yield 'first'
                self.stop.set()
                yield 'discard'
            finally:closed.append(True)
        self.engine.stream.side_effect=source
        self.assertEqual(list(self.generate()),['first'])
        self.assertTrue(closed);self.assertEqual(self.usage.recent()[0]['state'],'stopped')

    def test_error_propagates_without_fallback_or_error_content_logging(self):
        self.engine.stream.side_effect=RuntimeError('private failure details')
        with self.assertRaises(RuntimeError):list(self.generate())
        row=self.usage.recent()[0]
        self.assertEqual(row['state'],'error');self.assertNotIn('private',str(row))
        self.engine.stream.assert_called_once()

    def test_consumer_close_records_interruption(self):
        result=self.generate();next(result);result.close()
        self.assertEqual(self.usage.recent()[0]['state'],'interrupted')

    def test_unloaded_and_empty_are_not_success(self):
        self.engine.loaded=False
        with self.assertRaises(RuntimeError):list(self.generate())
        self.assertEqual(self.usage.recent()[0]['state'],'error')
        self.engine.loaded=True;self.engine.stream.return_value=iter([])
        self.assertEqual(list(self.generate()),[])
        self.assertEqual(self.usage.recent()[0]['state'],'empty')

    def test_restart_marks_unfinished_without_replaying(self):
        self.usage.start('llama.cpp','local.gguf')
        other=ModelUsage(self.usage.path);other.recover()
        self.assertEqual(other.recent()[0]['state'],'interrupted')
        self.engine.stream.assert_not_called()
