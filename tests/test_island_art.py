"""1.38.2: the Higgsfield island renders in HQ (forgemind/island_art.py, /api/team/island-art/<size>/<key>)."""
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from forgemind import island_art


def png(path, size=(3000, 1674), color=(40, 30, 90)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


class IslandArtTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_versions_find_originals_and_a_dropped_in_file_wins(self):
        png(self.root / "originals" / "stores.png")
        png(self.root / "originals" / "prime.png")
        png(self.root / "originals" / "unknown.png")  # not an island: ignored
        self.assertEqual(sorted(island_art.versions(self.root)), ["prime", "stores"])
        png(self.root / "stores.jpg", color=(200, 0, 0))
        self.assertEqual(island_art.source("stores", self.root).name, "stores.jpg")
        self.assertIsNone(island_art.source("../secrets", self.root))

    def test_web_sizes_are_jpegs_cached_per_version(self):
        png(self.root / "originals" / "trading.png")
        thumb = island_art.image("trading", "thumb", self.root)
        full = island_art.image("trading", "full", self.root)
        self.assertEqual(Image.open(io.BytesIO(thumb)).size[0], 900)
        self.assertEqual(Image.open(io.BytesIO(full)).size[0], 2560)
        self.assertEqual(Image.open(io.BytesIO(thumb)).format, "JPEG")
        cached = list((self.root / ".cache").glob("trading-thumb-*.jpg"))
        self.assertEqual(len(cached), 1)
        self.assertEqual(island_art.image("trading", "thumb", self.root), thumb)
        self.assertIsNone(island_art.image("trading", "huge", self.root))
        self.assertIsNone(island_art.image("lab", "thumb", self.root))

    def test_hq_page_loads_the_art_view_before_hq_js(self):
        web = Path(island_art.__file__).with_name("phone_web")
        html = (web / "hq.html").read_text("utf-8")
        self.assertLess(html.index("hqart.js"), html.index('src="hq.js"'))
        self.assertIn('id="view-toggle"', html)
        boot = (web / "hq3d-boot.js").read_text("utf-8")
        self.assertIn("const want = /[?&]3d\\b/.test(location.search) &&", boot)  # 3D only when asked for
        art = (web / "hqart.js").read_text("utf-8")
        for name in ("build(", "flyTo(", "overview(", "update(", "setIslandArt(", "setCrates(", "setArt(", "setFigure("):
            self.assertIn(name, art)
        self.assertIn("/api/team/island-art/", art)


if __name__ == "__main__":
    unittest.main()
