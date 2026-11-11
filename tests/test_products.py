import json
import queue
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from forgemind import products
from forgemind.config import Settings
from forgemind.phone_delegate import AppPhoneDelegate
from forgemind.web import SearchResult

TODAY = datetime(2026, 11, 5, 9, 0)


def item(name, **extra):
    base = {"name": name, "why_now": "Rising in roundups [1]", "problem": "Messy paws", "audience": "Dog owners",
            "price_usd": 24.99, "landed_cost_usd": 5.0,
            "scores": {"wow": 8, "problem": 9, "margin": 8, "demo": 9, "saturation": 6, "shipping": 8},
            "hooks": ["Watch the mud disappear", "Your floors after a walk", "Dog owners need this"],
            "angle": "Muddy paw before/after", "risks": "Cheap plastic", "search_terms": "paw cleaner cup", "sources": [1]}
    base.update(extra)
    return base


def answer(*items):
    return "```json\n" + json.dumps({"products": list(items)}) + "\n```"


class FakeEngine:
    display_name = "Claude"
    loaded = True

    def __init__(self, text):
        self.text, self.calls = text, []

    def chat_stream(self, system, messages, stop_event=None, effort="low", max_tokens=4000):
        self.calls.append((system, messages, effort, max_tokens))
        yield from (self.text[i:i + 40] for i in range(0, len(self.text), 40))


class FakeBrain:
    def __init__(self, engine):
        self.engine = engine

    def clouds(self, settings):
        return [self.engine] if self.engine else []


def fake_search(query):
    if "fail" in query:
        raise RuntimeError("No results found.")
    return [SearchResult("Trending 2026", "https://example.com/trending", "snippet", "Paw cleaners are rising."),
            SearchResult("Dup", "https://example.com/trending", "dup", ""),
            SearchResult("Bad", "javascript:alert(1)", "x", "")]


class IntentTests(unittest.TestCase):
    def test_requests(self):
        cases = {
            "find winning products": "",
            "Find me some winning products for pets.": "pets",
            "hey doxa find winner products in the kitchen niche": "kitchen",
            "what should I sell": "",
            "start a product hunt": "",
            "research products to sell for gym lovers": "gym lovers",
            "find winning products for me": "",
            "Doxa, find viral products for dog owners to sell online": "dog owners",
        }
        for text, niche in cases.items():
            self.assertEqual(products.hunt_request(text), niche, text)

    def test_not_requests(self):
        for text in ("how do they find winner products?", "Hey Doxa how do I find winning products", "the product is winning",
                     "find me a lawyer", "build a website for Casa Luna", "start a quote for Ana Ruiz, auto"):
            self.assertIsNone(products.hunt_request(text), text)


class ParseTests(unittest.TestCase):
    sources = [{"title": "T", "url": "https://example.com/a", "text": "x"}]

    def test_ranks_validates_and_cites(self):
        weak = item("Weak gadget", scores={"wow": 2, "problem": 2, "margin": 2, "demo": 2, "saturation": 2, "shipping": 2})
        result = products.parse_products(answer(weak, item("Paw cleaner cup")), self.sources)
        self.assertEqual([p.name for p in result], ["Paw cleaner cup", "Weak gadget"])
        top = result[0]
        self.assertEqual(top.sources, ["https://example.com/a"])
        self.assertEqual(top.profit["markup"], 5.0)
        self.assertGreater(top.profit["profit"], 15)
        self.assertEqual(len(top.hooks), 3)
        self.assertIn("alibaba.com", top.links()["Alibaba"])

    def test_scores_clamped_and_bad_numbers_tolerated(self):
        odd = item("Odd one", price_usd="$29.99", landed_cost_usd="lots",
                   scores={"wow": 50, "problem": -3, "margin": "x"}, sources=[99, "zz"])
        p = products.parse_products(answer(odd), self.sources)[0]
        self.assertEqual(p.scores["wow"], 10)
        self.assertEqual(p.scores["problem"], 1)
        self.assertEqual(p.price, 29.99)
        self.assertEqual(p.profit, {})  # no cost estimate → no profit claim
        self.assertEqual(p.sources, [])

    def test_blocked_products_removed(self):
        result = products.parse_products(answer(item("Stanley tumbler dupe"), item("CBD gummies"),
                                                item("Mini vape pen"), item("Paw cleaner cup")), self.sources)
        self.assertEqual([p.name for p in result], ["Paw cleaner cup"])
        with self.assertRaises(products.HuntError):
            products.parse_products(answer(item("Nike slides")), self.sources)
        allowed = products.parse_products(answer(item("Mini massage gun"), item("Apple slicer"),
                                                 item("Knife sharpener"), item("Water gun")), self.sources)
        self.assertEqual(len(allowed), 4)
        self.assertEqual(len(products.parse_products(answer(item("Airsoft gun"), item("Paw cup")), self.sources)), 1)

    def test_duplicates_and_malformed_items(self):
        result = products.parse_products(answer(item("Paw cleaner cup"), item("paw cleaner cup"), "junk", {"name": ""}),
                                         self.sources)
        self.assertEqual(len(result), 1)

    def test_not_json(self):
        for text in ("Sorry, I can't.", '{"products": [', '{"items": []}', ""):
            with self.assertRaises(products.HuntError):
                products.parse_products(text, self.sources)

    def test_thin_margin_is_penalized(self):
        thin = item("Thin margin", landed_cost_usd=21.0)
        full = item("Full margin")
        result = {p.name: p for p in products.parse_products(answer(thin, full), self.sources)}
        self.assertLess(result["Thin margin"].score, result["Full margin"].score)


