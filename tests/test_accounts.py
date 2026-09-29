from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from manmabot_v1.accounts import Account, AccountStore, AccountStoreError
from manmabot_v1.paths import USERDATA
from manmabot_v1.profile import Profile, save_profile


@unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is required")
class AccountStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = USERDATA / f".account-test-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.path = self.root / "accounts.json"
        self.store = AccountStore(self.path)
        self.purple_path = self.root / "Purple.exe"
        self.game_path = self.root / "LC.exe"
        self.purple_path.write_bytes(b"test")
        self.game_path.write_bytes(b"test")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def account(self, *, username: str = "operator@example.com") -> Account:
        return Account.create(
            username,
            "plain-secret",
            "Korea",
            "Test Server",
            character_number=2,
            click_mode="hybrid",
            display_name="Primary",
            locale="ko",
            purple_launcher_path=str(self.purple_path),
            game_path=str(self.game_path),
            character_type="knight",
        )

    def test_round_trip_uses_dpapi_ciphertext_only(self) -> None:
        account = self.account()
        self.store.save([account])

        raw = self.path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertNotIn("plain-secret", raw)
        self.assertNotIn("password", payload["accounts"][0])
        self.assertNotIn("pw", payload["accounts"][0])
        self.assertIn("password_dpapi", payload["accounts"][0])

        loaded = self.store.load()[0]
        self.assertEqual(loaded.account_id, account.account_id)
        self.assertEqual(loaded.password, "plain-secret")
        launcher = loaded.to_launcher_account()
        self.assertEqual(launcher["character_number"], 2)
        self.assertEqual(launcher["display_name"], "Primary")
        self.assertEqual(launcher["locale"], "ko")
        self.assertEqual(launcher["purple_path"], str(self.purple_path))
        self.assertEqual(launcher["game_path"], str(self.game_path))
        self.assertEqual(loaded.character_type, "knight")
        self.assertEqual(launcher["character_type"], "knight")

    def test_required_launcher_metadata_is_persisted(self) -> None:
        self.store.save([self.account()])
        record = json.loads(self.path.read_text(encoding="utf-8"))["accounts"][0]
        self.assertEqual(record["display_name"], "Primary")
        self.assertEqual(record["locale"], "ko")
        self.assertEqual(record["purple_launcher_path"], str(self.purple_path))
        self.assertEqual(record["game_path"], str(self.game_path))
        self.assertEqual(record["character_type"], "knight")

    def test_repr_redacts_password(self) -> None:
        shown = repr(self.account())
        self.assertNotIn("plain-secret", shown)
        self.assertIn("<redacted>", shown)

    def test_duplicate_username_is_rejected_case_insensitively(self) -> None:
        first = self.account()
        second = self.account(username="OPERATOR@example.com")
        with self.assertRaisesRegex(ValueError, "duplicate_account"):
            self.store.save([first, second])

    def test_failed_replace_preserves_previous_store(self) -> None:
        self.store.save([self.account()])
        previous = self.path.read_bytes()
        with mock.patch("manmabot_v1.accounts.os.replace", side_effect=OSError):
            with self.assertRaises(AccountStoreError):
                self.store.save([self.account(username="second@example.com")])
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_malformed_store_is_rejected_without_defaults(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(AccountStoreError):
            self.store.load()

    def test_plaintext_password_record_is_rejected(self) -> None:
        self.path.write_text(
            json.dumps({
                "version": 1,
                "accounts": [{
                    "account_id": str(uuid.uuid4()),
                    "username": "unsafe@example.com",
                    "password": "unsafe",
                }],
            }),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AccountStoreError, "unsafe"):
            self.store.load()

    def test_inaccessible_store_is_backed_up_before_reset(self) -> None:
        original = b'{"version": 1, "accounts": [{"broken": true}]}'
        self.path.write_bytes(original)

        backup = self.store.backup_and_reset_inaccessible()

        self.assertIsNotNone(backup)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(self.store.load(), [])

    def test_profile_persists_only_selected_account_id(self) -> None:
        account = self.account()
        profile_path = self.root / "profile.json"
        save_profile(Profile(selected_account_id=account.account_id), profile_path)
        raw = profile_path.read_text(encoding="utf-8")
        self.assertIn(account.account_id, raw)
        self.assertNotIn(account.username, raw)
        self.assertNotIn(account.password, raw)


if __name__ == "__main__":
    unittest.main()
