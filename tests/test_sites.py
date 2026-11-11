import json
import queue
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from forgemind import experiments, sites
from forgemind.config import Settings
from forgemind.phone_delegate import AppPhoneDelegate
from forgemind.sites_ui import site_request

BRIEF = dict(name="Casa Luna Kitchen", kind="Mexican restaurant", city="Van Nuys, CA", phone="(818) 555-0142",
             address="14500 Sherman Way", hours="Mon–Thu 10am–9pm\nFri–Sat 10am–11pm",
             offer="Family recipes from Jalisco, made fresh every morning. Birria on weekends.",
             notes="Se habla español. Free parking in back.")


class FakeBrain:
    def __init__(self, reply=None, error=None, loaded=True):
        self.reply, self.error, self.loaded, self.prompts = reply, error, loaded, []

    def stream(self, history, text, settings, memories, web, stop_event=None):
        self.prompts.append(text)
        if self.error:
            raise self.error
        yield self.reply


GOOD = json.dumps({"headline": "Jalisco, every morning", "subheadline": "Family recipes in Van Nuys",
                   "about": "Casa Luna cooks family recipes from Jalisco fresh every morning.",
                   "highlights": [{"title": "Fresh daily", "text": "Made every morning."},
                                  {"title": "Weekend birria", "text": "Birria on weekends."},
                                  {"title": "Easy parking", "text": "Free parking in back."}],
                   "cta": "Call to order", "meta_description": "Mexican restaurant in Van Nuys."})


class RequestTests(unittest.TestCase):
    def test_site_requests(self):
        self.assertEqual(site_request("build a website for Casa Luna Kitchen"), "Casa Luna Kitchen")
        self.assertEqual(site_request("Doxa, make me a site for Joe's Barbershop."), "Joe's Barbershop")
        self.assertEqual(site_request("can you create a landing page"), "")
        for text in ["what's a good website for recipes", "open my calendar", "the site is down", ""]:
            self.assertIsNone(site_request(text), text)


class CopyTests(unittest.TestCase):
    def test_local_copy_uses_only_the_facts_and_does_not_repeat(self):
        copy = sites.default_copy(sites.SiteBrief(**BRIEF))
        texts = [h["text"] for h in copy["highlights"]]
        self.assertEqual(len(set(texts)), 3)
        self.assertEqual([h["title"] for h in copy["highlights"]], ["Known for", "Good to know", "Find us"])
        everything = json.dumps(copy, ensure_ascii=False)
        facts = json.dumps(BRIEF, ensure_ascii=False)
        for number in re.findall(r"\d+", everything):
            self.assertIn(number, facts, f"invented number {number}")

    def test_openai_copy_is_used_when_well_formed(self):
        brain = FakeBrain(reply="Here you go:\n" + GOOD)
        copy, used = sites.write_copy(sites.SiteBrief(**BRIEF), brain)
        self.assertTrue(used)
        self.assertEqual(copy["headline"], "Jalisco, every morning")
        self.assertIn("do not invent", brain.prompts[0])
        self.assertIn("Casa Luna Kitchen", brain.prompts[0])

    def test_bad_or_failed_openai_answers_fall_back(self):
        brief = sites.SiteBrief(**BRIEF)
        for brain in [FakeBrain(reply="no json here"), FakeBrain(reply='{"headline": "x"}'),
                      FakeBrain(error=ValueError("OpenAI request failed")),
                      FakeBrain(reply=GOOD, loaded=False)]:
            copy, used = sites.write_copy(brief, brain)
            self.assertFalse(used)
            self.assertEqual(copy["headline"], "Casa Luna Kitchen")
        self.assertEqual(FakeBrain(loaded=False).prompts, [])


