import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from forgemind.phone_delegate import AppPhoneDelegate

class PhoneCloudTests(unittest.TestCase):
    def test_cloud_receives_only_explicit_prompt(self):
        cloud=Mock(loaded=True)
        cloud.stream.return_value=iter(['Draft'])
        app=SimpleNamespace(cloud=cloud,db=Mock(),events=Mock())
        delegate=AppPhoneDelegate(app)
        events=list(delegate.chat_stream('OpenAI draft: Write a caption'))
        args=cloud.stream.call_args.args
        self.assertEqual(args,([], 'Write a caption', None, [], []))
        app.db.recent_messages.assert_not_called()
        app.db.retrieve.assert_not_called()
        self.assertEqual(events[-1]['reply'],'Draft')
        self.assertTrue(delegate._chat_lock.acquire(blocking=False))
    def test_failure_releases_lock_without_retry(self):
        cloud=Mock(loaded=True)
        cloud.stream.side_effect=ValueError('cap reached')
        delegate=AppPhoneDelegate(SimpleNamespace(cloud=cloud))
        with self.assertRaises(ValueError):list(delegate.chat_stream('OpenAI draft: Hello'))
        self.assertEqual(cloud.stream.call_count,1)
        self.assertTrue(delegate._chat_lock.acquire(blocking=False))


class NewMessageTakesOverTests(unittest.TestCase):
    """the owner 2026-11-09: "it said Doxa is already answering a phone message". A new message stops the old answer."""

    def make(self):
        import threading
        started, release = threading.Event(), threading.Event()

        class Brain:
            def ready(self, settings):
                return True

            def stream(self, history, text, settings, memories, web, stop_event=None):
                started.set()
                yield "first words "
                while not stop_event.is_set() and not release.is_set():
                    stop_event.wait(0.02)
                if not stop_event.is_set():
                    yield "rest"

        journal = Mock()
        app = SimpleNamespace(brain=Brain(), settings_data=SimpleNamespace(auto_research=False), events=Mock(),
                              db=Mock(), run_journal=journal, engine=SimpleNamespace(model_name="test"))
        app.db.recent_messages.return_value = []
        app.db.retrieve.return_value = []
        return AppPhoneDelegate(app), started, release

    def test_a_new_message_stops_the_old_answer_instead_of_bouncing(self):
        import threading
        from unittest import mock
        delegate, started, release = self.make()
        with mock.patch("forgemind.phone_delegate.Settings", lambda **kw: SimpleNamespace(auto_research=False)):
            old = delegate.chat_stream("research everything about Etsy")
            first = next(old)  # the phone got the first words, then disconnected: nobody reads `old` any more
            self.assertEqual(first["text"], "first words ")
            self.assertTrue(started.wait(2))
            finished = []
            threading.Thread(target=lambda: finished.append(list(old)), daemon=True).start()  # the server thread
            release_later = threading.Timer(5, release.set)
            release_later.start()
            events = list(delegate.chat_stream("hello again"))
            release_later.cancel()
            self.assertEqual(events[-1]["type"], "done")
            self.assertIn("[Stopped]", finished[0][-1]["reply"])

    def test_an_answer_that_never_started_does_not_lock_doxa(self):
        from unittest import mock
        delegate, started, release = self.make()
        release.set()
        with mock.patch("forgemind.phone_delegate.Settings", lambda **kw: SimpleNamespace(auto_research=False)):
            delegate.chat_stream("dropped before the first byte")  # never iterated (connection failed)
            events = list(delegate.chat_stream("next message"))
        self.assertEqual(events[-1]["type"], "done")
        self.assertTrue(delegate._chat_lock.acquire(blocking=False))
