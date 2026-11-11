from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from forgemind.research_ui import pump_research


class BackgroundLearningTests(unittest.TestCase):
    def test_finished_cpu_trial_does_not_mark_concurrent_chat_idle(self):
        session=SimpleNamespace(tick=Mock(),message='RAM budget reached',background=True,device='cpu',active=False)
        settings=SimpleNamespace(local_learning_enabled=True,save=Mock(),model_path='')
        app=SimpleNamespace(_research_session=session,_research_reported=set(),research_lab=SimpleNamespace(runs=lambda:[]),
            busy=True,send_button=Mock(),settings_data=settings,learning_label=Mock(),
            _set_status=Mock(),refresh_all=Mock(),after=Mock(),_closing=False)
        pump_research(app)
        self.assertTrue(app.busy)
        app.send_button.configure.assert_not_called()
        app._set_status.assert_not_called()
        self.assertFalse(settings.local_learning_enabled)
        settings.save.assert_called_once()
        self.assertIsNone(app._research_session)

    def test_live_background_progress_never_interrupts_conversation(self):
        session=SimpleNamespace(tick=Mock(),message='gru step 10',background=True,device='cpu',active=True)
        app=SimpleNamespace(_research_session=session,_research_reported=set(),research_lab=SimpleNamespace(runs=lambda:[]),
            busy=True,learning_label=Mock(),_set_status=Mock(),after=Mock(),_closing=False)
        pump_research(app)
        app._set_status.assert_not_called()
        app.learning_label.configure.assert_called_once()
        self.assertTrue(app.busy)

if __name__=='__main__':unittest.main()