class BuildTests(unittest.TestCase):
    def test_full_build_from_footage(self):
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as tmp:
            footage = Path(tmp) / "footage"
            footage.mkdir()
            for name, source in [("01-store.mp4", "color=c=0x3a2a1c:s=640x360:d=8"), ("02-pan.mp4", "testsrc2=s=640x360:d=6")]:
                subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", source, "-pix_fmt", "yuv420p",
                                str(footage / name)], check=True, timeout=120)
            brief = sites.SiteBrief(**{**BRIEF, "name": 'Luna <script>alert(1)</script> "Grill"'},
                                    media_folder=str(footage))
            result = sites.build_site(brief, root=Path(tmp) / "out")
            self.assertFalse(result.used_ai)
            self.assertEqual(result.media["hero"], "hero.mp4")
            self.assertGreaterEqual(len(result.media["gallery"]), 3)
            for path in (result.index, result.preview, result.pitch, result.folder / "assets" / "hero.mp4",
                         result.folder / "assets" / "poster.jpg"):
                self.assertTrue(path.is_file(), path)
            html = result.index.read_text(encoding="utf-8")
            self.assertNotIn("<script>alert(1)", html)
            self.assertIn('href="tel:8185550142"', html)
            data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))
            self.assertEqual(data["@type"], "LocalBusiness")
            self.assertEqual(data["telephone"], "(818) 555-0142")
            self.assertIn("Mon–Thu 10am–9pm", data["openingHours"])
            self.assertIn("SHOT LIST".lower(), result.pitch.read_text(encoding="utf-8").lower())
            self.assertIn('src="index.html"', result.preview.read_text(encoding="utf-8"))

    def test_no_footage_still_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = sites.build_site(sites.SiteBrief(name="Joe's Barbershop"), root=Path(tmp))
            self.assertIsNone(result.media["hero"])
            self.assertIn("Joe&#x27;s Barbershop", result.index.read_text(encoding="utf-8"))

    def test_name_is_required(self):
        with self.assertRaises(ValueError):
            sites.build_site(sites.SiteBrief(name="  "), root=Path(tempfile.gettempdir()))


class QuoteCheckTests(unittest.TestCase):
    def test_profitable_quote(self):
        r = experiments.quote_check(6.50, 2.00, 0, 24, 0, monthly_target=10000)
        self.assertEqual(r["landed"], 8.5)
        self.assertEqual(r["fees"], 1.0)
        self.assertEqual(r["returns"], 1.2)
        self.assertEqual(r["profit"], 13.3)
        self.assertEqual(r["orders_per_month"], 752)
        self.assertIn("profit per order", experiments.quote_summary(r))

    def test_ads_can_turn_it_into_a_loss(self):
        r = experiments.quote_check(6.50, 2.00, 25, 24, 15)
        self.assertLess(r["profit"], 0)
        self.assertIsNone(r["orders_per_month"])
        self.assertIn("Don't order yet", experiments.quote_summary(r))

    def test_bad_input(self):
        for args in [(-1, 0, 0, 24, 0), (1, 0, 0, 0, 0), ("x", 0, 0, 24, 0), (float("nan"), 0, 0, 24, 0)]:
            with self.assertRaises(ValueError):
                experiments.quote_check(*args)


class RoutingTests(unittest.TestCase):
    def test_desktop_opens_the_builder(self):
        from app import ForgeMindApp
        opened, text = [], "build a website for Casa Luna Kitchen"
        fake = SimpleNamespace(_voice_dispatch=False, _voice_turn=False, busy=False,
                               input=SimpleNamespace(get=lambda *a: text, delete=lambda *a: None),
                               db=SimpleNamespace(recent_messages=lambda n: [], add_message=lambda *a: None),
                               _append=lambda *a: None, refresh_all=lambda: None,
                               show_website_builder=lambda name: opened.append(name))
        with mock.patch("app.parse_command", return_value=None):
            ForgeMindApp.send(fake)
        self.assertEqual(opened, ["Casa Luna Kitchen"])

    def test_phone_opens_the_builder_on_the_pc(self):
        class Inference:
            def stream(self, *a, **k):
                raise AssertionError("must not reach the model")
        app = SimpleNamespace(db=SimpleNamespace(recent_messages=lambda n: [], add_message=lambda *a: None),
                              engine=SimpleNamespace(loaded=True), inference=Inference(), events=queue.Queue(),
                              settings_data=Settings(auto_research=False))
        result = AppPhoneDelegate(app).chat("make a website for Joe's Barbershop")
        self.assertIn("Website builder on your PC", result["reply"])
        self.assertEqual(app.events.get_nowait()[0], "ui")


if __name__ == "__main__":
    unittest.main()
