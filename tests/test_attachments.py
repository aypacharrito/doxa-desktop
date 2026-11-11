"""Photos and documents from the phone: saved on the PC, and Claude can actually see/read them (view_file)."""
import base64
import io
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from forgemind import attachments
from forgemind.agent import DoxaTools, needs_tools
from forgemind.claude_brain import ClaudeBrain
from forgemind.cloud_brain import CloudBudget
from forgemind.phone_bridge import PhoneError
from forgemind.phone_delegate import AppPhoneDelegate
from test_agent import FakeClient, text_event, turn


def png(size=(3000, 2000)):
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


class SaveTests(unittest.TestCase):
    def test_saved_in_the_inbox_with_a_safe_unique_name(self):
        with tempfile.TemporaryDirectory() as folder:
            now = datetime(2026, 11, 9, 14, 5, 7)
            data = base64.b64encode(png()).decode()
            first = attachments.save_upload("../../evil\\name<>.png", data, Path(folder), now)
            second = attachments.save_upload("../../evil\\name<>.png", data, Path(folder), now)
            self.assertEqual(Path(first["path"]).parent, Path(folder) / "2026-11-09")
            self.assertTrue(first["name"].startswith("140507 ") and first["name"].endswith(".png"))
            self.assertNotIn("..", first["name"])
            self.assertNotEqual(first["path"], second["path"])
            self.assertEqual(first["kind"], "image")
            self.assertEqual(first["tag"], f"[Attached file: {first['path']}]")
            self.assertEqual(attachments.attached_paths("look " + first["tag"]), [first["path"]])
            with self.assertRaises(ValueError):
                attachments.save_upload("x.pdf", "not base64!!", Path(folder))
            with self.assertRaises(ValueError):
                attachments.save_upload("x.pdf", "", Path(folder))

    def test_phone_upload_errors_are_plain_400s(self):
        delegate = AppPhoneDelegate(SimpleNamespace())
        with self.assertRaises(PhoneError) as caught:
            delegate.upload("x.png", "%%%")
        self.assertEqual(caught.exception.status, 400)


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_photos_become_images_claude_can_see(self):
        path = self.root / "car.png"
        path.write_bytes(png())
        blocks = attachments.view_blocks(str(path))
        self.assertEqual(blocks[0]["type"], "image")
        image = Image.open(io.BytesIO(base64.b64decode(blocks[0]["source"]["data"])))
        self.assertLessEqual(max(image.size), attachments.MAX_SIDE)

    def test_documents_become_text(self):
        docx = self.root / "policy.docx"
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", "<w:document><w:p><w:t>Liability 100/300</w:t></w:p></w:document>")
        self.assertIn("Liability 100/300", attachments.view_blocks(str(docx)))
        note = self.root / "notes.txt"
        note.write_text("VIN 1HGCM", "utf-8")
        self.assertEqual(attachments.view_blocks(str(note)), "VIN 1HGCM")
        with self.assertRaises(ValueError):
            attachments.view_blocks(str(self.root / "missing.pdf"))

    def test_the_tool_hands_claude_the_image_blocks(self):
        path = self.root / "id.jpg"
        Image.new("RGB", (40, 40)).save(path, "JPEG")
        tools = DoxaTools(SimpleNamespace())
        self.assertIn("view_file", {s["name"] for s in tools.specs})
        self.assertEqual(tools.execute("view_file", {"path": str(path)})[0]["type"], "image")
        self.assertTrue(needs_tools(f"what's in this? [Attached file: {path}]"))  # goes to Claude with tools

        (self.root / "anthropic-key.dpapi").write_bytes(b"x")
        use = SimpleNamespace(type="tool_use", id="t1", name="view_file", input={"path": str(path)})
        client = FakeClient([turn("tool_use", [use]), turn("end_turn", [], [text_event("A black square.")])])
        claude = ClaudeBrain(self.root, CloudBudget(self.root / "b.sqlite3", 2000), client_factory=lambda: client)
        out = "".join(claude.agent_stream("sys", [{"role": "user", "content": "look"}], tools))
        self.assertEqual(out, "A black square.")
        result = client.calls[1]["messages"][-1]["content"][0]
        self.assertEqual(result["content"][0]["type"], "image")  # a list of blocks, not the text of a list


if __name__ == "__main__":
    unittest.main()


