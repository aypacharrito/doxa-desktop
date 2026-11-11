"""Construct the full app, not just a mock HQ host: catches missing sidebar callbacks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class StartupTests(unittest.TestCase):
    def test_full_app_opens_in_chat_with_hq_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'ForgeMind'
            data.mkdir()
            (data / 'settings.json').write_text(json.dumps({
                'voice_enabled': False, 'open_hq_on_start': False, 'team_autopilot': False,
                'auto_research': False, 'model_path': ''}), encoding='utf-8')
            env = dict(os.environ, LOCALAPPDATA=tmp, USERPROFILE=tmp)
            code = """
from app import ForgeMindApp
a = ForgeMindApp()
assert callable(a.show_team_hq)
assert a.mode == 'chat'
a.update()
a.after(150, a._on_close)
a.mainloop()
print('FULL APP STARTUP OK')
"""
            result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True,
                                    text=True, timeout=30, cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('FULL APP STARTUP OK', result.stdout)
