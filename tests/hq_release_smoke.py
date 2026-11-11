"""Isolated local render and real Edge/Tk lifecycle check; no owner data or cloud calls."""
import json
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgemind.team import ROOMS
from forgemind.embed_web import EmbeddedPage, profile_dir
from forgemind.hq_window import open_hq_window
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'release-checks'
OUT.mkdir(exist_ok=True)
state = {'campaign': {'id': 'demo', 'name': 'Design preview', 'goal': 'Fixture data — no campaign running'},
         'rooms': [dict(key=k, room=r, worker=w, about=a) for k, r, w, a in ROOMS],
         'counts': {}, 'workers': {}, 'busy': [], 'waiting': [], 'models': {}, 'prime': {'on': False}}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / 'forgemind' / 'phone_web'), **kw)
    def log_message(self, *_):
        pass
    def do_GET(self):
        if self.path == '/api/team':
            payload = json.dumps(state).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            super().do_GET()

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}/hq.html'
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1600, 'height': 1000}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_selector('.hq-island')
        page.wait_for_timeout(1300)
        page.screenshot(path=str(OUT / 'hq-overview.png'))
        page.get_by_role('button', name='+ New campaign', exact=True).first.click()
        page.screenshot(path=str(OUT / 'hq-campaign.png'))
        assert not errors, errors
        browser.close()
    with tempfile.TemporaryDirectory() as tmp:
        app = tk.Tk()
        app.title('Doxa release check')
        app.geometry('600x400')
        results = []
        app._set_status = results.append
        def embed(host, callback):
            app.page = EmbeddedPage(host, url, profile_dir(tmp), on_state=callback)
            app.page.start()
        app.embed_hq = embed
        window = open_hq_window(app)
        deadline = time.monotonic() + 30
        def check():
            if getattr(app, 'page', None) and app.page.embedded or time.monotonic() > deadline:
                app.quit()
            else:
                app.after(100, check)
        app.after(100, check)
        try:
            app.mainloop()
            assert app.page.embedded, results
            window.withdraw(); app.update()
            assert open_hq_window(app) is window
            handle = app.page.hwnd
        finally:
            if getattr(app, 'page', None):
                app.page.close()
            app.destroy()
        from forgemind.embed_web import _user32
        assert not _user32().IsWindow(handle), 'HQ browser survived close'
        time.sleep(1)
    print('PASS: desktop render, campaign dialog, embed, hide/reopen, exact-profile cleanup')
finally:
    server.shutdown()
    server.server_close()