class LaptopPaperclipTests(unittest.TestCase):
    def test_a_picked_file_is_copied_to_the_inbox_and_tagged(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "dec page.pdf"
            src.write_bytes(b"%PDF-1.4 fake")
            saved = attachments.save_file(str(src), Path(folder) / "inbox", datetime(2026, 11, 9, 20, 1, 2))
            self.assertTrue(Path(saved["path"]).is_file())
            self.assertTrue(src.is_file())                       # the original stays where it was
            self.assertEqual(saved["tag"], f"[Attached file: {saved['path']}]")
            with self.assertRaises(ValueError):
                attachments.save_file(str(Path(folder) / "missing.pdf"))


class RobotArtTests(unittest.TestCase):
    def test_art_is_made_only_for_islands_without_a_picture_and_counted_in_the_budget(self):
        import threading
        from forgemind import hq_art
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "stores.png").write_bytes(b"x")              # already has a picture
            png = base64.b64encode(b"\x89PNG fake").decode()
            calls, settled, done = [], [], threading.Event()

            class Response:
                ok, status_code = True, 200

                def json(self):
                    return {"data": [{"b64_json": png}]}

            class Transport:
                @staticmethod
                def post(url, timeout, headers, json):
                    calls.append(json["prompt"])
                    return Response()

            class Budget:
                def reserve(self, cents):
                    return "id"

                def settle(self, ident, state, usd):
                    settled.append(usd)

            maker = hq_art.ArtMaker(lambda: "sk-test", Budget(), root, notify=lambda t: done.set(), transport=Transport)
            self.assertNotIn("stores", maker.missing())
            message = maker.start()
            self.assertIn("OpenAI budget", message)
            self.assertTrue(done.wait(5))
            self.assertEqual(len(calls), len(hq_art.ROBOTS) - 1)
            self.assertTrue(all("original" in p.lower() for p in calls))   # never copies an existing character
            self.assertEqual(maker.missing(), [])
            self.assertEqual(sum(settled), hq_art.COST_USD * len(calls))
            self.assertIn("Every island already has its robot portrait", maker.start())

    def test_no_openai_means_a_plain_message(self):
        from forgemind import hq_art
        with tempfile.TemporaryDirectory() as folder:
            def missing_key():
                raise ValueError("Connect ChatGPT (OpenAI) in Settings → AI brains first.")
            maker = hq_art.ArtMaker(missing_key, None, Path(folder))
            with self.assertRaisesRegex(ValueError, "Connect ChatGPT"):
                maker.start()
            self.assertFalse(maker.running)


class RobotArtErrorTests(unittest.TestCase):
    def test_the_real_reason_is_shown_and_a_model_problem_tries_the_next_model(self):
        import threading
        from forgemind import hq_art
        with tempfile.TemporaryDirectory() as folder:
            png = base64.b64encode(b"\x89PNG fake").decode()
            calls, done = [], threading.Event()

            class Response:
                def __init__(self, ok, status, body):
                    self.ok, self.status_code, self.body = ok, status, body

                def json(self):
                    return self.body

            class Transport:
                @staticmethod
                def post(url, timeout, headers, json):
                    calls.append(json["model"])
                    if json["model"] == "gpt-image-1":
                        return Response(False, 400, {"error": {"message": "The model gpt-image-1 is not available to your organization."}})
                    return Response(True, 200, {"data": [{"b64_json": png}]})

            budget = type("B", (), {"reserve": lambda self, c: "id", "settle": lambda self, *a: None})()
            maker = hq_art.ArtMaker(lambda: "sk-test", budget, Path(folder), notify=lambda t: done.set(), transport=Transport)
            maker.start()
            self.assertTrue(done.wait(5))
            self.assertEqual(calls[:2], ["gpt-image-1", "gpt-image-1-mini"])   # switched once, then kept the working model
            self.assertNotIn("gpt-image-1", calls[2:])
            self.assertEqual(maker.missing(), [])

    def test_a_billing_problem_stops_at_once_with_openais_words(self):
        import threading
        from forgemind import hq_art
        with tempfile.TemporaryDirectory() as folder:
            done, calls = threading.Event(), []

            class Response:
                ok, status_code = False, 400

                def json(self):
                    return {"error": {"message": "Billing hard limit has been reached."}}

            class Transport:
                @staticmethod
                def post(url, timeout, headers, json):
                    calls.append(1)
                    return Response()

            budget = type("B", (), {"reserve": lambda self, c: "id", "settle": lambda self, *a: None})()
            maker = hq_art.ArtMaker(lambda: "sk-test", budget, Path(folder), notify=lambda t: done.set(), transport=Transport)
            maker.start()
            self.assertTrue(done.wait(5))
            self.assertEqual(len(calls), 1)                                   # not 11 identical failures
            self.assertIn("Billing hard limit has been reached", maker.status)


class FigureArtTests(unittest.TestCase):
    def test_3d_figures_start_once_by_themselves_after_the_portraits_with_transparent_backgrounds(self):
        import threading
        from forgemind import hq_art
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            png = base64.b64encode(b"\x89PNG fake").decode()
            bodies, done = [], threading.Event()

            class Response:
                ok, status_code = True, 200

                def json(self):
                    return {"data": [{"b64_json": png}]}

            class Transport:
                @staticmethod
                def post(url, timeout, headers, json):
                    bodies.append(json)
                    return Response()

            budget = type("B", (), {"reserve": lambda self, c: "id", "settle": lambda self, *a: None})()
            maker = hq_art.ArtMaker(lambda: "sk-test", budget, root, notify=lambda t: done.set(), transport=Transport)
            self.assertIsNone(maker.auto_tick())                    # portraits still missing: not yet
            for key in hq_art.ROBOTS:
                (root / f"{key}.png").write_bytes(b"x")
            self.assertIn("3D figures", maker.auto_tick())
            self.assertTrue(done.wait(5))
            self.assertEqual(len(bodies), len(hq_art.ROBOTS))
            self.assertTrue(all(b["background"] == "transparent" and b["model"] != "dall-e-3" for b in bodies))
            self.assertEqual(set(maker.figures()), set(hq_art.ROBOTS))
            self.assertEqual(maker.figure("prime"), b"\x89PNG fake")
            self.assertIsNone(maker.figure("../secret"))
            (root / "figures" / "stores.png").unlink()              # a missing one is never re-bought by itself
            self.assertIsNone(maker.auto_tick())
            self.assertEqual(maker.missing("portrait"), [])          # the figures folder isn't counted as a portrait
