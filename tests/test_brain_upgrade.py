from datetime import datetime
import unittest
from forgemind.answer_filter import AnswerFilter
from forgemind.local_tools import clock_reply
from forgemind.engine import LocalEngine
from forgemind.config import Settings


class BrainUpgradeTests(unittest.TestCase):
    def test_split_reasoning_tags_never_reach_visible_answer(self):
        parser=AnswerFilter()
        pieces=['<th','ink>','private notes','</thi','nk>','Hello, the owner.']
        self.assertEqual(''.join(parser.feed(x) for x in pieces)+parser.finish(),'Hello, the owner.')

    def test_template_can_start_inside_reasoning_and_cancel_without_final(self):
        parser=AnswerFilter(thinking=True)
        self.assertEqual(parser.feed('not a final answer'),'')
        self.assertEqual(parser.feed('</think>391'),'391')
        self.assertEqual(parser.finish(),'')
        parser=AnswerFilter(thinking=True)
        parser.feed('budget ended')
        with self.assertRaises(ValueError):parser.finish()

    def test_plain_stream_and_orphan_closing_tag(self):
        parser=AnswerFilter()
        self.assertEqual(parser.feed('</think>hello'),'hello')
        self.assertEqual(parser.feed(' world'),' world')
        self.assertEqual(parser.finish(),'')

    def test_actual_clock_tool_uses_supplied_device_time(self):
        now=datetime(2026,10,26,19,7)
        self.assertEqual(clock_reply('what time is it right now?',now),'It’s 7:07 PM on your computer.')
        self.assertIn('October 26, 2026',clock_reply('what day is today',now))
        self.assertIsNone(clock_reply('Write a story about what time means',now))

    def test_reasoning_budget_reserves_context_before_generation(self):
        class Model:
            def tokenize(self,text,**kwargs):return list(text)
            def detokenize(self,tokens):return bytes(tokens)
            def create_chat_completion(self,**kwargs):
                self.request=kwargs
                yield {'choices':[{'delta':{'content':'</think>Final answer'}}]}
        engine=LocalEngine();engine._model=Model();engine._reasoning_model=True
        engine._set_thinking=lambda enabled:None
        answer=''.join(engine.stream([], 'Think carefully: '+('large task '*3000),Settings(max_tokens=256),[],[]))
        self.assertEqual(answer,'Final answer')
        request=engine._model.request
        self.assertEqual(request['max_tokens'],2048)
        self.assertLessEqual(sum(len(m['content'].encode()) for m in request['messages'])+request['max_tokens'],8192)

if __name__=='__main__':unittest.main()
