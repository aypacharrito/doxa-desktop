from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from forgemind.computer import ComputerTask, Controls, DesktopBackend, DesktopLease, Interrupted, validate_action


class FakeDesktop:
    def __init__(self, controls, changing=True):
        self.actions = []
        self.controls = controls
        self.changing = changing
        self.released = False

    def capture(self, path):
        path.write_bytes(str(len(self.actions) if self.changing else 0).encode())
        return (1280, 720)

    def execute(self, action, size):
        self.controls.check()
        self.actions.append(action)

    def release(self):
        self.released = True


class FakeVision:
    def __init__(self, actions, verified=True):
        self.actions = iter(actions)
        self.verified = verified

    def next_action(self, *_args):
        return next(self.actions)

    def verify(self, *_args):
        return {"completed": self.verified, "evidence": "Expected text is visible"}


class ComputerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temporary.name)
        self.controls = Controls()
        self.backend = FakeDesktop(self.controls)

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, vision, notify=None):
        return ComputerTask("Write a greeting in the test editor", self.controls, self.backend,
                            vision, self.root, notify)

    def test_action_and_completion_require_observation_and_verifier(self):
        runner = self.runner(FakeVision([{"action": "type", "text": "Hello"}, {"action": "done"}]))
        result = runner.run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["steps"], 1)
        self.assertEqual(self.backend.actions[0]["text"], "Hello")
        self.assertTrue(self.backend.released)
        self.assertEqual(json.loads(Path(result["report"]).read_text())["status"], "completed")
        self.assertTrue((runner.run_dir / "actions.jsonl").is_file())

    def test_model_claim_alone_cannot_mark_completed(self):
        result = self.runner(FakeVision([{"action": "done"}] * 3, verified=False)).run()
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("not visually verified", result["reason"])
        self.assertFalse(self.backend.actions)

    def test_stop_during_inference_prevents_next_input(self):
        vision = FakeVision([])
        def generate(*_args):
            self.controls.cancel()
            return {"action": "click", "x": 50, "y": 50}
        vision.next_action = generate
        result = self.runner(vision).run()
        self.assertEqual(result["status"], "stopped")
        self.assertFalse(self.backend.actions)

    def test_preexisting_stop_never_captures_or_sends_input(self):
        self.controls.cancel()
        self.backend.capture = Mock(side_effect=AssertionError("Should not capture"))
        self.assertEqual(self.runner(FakeVision([])).run()["status"], "stopped")

    def test_owner_pause_and_resume_discards_stale_inference(self):
        vision = FakeVision([{"action": "needs_input", "reason": "Fresh screen needed"}])
        original = vision.next_action
        calls = []
        def generate(*args):
            calls.append(1)
            if len(calls) == 1:
                self.controls.pause()
                self.controls.resume()
                return {"action": "click", "x": 50, "y": 50}
            return original(*args)
        vision.next_action = generate
        self.assertEqual(self.runner(vision).run()["status"], "needs_input")
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.backend.actions)

    def test_paused_task_does_not_act_until_explicit_resume(self):
        self.controls.pause()
        paused = threading.Event()
        def notify(text):
            if text.startswith("paused"):
                paused.set()
        runner = self.runner(FakeVision([{"action": "done"}]), notify)
        thread = threading.Thread(target=runner.run)
        thread.start()
        self.assertTrue(paused.wait(2))
        self.assertFalse(self.backend.actions)
        self.controls.cancel()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(runner.state["status"], "stopped")

    def test_no_six_step_ceiling_when_progress_continues(self):
        actions = [{"action": "type", "text": str(i)} for i in range(8)] + [{"action": "done"}]
        result = self.runner(FakeVision(actions)).run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["steps"], 8)

    def test_repeated_no_progress_reports_specific_reason(self):
        self.backend.changing = False
        action = {"action": "click", "x": 55, "y": 55}
        result = self.runner(FakeVision([action] * 8)).run()
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("without progress", result["reason"])
        self.assertEqual(len(self.backend.actions), 3)

    def test_missing_login_is_not_bypassed_or_claimed_complete(self):
        result = self.runner(FakeVision([{"action": "needs_input", "reason": "Sign into Google yourself"}])).run()
        self.assertEqual(result["reason"], "Sign into Google yourself")
        self.assertFalse(self.backend.actions)

    def test_malformed_actions_never_reach_desktop(self):
        result = self.runner(FakeVision([{"action": "click", "x": -3, "y": 20}] * 3)).run()
        self.assertEqual(result["status"], "needs_input")
        self.assertFalse(self.backend.actions)

    def test_corner_emergency_stop(self):
        class FailSafeException(Exception):
            pass
        self.backend.execute = Mock(side_effect=FailSafeException())
        result = self.runner(FakeVision([{"action": "type", "text": "x"}])).run()
        self.assertEqual(result["status"], "stopped")
        self.assertIn("corner", result["reason"])

    def test_physical_input_pauses_but_injected_input_does_not(self):
        self.controls.armed = True
        self.controls.mouse_filter(0x200, SimpleNamespace(flags=1))
        self.assertFalse(self.controls.paused.is_set())
        self.controls.mouse_filter(0x200, SimpleNamespace(flags=0))
        self.assertTrue(self.controls.paused.is_set())
        self.controls.resume()
        self.controls.keyboard_filter(0x100, SimpleNamespace(flags=0x10, vkCode=65))
        self.assertFalse(self.controls.paused.is_set())
        self.controls.keyboard_filter(0x100, SimpleNamespace(flags=0, vkCode=65))
        self.assertTrue(self.controls.paused.is_set())

    def test_override_hotkey_keys_do_not_repause_resume(self):
        self.controls.armed = True
        for key in (0x11, 0x12, 0x7A, 0x7B):
            self.controls.keyboard_filter(0x100, SimpleNamespace(flags=0, vkCode=key))
        self.assertFalse(self.controls.paused.is_set())

    def test_physical_mouse_corner_stops_instead_of_only_pausing(self):
        self.controls.armed = True
        self.controls.screen_size = (2560, 1440)
        self.controls.mouse_filter(0x200, SimpleNamespace(flags=0, pt=SimpleNamespace(x=0, y=0)))
        self.assertTrue(self.controls.stop.is_set())

    def test_invalid_json_values_and_coordinates_are_rejected(self):
        for action in [None, {"action": "shell"}, {"action": "click", "x": True, "y": 0},
                       {"action": "click", "x": 1280, "y": 0},
                       {"action": "wait", "seconds": float("nan")},
                       {"action": "hotkey", "keys": "ctrl+l"},
                       {"action": "scroll", "x": 2, "y": 2, "amount": 100},
                       {"action": "drag", "x": 2, "y": 2, "to_x": -1, "to_y": 2}]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(action, (1280, 720))

    def native_backend(self):
        backend = DesktopBackend.__new__(DesktopBackend)
        backend.controls = self.controls
        backend.gui = Mock()
        backend.gui.FAILSAFE = True
        backend.gui.KEYBOARD_KEYS = ["ctrl", "l", "enter"]
        backend.held = []
        backend.screen_size = (2560, 1440)
        backend.protected_rect = (0, 0, 80, 80)
        return backend

    def test_screen_coordinate_scaling_and_controller_protection(self):
        backend = self.native_backend()
        self.assertEqual(backend.point({"x": 640, "y": 360}, (1280, 720)), (1280, 720))
        with self.assertRaises(ValueError):
            backend.point({"x": 20, "y": 20}, (1280, 720))

    def test_controller_log_changes_do_not_count_as_target_progress(self):
        from PIL import Image, ImageDraw
        backend = self.native_backend()
        path = self.root / "fixture.png"
        values = []
        for color in ("red", "blue"):
            image = Image.new("RGB", (1280, 720), "white")
            ImageDraw.Draw(image).rectangle((5, 5, 30, 30), fill=color)
            image.save(path)
            values.append(backend.fingerprint(path, image.size))
        self.assertEqual(values[0], values[1])
        ImageDraw.Draw(image).rectangle((500, 200, 700, 400), fill="black")
        image.save(path)
        self.assertNotEqual(values[1], backend.fingerprint(path, image.size))

    def test_click_is_cancelled_if_owner_moves_during_move_to(self):
        backend = self.native_backend()
        backend.gui.moveTo.side_effect = lambda *_: self.controls.pause()
        with self.assertRaises(Interrupted):
            backend.execute({"action": "click", "x": 100, "y": 100}, (1280, 720))
        backend.gui.click.assert_not_called()

    def test_held_modifier_released_on_interrupted_hotkey(self):
        backend = self.native_backend()
        backend.gui.keyDown.side_effect = lambda *_: self.controls.cancel()
        with self.assertRaises(Interrupted):
            backend.execute({"action": "hotkey", "keys": ["ctrl", "l"]}, (1280, 720))
        backend.gui.keyUp.assert_called_once_with("ctrl")
        self.assertTrue(backend.gui.FAILSAFE)
        self.assertFalse(backend.held)

    def test_capture_failure_is_recorded_not_claimed_complete(self):
        self.backend.capture = Mock(side_effect=RuntimeError("Screen locked"))
        result = self.runner(FakeVision([])).run()
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("Screen locked", result["reason"])

    def test_completion_cannot_override_stop_during_verification(self):
        vision = FakeVision([{"action": "done"}])
        def verify(*_):
            self.controls.cancel()
            return {"completed": True, "evidence": "Visible"}
        vision.verify = verify
        self.assertEqual(self.runner(vision).run()["status"], "stopped")

    def test_application_close_waits_for_input_cleanup(self):
        from app import ForgeMindApp
        fake = SimpleNamespace(_closing=False, _stop_evolution=threading.Event(), _research_session=None,
                               _cancel_answer=threading.Event(), voice=SimpleNamespace(disable=Mock()),
                               _computer_controls=self.controls, _set_status=Mock(),
                               after=Mock(), _on_close=Mock(), destroy=Mock(),
                               settings_data=SimpleNamespace(backup_folder=""))
        ForgeMindApp._on_close(fake)
        self.assertTrue(fake._closing)
        self.assertTrue(fake._cancel_answer.is_set())
        fake.voice.disable.assert_called_once()
        self.assertTrue(self.controls.stop.is_set())
        fake.destroy.assert_not_called()
        fake.after.assert_called_once()
        fake._computer_controls = None
        ForgeMindApp._on_close(fake)
        fake.destroy.assert_called_once()

    def test_application_close_waits_for_training_checkpoint(self):
        from app import ForgeMindApp
        session = SimpleNamespace(stop=Mock(), tick=Mock(), active=True)
        fake = SimpleNamespace(_closing=False, _stop_evolution=threading.Event(),
                               _cancel_answer=threading.Event(), voice=SimpleNamespace(disable=Mock()),
                               _research_session=session, _computer_controls=None,
                               _set_status=Mock(), after=Mock(), _on_close=Mock(), destroy=Mock(),
                               settings_data=SimpleNamespace(backup_folder=""))
        ForgeMindApp._on_close(fake)
        session.stop.assert_called_once()
        session.tick.assert_called_once()
        fake.destroy.assert_not_called()
        fake.after.assert_called_once_with(250, fake._on_close)
        session.active = False
        ForgeMindApp._on_close(fake)
        self.assertIsNone(fake._research_session)
        fake.destroy.assert_called_once()

    @unittest.skipUnless(__import__("os").name == "nt", "Windows file lease")
    def test_only_one_desktop_task_can_hold_the_lease(self):
        with DesktopLease(self.root):
            with self.assertRaises(RuntimeError):
                with DesktopLease(self.root):
                    self.fail("Second controller obtained the same lease")
        with DesktopLease(self.root):
            pass


if __name__ == "__main__":
    unittest.main()
