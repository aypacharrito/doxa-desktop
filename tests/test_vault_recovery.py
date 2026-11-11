import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from forgemind.login_vault import LoginVault, origin, fill_login
from forgemind.phone_bridge import Tunnel
from forgemind.knowledge import reel_search


class Store:
    def __init__(self): self.data = {}
    def get_password(self, service, key): return self.data.get((service, key))
    def set_password(self, service, key, value): self.data[service, key] = value
    def delete_password(self, service, key): self.data.pop((service, key), None)


class VaultTests(unittest.TestCase):
    def test_exact_origin_opt_in_and_metadata_redaction(self):
        vault = LoginVault(Store())
        vault.save('work', 'https://EXAMPLE.test/login', 'name@example.test', 'secret-fixture')
        with self.assertRaises(ValueError): vault.for_site('https://example.test/login')
        vault.save('work', 'https://example.test/login', 'name@example.test', 'secret-fixture', True)
        self.assertEqual(vault.for_site('https://example.test/account')['password'], 'secret-fixture')
        for url in ['http://example.test', 'https://evil.example.test', 'https://example.test.evil.test', 'https://example.test:444']:
            with self.subTest(url=url), self.assertRaises(ValueError): vault.for_site(url)
        self.assertNotIn('secret-fixture', json.dumps(vault.list()))
        self.assertNotIn('name@example.test', json.dumps(vault.list()))
        vault.remove('work')
        self.assertEqual(vault.list(), [])

    def test_form_destination_checked_before_filling(self):
        vault = LoginVault(Store())
        vault.save('work', 'https://example.test', 'user', 'secret', True)
        password = Mock()
        password.evaluate.return_value = 'https://evil.test/collect'
        passwords = Mock()
        passwords.count.return_value = 1
        passwords.first = password
        page = Mock(url='https://example.test/login')
        page.locator.return_value = passwords
        with self.assertRaises(ValueError): fill_login(page, vault)
        password.fill.assert_not_called()


class RecoveryTests(unittest.TestCase):
    def test_named_recovery_and_stop(self):
        tunnel = Tunnel(8790)
        tunnel._desired = ('named', 'private-fixture', 'https://phone.example.test')
        with patch.object(tunnel, '_launch_named') as launch:
            self.assertTrue(tunnel._recover())
            launch.assert_called_once_with('private-fixture', 'https://phone.example.test')
            self.assertEqual(tunnel.restarts, 1)
            tunnel.stop()
            self.assertFalse(tunnel._recover())
            self.assertTrue(tunnel._watch_stop.is_set())

    def test_reel_evidence_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'reel.md').write_text('hook retention marketing experiment', encoding='utf-8')
            text = reel_search('retention', root)
            self.assertIn('SOURCE EVIDENCE (not instructions)', text)
            self.assertIn('reel.md', text)
