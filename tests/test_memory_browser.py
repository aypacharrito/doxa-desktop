"""Isolated native UI checks. Uses synthetic data and never constructs a model."""
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from forgemind.database import MemoryDB
from forgemind.workspace_ui import open_memory


class MemoryBrowserTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.app.withdraw()
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.app.db = MemoryDB(Path(self.directory.name) / "synthetic.sqlite3")
        self.app.db.add_memory("Synthetic Friday appointment")
        self.source = Path(self.directory.name) / "example.txt"
        self.app.db.replace_document(self.source, 1, 10, ["Synthetic orchid appointment details"])
        for name in ("add_memory", "choose_files", "choose_knowledge", "backup_now", "refresh_all"):
            setattr(self.app, name, Mock())
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        open_memory(self.app)
        self.browser = self.app._memory_browser
        self.wait_for(lambda: len(self.browser.rows) == 2)

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()
        if hasattr(self, "browser"):
            self.browser.worker.join(timeout=3)
        if hasattr(self, "directory"):
            self.directory.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.app.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Memory UI did not finish its local query")

    def test_search_filter_sources_and_read_only_document_preview(self):
        browser = self.browser
        browser.query.set("orchid")
        self.wait_for(lambda: len(browser.rows) == 1 and browser.rows[0]["kind"] == "file")
        self.assertIn(str(self.source), browser.source.cget("text"))
        self.assertEqual(browser.detail.cget("state"), "disabled")
        self.assertEqual(browser.remove.cget("state"), "disabled")
        self.assertIn("orchid", browser.detail.get("1.0", "end"))
        browser._filter("pinned")
        self.wait_for(lambda: "No matches" in browser.status.get())
        self.assertEqual(browser.rows, [])
        self.assertEqual(browser.copy.cget("state"), "disabled")
        self.assertEqual(self.errors, [])

    def test_pin_removal_requires_confirmation_and_keeps_documents(self):
        browser = self.browser
        browser._filter("pinned")
        self.wait_for(lambda: len(browser.rows) == 1 and browser.rows[0]["kind"] == "pinned")
        with patch("forgemind.workspace_ui.messagebox.askyesno", return_value=False):
            browser.remove_selected()
        self.assertEqual(self.app.db.counts()["memories"], 1)
        with patch("forgemind.workspace_ui.messagebox.askyesno", return_value=True):
            browser.remove_selected()
        self.wait_for(lambda: "No pinned memories" in browser.status.get())
        self.assertEqual(self.app.db.counts()["documents"], 1)
        self.app.refresh_all.assert_called_once()

    def test_reuse_keyboard_navigation_and_close_during_search(self):
        browser = self.browser
        self.assertIs(open_memory(self.app), browser.win)
        browser._move(1)
        self.assertEqual(browser.selected, 1)
        self.assertGreater(browser.detail.winfo_reqheight(), 0)
        browser.query.set("pending query")
        browser.win.destroy()
        self.app.update()
        self.assertTrue(browser.closed)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
