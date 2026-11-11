import json
import threading
import unittest
from forgemind.voice import WakeRouter, spoken_text
from forgemind.engine import LocalEngine
from forgemind.config import Settings


class VoiceTests(unittest.TestCase):
    def test_background_speech_is_ignored(self):
        router=WakeRouter()
        for text in ['Send this to everyone', 'Do you know Jarvis?', 'We were talking about Jarvis yesterday']:
            self.assertIsNone(router.accept(text))

    def test_wake_plus_request_and_low_confidence(self):
        router=WakeRouter()
        self.assertIsNone(router.accept('Jarvis delete my files', .2))
        self.assertEqual(router.accept('Hey Jarvis, what is 17 times 23?'), ('command', 'what is 17 times 23?'))
        self.assertIsNone(router.accept('and send the result'))

    def test_bare_wake_accepts_only_one_following_turn_and_expires(self):
        now=[10]
        router=WakeRouter(lambda: now[0])
        self.assertEqual(router.accept('Jarvis'), ('wake',''))
        self.assertEqual(router.accept('Hello there'), ('command','Hello there'))
        self.assertIsNone(router.accept('TV in the background'))
        router.accept('Jarvis')
        now[0]=26
        self.assertIsNone(router.accept('too late'))

    def test_stop_and_reset(self):
        router=WakeRouter()
        self.assertEqual(router.accept('Jarvis stop listening'), ('stop',''))
        router.accept('Jarvis')
        router.reset()
        self.assertIsNone(router.accept('do something'))

    def test_speech_does_not_read_code_or_urls(self):
        text=spoken_text('Use **this**. ```python\nprint(1)\n``` [Docs](https://example.com) https://example.com/secret')
        self.assertNotIn('print',text)
        self.assertNotIn('https',text)
        self.assertIn('Docs',text)
        self.assertLess(len(spoken_text('word '*2000)),1500)

    def test_cancel_closes_stream_and_preserves_compatibility(self):
        class Fake:
            closed=False
            def tokenize(self,data,**kwargs):return list(data)
            def detokenize(self,data):return bytes(data)
            def create_chat_completion(self,**kwargs):
                try:
                    for word in ['first','second','third']:
                        yield {'choices':[{'delta':{'content':word}}]}
                finally:self.closed=True
        model=Fake(); engine=LocalEngine();engine._model=model
        stop=threading.Event()
        stream=engine.stream([], 'hello', Settings(), [], [], stop_event=stop)
        self.assertEqual(next(stream),'first')
        stop.set()
        self.assertEqual(list(stream),[])
        self.assertTrue(model.closed)

if __name__=='__main__': unittest.main()


class DoxaWakeTests(unittest.TestCase):
    def test_doxa_is_the_wake_word(self):
        from forgemind.voice import WakeRouter
        router = WakeRouter()
        self.assertEqual(router.accept('Hey Doxa, what time is it?'), ('command', 'what time is it?'))
        self.assertEqual(router.accept('Doxa'), ('wake', ''))
        self.assertIsNone(WakeRouter().accept('The word doxa means glory'))  # not addressed to Doxa


if __name__ == '__main__':
    unittest.main()
