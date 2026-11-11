import tempfile
import time
import tkinter as tk
import unittest
import threading
from pathlib import Path
from unittest.mock import Mock
from forgemind.config import Settings
from forgemind.task_queue import TaskQueue
from forgemind.task_ui import open_tasks


class TaskUITests(unittest.TestCase):
    def test_save_run_and_reopen_result(self):
        app=tk.Tk();app.withdraw()
        with tempfile.TemporaryDirectory() as directory:
            app.task_queue=TaskQueue(Path(directory)/'jobs.db')
            app.busy=False;app._upload_running=False;app._creator_operations=0
            app.engine=Mock(loaded=False);app.db=Mock();app.settings_data=Settings()
            app.inference=app.engine
            app._cancel_answer=threading.Event();app.send_button=Mock()
            errors=[];app.report_callback_exception=lambda *args:errors.append(args)
            try:
                panel=open_tasks(app);app.update()
                panel.kind.set('Calculate');panel.prompt.insert('1.0','17*23');panel.add()
                identifier=panel.selected();panel.run()
                deadline=time.monotonic()+4
                while panel.active and time.monotonic()<deadline:app.update();time.sleep(.01)
                self.assertFalse(panel.active);self.assertFalse(app.busy)
                self.assertEqual(app.task_queue.get(identifier)['state'],'succeeded')
                self.assertIn('391',panel.output.get('1.0','end'))
                panel.close();panel=open_tasks(app);app.update()
                panel.list.selection_set(identifier);panel.preview()
                self.assertIn('391',panel.output.get('1.0','end'))
                self.assertEqual(panel.output.cget('state'),'disabled')
                self.assertEqual(errors,[]);panel.close()
            finally:app.destroy()
