"""Mac / Linux paths: secrets in the system keychain, data folder outside AppData. Runs on any OS (fake keyring)."""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from forgemind import config, windows_credentials


class FakeKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")
        self.store = {}

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def get_password(self, service, name):
        return self.store.get((service, name))


class KeychainTests(unittest.TestCase):
    def test_round_trip_keeps_secret_out_of_the_file(self):
        fake = FakeKeyring()
        with mock.patch.dict(sys.modules, {"keyring": fake}):
            stored = windows_credentials.keychain_key(b"sk-test-123", encrypt=True)
            self.assertTrue(stored.startswith(windows_credentials.MARK))
            self.assertNotIn(b"sk-test-123", stored)
            self.assertEqual(windows_credentials.keychain_key(stored, encrypt=False), b"sk-test-123")

    def test_windows_blob_or_missing_entry_gives_a_clear_error(self):
        fake = FakeKeyring()
        with mock.patch.dict(sys.modules, {"keyring": fake}):
            with self.assertRaisesRegex(RuntimeError, "another computer"):
                windows_credentials.keychain_key(b"\x01\x00dpapi", encrypt=False)
            with self.assertRaisesRegex(RuntimeError, "no longer has"):
                windows_credentials.keychain_key(windows_credentials.MARK + b"gone", encrypt=False)


class DataFolderTests(unittest.TestCase):
    def test_mac_uses_application_support(self):
        env = {k: v for k, v in os.environ.items() if k != "LOCALAPPDATA"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(config, "os", types.SimpleNamespace(name="posix", environ=os.environ)), \
                mock.patch.object(config.sys, "platform", "darwin"), mock.patch.object(Path, "mkdir"):
            self.assertEqual(config.app_data_dir(), Path.home() / "Library/Application Support" / config.APP_NAME)


if __name__ == "__main__":
    unittest.main()
