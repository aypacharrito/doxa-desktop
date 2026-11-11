import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from forgemind.quick_actions import parse_command, launch_app, local_brief


class QuickActionTests(unittest.TestCase):
    def test_explicit_allowlisted_commands_only(self):
        self.assertEqual(parse_command('Please open VYRA.').target, 'vyra')
        self.assertEqual(parse_command('open my downloads please').target, 'downloads')
        self.assertEqual(parse_command('Use my computer to organize this draft').kind, 'computer')
        for value in ['How do I open VYRA?', 'open cmd', 'open https://example.com',
                      'open VYRA and delete everything', 'He said open VYRA',
                      'open C:/Windows/System32/cmd.exe', 'open notepad & calc']:
            self.assertIsNone(parse_command(value), value)

    def test_launch_uses_exact_target_no_shell_or_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Downloads').mkdir()
            opener = Mock()
            result = launch_app('downloads', home=root, startfile=opener)
            opener.assert_called_once_with(str(root / 'Downloads'))
            self.assertIn('open request', result)
            with self.assertRaises(FileNotFoundError):
                launch_app('vyra', local=root, startfile=opener)
            with self.assertRaises(ValueError):
                launch_app('cmd.exe', startfile=opener)
            self.assertEqual(opener.call_count, 1)

    def test_brief_only_reports_todays_actual_records(self):
        settings = SimpleNamespace(personal_brief='Focus on existing customers.')
        rows = [dict(local_date='2026-11-02', status='complete', title='A draft', stage='Response ready'),
                dict(local_date='2026-11-01', status='complete', title='Old task', stage='Response ready')]
        reply = local_brief(settings, {'memories': 2, 'documents': 3}, rows, today='2026-11-02')
        self.assertIn('1 completed requests', reply)
        self.assertNotIn('Old task', reply)
        self.assertIn("Calendar isn't connected", reply)
        self.assertIn('Email is not connected', reply)

    def test_stop_cancels_desktop_control_and_interrupts_voice(self):
        from app import ForgeMindApp
        app = SimpleNamespace(_cancel_answer=Mock(), _computer_controls=Mock(), voice=Mock(), _voice_turn=True)
        ForgeMindApp.stop_jarvis(app)
        app._computer_controls.cancel.assert_called_once()
        app.voice.interrupt.assert_called_once()  # Stop/Esc stop the turn; listening for "Doxa" stays on
        app.voice.disable.assert_not_called()


if __name__ == '__main__':
    unittest.main()
