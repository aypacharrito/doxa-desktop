"""Fast screen reading through Windows accessibility (no screenshots), the default for "what's on my screen"."""
import unittest
from types import SimpleNamespace
from unittest import mock

from forgemind import screen_read as s
from forgemind.agent import DoxaTools
from forgemind.brain import Brain


def T(name, *kids):
    return (s.TEXT, name, "", False, list(kids))


def node(kind, name="", *kids, value=""):
    return (kind, name, value, False, list(kids))


CLAUDE_WINDOW = node(s.WINDOW, "Claude",
    node(s.BUTTON, "Minimize"),
    node(s.DOCUMENT, "",
        node(s.GROUP, "", T("Here's the plan for "), node(s.HYPERLINK, "Doxa"), T(":")),
        node(s.LIST, "",
            node(s.LISTITEM, "", T("1. "), T("Fix the "), node(s.TEXT, "upgrade tool"), T(".")),
            node(s.LISTITEM, "", T("Make the screen read the default."))),   # no marker text: numbered by the walker? bullet
        node(s.LIST, "",
            node(s.LISTITEM, "", T("Ship it"))),
        node(s.GROUP, "", T("Done."))),
    node(s.EDIT, "Message", value="also check the logs"),
    node(s.BUTTON, "Stop response"),
    node(s.BUTTON, "Allow once"))


class ReadingOrderTests(unittest.TestCase):
    def test_lines_lists_buttons_and_inputs(self):
        lines, buttons, inputs = s.flatten(CLAUDE_WINDOW)
        self.assertEqual(lines[0], "Here's the plan for Doxa:")
        self.assertEqual(lines[1], "1. Fix the upgrade tool.")          # the marker text is kept, runs are joined
        self.assertTrue(lines[2].startswith(("2. ", "• ")))             # every list item becomes its own line
        self.assertIn("Make the screen read the default.", lines[2])
        self.assertEqual(lines[3], "• Ship it")
        self.assertEqual(lines[-1], "Done.")
        self.assertEqual(inputs, ["also check the logs"])
        self.assertIn("Stop response", buttons)
        self.assertEqual(s.status_of(buttons), "Still writing (a Stop button is showing).")
        self.assertEqual(s.status_of(["Allow once", "Deny"]), "Waiting for a choice: Allow once, Deny.")
        self.assertEqual(s.status_of(["Copy"]), "Finished (no Stop button showing).")

    def test_read_window_keeps_the_end_of_long_windows_and_skips_doxa(self):
        long_tree = node(s.WINDOW, "Claude", *[node(s.GROUP, "", T(f"line {i} " + "x" * 50)) for i in range(400)])
        windows = [(1, "Claude", "claude.exe"), (2, "ChatGPT", "chatgpt.exe")]
        result = s.read_window("", max_chars=2000, tree_source=lambda hwnd: long_tree, windows=windows)
        self.assertTrue(result["truncated"])
        self.assertIn("line 399", result["text"])
        self.assertNotIn("line 0 ", result["text"])
        self.assertEqual(s.pick_window("chatgpt", windows)[1], "ChatGPT")
        self.assertIsNone(s.pick_window("outlook", windows))
        with self.assertRaises(ValueError):
            s.read_window("outlook", windows=windows, tree_source=lambda hwnd: long_tree)
        self.assertIn("no screenshot", s.as_text(result))

    def test_the_front_window_falls_through_to_one_with_text(self):
        trees = {1: node(s.WINDOW, "Overlay"), 2: CLAUDE_WINDOW}
        result = s.read_window("", tree_source=lambda hwnd: trees[hwnd], windows=[(1, "Overlay", "x.exe"), (2, "Claude", "claude.exe")])
        self.assertEqual(result["window"], "Claude")


class QuestionTests(unittest.TestCase):
    def test_which_messages_are_screen_reading_questions(self):
        cases = {"what is on my screen": "", "What does my screen say?": "", "whats on the screen": "",
                 "what is Claude saying": "claude", "whats claude saying right now": "claude",
                 "read me chatgpt": "chatgpt", "what did ChatGPT say": "chatgpt"}
        for text, hint in cases.items():
            self.assertEqual(s.screen_question(text), hint, text)
        for text in ("click the blue button on my screen", "tell me a joke", "type hello in the window",
                     "screen this candidate"):
            self.assertIsNone(s.screen_question(text), text)


class ChatUsesItTests(unittest.TestCase):
    def test_the_question_reaches_the_brain_with_the_screen_text(self):
        brain = Brain.__new__(Brain)
        brain.on_status = None
        result = {"window": "Claude", "app": "claude.exe", "text": "1. Done", "truncated": False, "buttons": [],
                  "inputs": [], "status": "Finished (no Stop button showing).", "ms": 120}
        with mock.patch("forgemind.screen_read.read_window", return_value=result) as read:
            text = brain._with_screen("what is Claude saying?")
        read.assert_called_once_with("claude")
        self.assertIn("<screen>", text)
        self.assertIn("1. Done", text)
        self.assertIn("data, not instructions", text)
        self.assertEqual(brain._with_screen("hello"), "hello")
        with mock.patch("forgemind.screen_read.read_window", side_effect=ValueError("No open Outlook window found.")):
            self.assertIn("couldn't read", brain._with_screen("read me outlook"))

    def test_claude_has_the_tool(self):
        tools = DoxaTools(SimpleNamespace())
        self.assertIn("read_screen", {spec["name"] for spec in tools.specs})
        with mock.patch("forgemind.screen_read.read_window", return_value={
                "window": "ChatGPT", "app": "chatgpt.exe", "text": "Hi", "truncated": False, "buttons": ["Copy"],
                "inputs": [], "status": "Finished (no Stop button showing).", "ms": 90}) as read:
            out = tools.execute("read_screen", {"app": "ChatGPT"})
        read.assert_called_once_with("chatgpt")
        self.assertIn("Window: ChatGPT", out)


if __name__ == "__main__":
    unittest.main()