class GatherTests(unittest.TestCase):
    def test_failures_skipped_duplicates_and_bad_urls_dropped(self):
        sources = products.gather(["ok one", "fail two", "ok three"], search=fake_search)
        self.assertEqual([s["url"] for s in sources], ["https://example.com/trending"])
        self.assertIn("Paw cleaners", sources[0]["text"])

    def test_queries(self):
        general = products.queries_for("", TODAY)
        self.assertTrue(all("2026" in q for q in general))
        self.assertTrue(any("November" in q for q in general))
        self.assertTrue(products.queries_for("pets", TODAY)[0].startswith("trending pets"))

    def test_evidence_is_capped(self):
        many = [{"title": f"t{i}", "url": f"https://e.com/{i}", "text": "x" * 1800} for i in range(40)]
        self.assertLessEqual(len(products.evidence_text(many)), products.EVIDENCE_CHARS)


class HuntTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.store = products.HuntStore(self.root)

    def tearDown(self):
        self.dir.cleanup()

    def run_hunt(self, text, niche=""):
        engine = FakeEngine(text)
        result = products.hunt(FakeBrain(engine), Settings(), self.store, niche, search=fake_search,
                               folder=self.root / "out", today=TODAY)
        return engine, result

    def test_full_hunt_writes_report_and_history(self):
        engine, result = self.run_hunt(answer(item("Paw cleaner cup"), item("<script>alert(1)</script> lamp")), "pets")
        system, messages, effort, _ = engine.calls[0]
        self.assertIn("JSON only", system)
        self.assertIn("pets niche", messages[0]["content"])
        self.assertIn("Paw cleaners are rising", messages[0]["content"])
        self.assertEqual(effort, "medium")
        report = Path(result["report"])
        self.assertTrue(report.is_file())
        page = report.read_text("utf-8")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("How to find the winner", page)
        self.assertEqual(len(self.store.history()), 2)
        summary = products.chat_summary(result)
        self.assertIn("1. Paw cleaner cup", summary)
        self.assertIn("estimates, not proof", summary)

    def test_verdicts_feed_the_next_hunt(self):
        self.run_hunt(answer(item("Paw cleaner cup"), item("Sunset lamp")))
        history = self.store.history()
        self.store.mark(history[0]["id"], "winner", "3 videos over 50k")
        self.store.mark(history[1]["id"], "dud")
        engine, _ = self.run_hunt(answer(item("Car trash can")))
        prompt = engine.calls[0][1][0]["content"]
        self.assertIn("Paw cleaner cup: winner (3 videos over 50k)", prompt)
        self.assertIn("Sunset lamp: dud", prompt)
        self.assertIn("don't repeat these", prompt)
        with self.assertRaises(ValueError):
            self.store.mark(history[0]["id"], "bought")

    def test_needs_a_cloud_brain(self):
        with self.assertRaises(products.HuntError) as caught:
            products.hunt(FakeBrain(None), Settings(), self.store, search=fake_search, folder=self.root)
        self.assertIn("AI brains", str(caught.exception))

    def test_daily_once(self):
        self.assertTrue(self.store.auto_due("2026-11-05"))
        self.store.mark_auto("2026-11-05")
        self.assertFalse(self.store.auto_due("2026-11-05"))
        self.assertTrue(self.store.auto_due("2026-11-06"))

    def test_corrupt_history_starts_fresh(self):
        (self.root / "product-hunts.json").write_text("{nope", "utf-8")
        self.assertEqual(self.store.history(), [])


class RoutingTests(unittest.TestCase):
    def test_desktop_starts_a_hunt(self):
        from app import ForgeMindApp
        started, text = [], "find me winning products for pets"
        fake = SimpleNamespace(_voice_dispatch=False, _voice_turn=False, busy=False,
                               input=SimpleNamespace(get=lambda *a: text, delete=lambda *a: None),
                               db=SimpleNamespace(recent_messages=lambda n: [], add_message=lambda *a: None),
                               start_product_hunt=lambda t, niche: started.append(niche))
        with mock.patch("app.parse_command", return_value=None):
            ForgeMindApp.send(fake)
        self.assertEqual(started, ["pets"])

    def test_phone_starts_the_hunt_on_the_pc(self):
        class Inference:
            def stream(self, *a, **k):
                raise AssertionError("must not reach the model")
        app = SimpleNamespace(db=SimpleNamespace(recent_messages=lambda n: [], add_message=lambda *a: None),
                              engine=SimpleNamespace(loaded=True), inference=Inference(), events=queue.Queue(),
                              settings_data=Settings(auto_research=False))
        result = AppPhoneDelegate(app).chat("find winning products")
        self.assertIn("on your PC", result["reply"])
        self.assertEqual(app.events.get_nowait()[0], "ui")


if __name__ == "__main__":
    unittest.main()
