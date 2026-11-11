import json
import tempfile
import unittest
from pathlib import Path
from forgemind.code_graph import build, query


class CodeGraphTests(unittest.TestCase):
    def test_refresh_and_remove_symbols(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'forgemind').mkdir()
            source = root / 'app.py'
            source.write_text('class Phone:\n def recover(self):\n  reconnect()\n')
            cache = root / 'map.json'
            first = query(root, cache, 'recover')
            self.assertEqual(first['matches'][0]['name'], 'Phone.recover')
            self.assertIn('reconnect', first['matches'][0]['calls_observed'])
            self.assertEqual(build(root, cache)[1], 0)
            source.write_text('def changed(): pass\n')
            self.assertEqual(query(root, cache, 'recover')['matches'], [])
            source.unlink()
            self.assertEqual(build(root, cache)[0]['files'], {})
