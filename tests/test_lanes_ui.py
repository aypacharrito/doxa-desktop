"""1.38.0: Chat | Work | Code switch and the ChatGPT-style home (message box in the middle until a chat starts)."""
import tkinter as tk
import unittest
from types import SimpleNamespace

from forgemind import jarvis_ui


class Stub(tk.Tk):
    """Just enough of Doxa's app for jarvis_ui.build: unknown show_*/run_* actions are no-ops."""

    def __getattr__(self, name):
        try:
            return super().__getattr__(name)
        except AttributeError:
            if name.startswith("_"):
                raise
            return lambda *a, **k: None


class FakeBrain:
    def __init__(self, local=True, paid=("Claude", "OpenAI", "Gemini"), free=()):
        self.local = SimpleNamespace(loaded=local)
        self.paid, self.free = paid, free

    def lane_brains(self, settings, lane):
        names = self.free if lane == "chat" else self.paid
        return [SimpleNamespace(display_name=n) for n in names]


class HomeTests(unittest.TestCase):
    """One window for the class: Doxa's images are made for the first Tk root, like in the real app."""

    @classmethod
    def setUpClass(cls):
        cls.app = app = Stub()
        app.withdraw()
        app.settings_data = SimpleNamespace(display_name="", lane="work", code_engine="auto")
        app.brain = FakeBrain()
        app.mode, app.busy, app.code_runner = "work", False, None
        app.code_folder_var = tk.StringVar(master=app)
        app.code_engine_var = tk.StringVar(master=app, value="auto")
        app.code_fresh_var = tk.BooleanVar(master=app)

        def set_mode(mode):
            app.mode = mode
            jarvis_ui.paint_mode(app, mode)
        app.set_mode = set_mode
        jarvis_ui.build(app)
        app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def setUp(self):
        self.app.brain = FakeBrain()
        jarvis_ui.show_hero(self.app)
        self.app.set_mode("work")

    def test_work_home_centers_the_box_and_names_the_ai(self):
        app = self.app
        self.assertEqual(app.hero_title.cget("text"), "What should we work on?")
        self.assertEqual(app._composer.winfo_manager(), "place")
        self.assertEqual(app.lane_pill.cget("text"), "Claude  +2 backup")
        self.assertIn("next one takes over", app.hero_sub.cget("text"))

    def test_chat_lane_says_on_your_pc_or_the_free_ai(self):
        app = self.app
        app.set_mode("chat")
        self.assertEqual(app.lane_pill.cget("text"), "On your PC")
        self.assertIn("on your PC", app.hero_sub.cget("text"))
        app.brain = FakeBrain(local=False, free=("OpenCode Go",))
        app.set_mode("chat")
        self.assertEqual(app.lane_pill.cget("text"), "OpenCode Go · free")
        app.brain = FakeBrain(paid=())
        app.set_mode("work")
        self.assertEqual(app.lane_pill.cget("text"), "No paid AI left")

    def test_box_docks_at_the_bottom_in_a_chat_and_in_code(self):
        app = self.app
        jarvis_ui.show_chat(app)
        self.assertEqual(app._composer.winfo_manager(), "grid")
        jarvis_ui.show_hero(app)
        self.assertEqual(app._composer.winfo_manager(), "place")
        app.set_mode("code")
        self.assertEqual(app._composer.winfo_manager(), "grid")
        self.assertEqual(app.lane_pill.cget("text"), "Codex · Claude Code")
        app.set_mode("work")
        self.assertEqual(app._composer.winfo_manager(), "place")


if __name__ == "__main__":
    unittest.main()
