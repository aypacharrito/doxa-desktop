import tempfile
import unittest
from pathlib import Path
from forgemind.workspace import RunJournal, personal_context, clean_routines
from forgemind.config import Settings

class WorkspaceTests(unittest.TestCase):
    def test_measured_run_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            now=[1.0]
            path=Path(directory)/'runs.sqlite3'
            journal=RunJournal(path,clock=lambda:now[0])
            run=journal.start('Test request')
            now[0]=1.25
            journal.first_response(run)
            now[0]=2.0
            journal.first_response(run)
            journal.finish(run,'complete')
            row=journal.recent()[0]
            self.assertEqual(row['first_response_ms'],250)
            self.assertEqual(row['elapsed_ms'],1000)
            journal.start('Interrupted')
            self.assertEqual(RunJournal(path).recent()[0]['status'],'interrupted')

    def test_owner_context_and_routines_are_bounded(self):
        self.assertEqual(personal_context(Settings()),'')
        text=personal_context(Settings(display_name='the owner',personal_brief='Concise, practical'))
        self.assertIn('the owner',text)
        self.assertIn('not evidence',text)
        self.assertEqual(clean_routines([None,{'name':'','prompt':'x'}]),[])
        self.assertEqual(len(clean_routines([{'name':'n','prompt':'p'}]*30)),24)
        one,two=Settings(),Settings()
        one.routines[0]['name']='changed'
        self.assertNotEqual(one.routines,two.routines)
