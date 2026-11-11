"""Doxa HQ (phone_web/hq.html): served by the phone server, needs a key, accepts the PC's private per-start key."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from forgemind.phone_bridge import PhoneAccess, PhoneServer
from test_phone_access import FakeDelegate


class HQTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.access = PhoneAccess(Path(self.folder.name) / "phone.json")
        self.access.local_keys = {"pc-window-key-abcdefghijkl"}
        d = FakeDelegate()
        d.team_state = lambda: {"rooms": [{"key": "research", "room": "Research", "worker": "Nova", "about": "x"}],
                                "campaign": None, "counts": {}, "workers": {}, "busy": [], "waiting": []}
        self.created = []

        def character(key):
            from forgemind.phone_bridge import PhoneError
            if key != "edit":
                raise PhoneError(404, "No picture for that character.")
            return b"PNG fake", "image/png"
        d.team_character = character
        d.team_campaign = lambda *a: (self.created.append(a), {"ok": True, "id": "c1"})[1]
        self.server = PhoneServer(d, self.access)
        self.base = f"http://127.0.0.1:{self.server.start(port=0)}"

    def tearDown(self):
        self.server.stop()
        self.folder.cleanup()

    def get(self, path, key=None):
        request = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {key}"} if key else {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_page_files_are_served(self):
        for name, marker in (("/hq.html", b"Doxa HQ"), ("/hq.js", b"/api/team"), ("/hq.css", b".hq-floor"),
                             ("/hq.html", b'id="tour"'), ("/hq.js", b"flyTo"), ("/hq.css", b".hq-sign"),
                             ("/hq.html", b'id="campaign-form"'), ("/hq.js", b"/api/team/character/")):
            status, body = self.get(name)
            self.assertEqual(status, 200, name)
            self.assertIn(marker, body, name)

    def post(self, path, body, key):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_character_pictures_and_new_campaign_routes(self):
        pc = "pc-window-key-abcdefghijkl"
        self.assertEqual(self.get("/api/team/character/edit")[0], 401)
        status, body = self.get("/api/team/character/edit", pc)
        self.assertEqual((status, body), (200, b"PNG fake"))
        self.assertEqual(self.get("/api/team/character/writers", pc)[0], 404)
        status, body = self.post("/api/team/campaign", {"name": "Song", "goal": "1,000 saves"}, pc)
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertEqual(self.created[0][:2], ("Song", "1,000 saves"))
        self.assertEqual(self.post("/api/team/campaign", {"name": "Song", "goal": "x"}, "wrong-key-0000000000000")[0], 401)

    def test_team_data_needs_a_key_and_the_pc_key_works(self):
        self.assertEqual(self.get("/api/team")[0], 401)
        status, body = self.get("/api/team", "pc-window-key-abcdefghijkl")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["rooms"][0]["worker"], "Nova")
        self.assertFalse(self.access.check("pc-window-key-abcdefghijkX"))


if __name__ == "__main__":
    unittest.main()


class Hq3dTests(unittest.TestCase):
    """1.33: HQ in real 3D (WebGL), three.js bundled locally (the page's CSP allows only Doxa's own scripts)."""

    def test_the_3d_world_is_bundled_and_wired_with_a_fallback(self):
        from pathlib import Path
        web = Path(__file__).resolve().parents[1] / "forgemind" / "phone_web"
        html = (web / "hq.html").read_text("utf-8")
        self.assertIn('<script type="module" src="hq3d-boot.js"></script>', html)
        boot = (web / "hq3d-boot.js").read_text("utf-8")
        self.assertIn('import("./hq3d.js")', boot)            # loaded on demand…
        self.assertIn("pointer: coarse", boot)                  # …and not on phones (the owner: keep the phone simple)
        self.assertNotIn("http", "".join(l for l in html.splitlines() if "<script" in l))  # nothing from the internet
        world = (web / "hq3d.js").read_text("utf-8")
        self.assertIn('from "./vendor/three.module.min.js"', world)
        self.assertNotIn("cdn", world.lower())
        for name in ("three.module.min.js", "three-LICENSE.txt", "jsm/postprocessing/EffectComposer.js",
                     "jsm/postprocessing/UnrealBloomPass.js", "jsm/shaders/CopyShader.js"):
            self.assertTrue((web / "vendor" / name).is_file(), name)
        for vendored in (web / "vendor" / "jsm").rglob("*.js"):
            self.assertNotIn("from 'three'", vendored.read_text("utf-8"), vendored.name)  # bare imports would fail
        js = (web / "hq.js").read_text("utf-8")
        self.assertIn("window.HQ3D", js)          # uses the 3D world when it loaded…
        self.assertIn("if (threeOn) return;", js)  # …and keeps the CSS floor as the fallback
        self.assertIn("hq3d-ready", js)
        self.assertIn("2d", world)                 # ?2d forces the old view
        self.assertNotIn('style: `width', js)      # CSP blocks style="…" attributes (the mission bar)
