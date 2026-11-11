from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from forgemind.opportunity_desk import OpportunityDesk, parse_feed


class OpportunityTests(unittest.TestCase):
    def test_public_feed_is_observation_not_performance_proof(self):
        xml = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Live trade claim</title>
        <published>2026-11-09T10:00:00Z</published><link href="https://www.youtube.com/watch?v=test"/>
        </entry></feed>'''
        response = Mock(text=xml, content=xml.encode())
        with tempfile.TemporaryDirectory() as tmp:
            desk = OpportunityDesk(Path(tmp))
            first = desk.scan(get=Mock(return_value=response))
            self.assertEqual(len(first['new_urls']), 1)
            self.assertFalse(first['live_broker_connected'])
            self.assertFalse(first['live_stream_capture'])
            second = desk.scan(get=Mock(return_value=response))
            self.assertEqual(second['new_urls'], [])
            failed = desk.scan(get=Mock(side_effect=RuntimeError('access unavailable')))
            self.assertTrue(failed['error'])
            self.assertEqual(len(failed['items']), 1)
            self.assertNotIn('profit', failed)
