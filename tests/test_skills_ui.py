import ctypes
import os
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

from forgemind import jarvis_ui, skills, win_identity

HERE = Path(__file__).resolve().parent.parent


class SkillDataTests(unittest.TestCase):
    def test_skills_are_well_formed(self):
        keys = [s.key for s in skills.SKILLS]
        self.assertEqual(len(keys), len(set(keys)))
        for skill in skills.SKILLS:
            self.assertIn(skill.kind, {"answer", "prompt"})
            self.assertTrue(skill.title and skill.subtitle and skill.text)
            if skill.kind == "prompt":
                self.assertLess(len(skill.text), 600, skill.key)  # local model prompt budget
        for key in skills.SUGGESTIONS:
            skills.get(key)

    def test_no_trading_or_investment_skills(self):
        text = " ".join(f"{s.title} {s.subtitle} {s.text}" for s in skills.SKILLS).lower()
        for word in ["insider", "god mode", "trade ", "trading", "stock", "crypto", "signal"]:
            self.assertNotIn(word, text)


class FakeInput:
    def __init__(self):
        self.text, self.tags, self.marks, self.events = "", [], {}, []

    def delete(self, *_):
        self.text = ""

    def insert(self, _index, text):
        self.text += text

    def focus_set(self):
        pass

    def tag_remove(self, *args):
        pass

    def tag_add(self, tag, start, end):
        self.tags.append((tag, start, end))

    def mark_set(self, name, index):
        self.marks[name] = index

    def event_generate(self, name):
        self.events.append(name)


class RunSkillTests(unittest.TestCase):
    def make_app(self):
        from app import ForgeMindApp
        posted, shown, status = [], [], []
        app = SimpleNamespace(busy=False, input=FakeInput(),
                              db=SimpleNamespace(add_message=lambda role, text: posted.append((role, text))),
                              _append=lambda tag, text: shown.append(text), refresh_all=lambda: None,
                              _set_status=lambda text, error=False: status.append(text))
        return ForgeMindApp, app, posted, status

    def test_checklist_answers_instantly_without_the_model(self):
        cls, app, posted, _ = self.make_app()
        cls.run_skill(app, "instagram_checklist")
        self.assertEqual(posted[0], ("user", "Instagram growth checklist"))
        self.assertIn("Account Status", posted[1][1])
        self.assertEqual(app.input.text, "")

    def test_prompt_skill_fills_the_box_and_selects_the_placeholder(self):
        cls, app, posted, status = self.make_app()
        cls.run_skill(app, "reel_scripts")
        self.assertEqual(posted, [])
        self.assertTrue(app.input.text.startswith("Write 3 Instagram reel scripts"))
        tag, start, end = app.input.tags[0]
        self.assertEqual(tag, "sel")
        first = app.input.text.index("[")
        self.assertEqual(start, f"1.0+{first}c")
        self.assertEqual(end, f"1.0+{app.input.text.index(']', first) + 1}c")
        self.assertIn("press Send", status[-1])

    def test_busy_checklist_waits(self):
        cls, app, posted, status = self.make_app()
        app.busy = True
        cls.run_skill(app, "shopify_launch")
        self.assertEqual(posted, [])
        self.assertIn("Finish or stop", status[-1])


class PanelTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"no display: {exc}")
        self.root.withdraw()
        jarvis_ui._pick_fonts(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_recents_list_past_chats_and_open_them(self):
        chats = [{"id": 9, "title": "write a reel script about renters insurance for students", "updated": "", "count": 2},
                 {"id": 0, "title": "how do I grow my page", "updated": "", "count": 4}]
        opened = []
        self.root._recents_box = tk.Frame(self.root, bg=jarvis_ui.SURFACE)
        self.root.db = SimpleNamespace(chats=lambda n: chats)
        self.root.open_chat = opened.append
        jarvis_ui.refresh_recents(self.root)
        labels = self.root._recents_box.winfo_children()
        self.assertEqual([w.cget("text") for w in labels], ["write a reel script about rent…", "how do I grow my page"])
        self.assertTrue(labels[1].bind("<Button-1>"))  # clicking opens that chat (app.open_chat)

    def test_skills_and_tools_panels_build(self):
        ran = []
        self.root.run_skill = ran.append
        for name in ("capability_label", "stats_label", "growth_label", "learning_label"):
            setattr(self.root, name, tk.Label(self.root, text=name))
        skills_window = jarvis_ui.open_skills(self.root)
        tools_window = jarvis_ui.open_tools(self.root, [("Group", [("Thing", "Does it.", lambda: ran.append("t"))])])
        self.root.update_idletasks()
        self.assertTrue(skills_window.winfo_exists() and tools_window.winfo_exists())


@unittest.skipUnless(os.name == "nt", "taskbar identity is Windows-only")
class TaskbarIdentityTests(unittest.TestCase):
    def test_window_gets_doxa_identity_icon_and_relaunch_command(self):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Doxa.Desktop")
        root = tk.Tk()
        try:
            root.update_idletasks()
            hwnd = int(root.wm_frame(), 16)
            icon = HERE / "forgemind" / "doxa.ico"
            self.assertTrue(win_identity.apply_to_window(hwnd, icon))
            self.assertEqual(win_identity.read_window_property(hwnd, "ID"), "Doxa.Desktop")
            self.assertEqual(win_identity.read_window_property(hwnd, "RelaunchDisplayNameResource"), "Doxa")
            self.assertTrue(win_identity.read_window_property(hwnd, "RelaunchIconResource").endswith(".ico,0"))
            command = win_identity.read_window_property(hwnd, "RelaunchCommand")
            self.assertIn("pythonw.exe", command)
            self.assertTrue(command.rstrip('"').endswith(("app.py", "doxa_launcher.pyw")))
        finally:
            root.destroy()

    def test_shortcut_gets_doxa_app_id(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as folder:
            lnk = Path(folder) / "Doxa test.lnk"
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
                            "$s.TargetPath='C:\Windows\notepad.exe'; $s.Save()"], check=True, timeout=60)
            self.assertEqual(win_identity.shortcut_app_id(lnk), "")
            self.assertTrue(win_identity.set_shortcut_app_id(lnk))
            self.assertEqual(win_identity.shortcut_app_id(lnk), "Doxa.Desktop")

    def test_missing_icon_is_a_no_op(self):
        self.assertFalse(win_identity.apply_to_window(123, Path("nope.ico")))


if __name__ == "__main__":
    unittest.main()
