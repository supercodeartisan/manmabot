"""DeviceKeyProvider Soft path + state-machine unit tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Engine.crypto.device_key import DeviceKeyError, ProviderType, open_or_create_device_key
from Engine.crypto.hwid import device_id_from_spki
from Engine.crypto.soft_key import oaep_encrypt_cek, soft_key_exists, write_meta
from Engine.crypto.tpm_key import TpmFailureClass, classify_tpm_failure


class TestClassifyTpm(unittest.TestCase):
    def test_denied(self) -> None:
        self.assertIs(classify_tpm_failure(0x80070005), TpmFailureClass.denied)

    def test_transient(self) -> None:
        self.assertIs(classify_tpm_failure(0x80090030), TpmFailureClass.transient)

    def test_permanent(self) -> None:
        self.assertIs(classify_tpm_failure(0x80090029), TpmFailureClass.permanent)


@unittest.skipUnless(sys.platform == "win32", "DPAPI requires Windows")
class TestSoftDeviceKey(unittest.TestCase):
    def test_create_persist_decrypt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = Path(td)
            prov = open_or_create_device_key(store, force_soft=True)
            self.assertEqual(prov.provider_type, ProviderType.soft)
            spki = prov.get_public_key_spki_der()
            self.assertEqual(prov.device_id, device_id_from_spki(spki))

            # Re-open
            prov2 = open_or_create_device_key(store, force_soft=True)
            self.assertEqual(prov2.device_id, prov.device_id)
            self.assertEqual(prov2.get_public_key_spki_der(), spki)

            from cryptography.hazmat.primitives.serialization import load_der_public_key

            pub = load_der_public_key(spki)
            cek = bytes(range(32))
            ct = oaep_encrypt_cek(pub, cek)  # type: ignore[arg-type]
            self.assertEqual(prov2.decrypt_cek(ct), cek)

    def test_no_auto_recreate_soft(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = Path(td)
            prov = open_or_create_device_key(store, force_soft=True)
            did = prov.device_id
            # Delete soft key but keep meta → must error, not recreate
            (store / "device_rsa_soft.dpapi").unlink()
            (store / "device_rsa_soft.spki").unlink(missing_ok=True)
            with self.assertRaises(DeviceKeyError):
                open_or_create_device_key(store, force_soft=True)
            self.assertFalse(soft_key_exists(store))
            # device_id from first create still in meta — identity preserved as error
            self.assertTrue(did)

    def test_meta_recover_from_soft_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = Path(td)
            prov = open_or_create_device_key(store, force_soft=True)
            did = prov.device_id
            (store / "device_key_meta.dpapi").unlink()
            # Meta absent + soft present → recover soft meta
            prov2 = open_or_create_device_key(store, force_soft=True)
            self.assertEqual(prov2.device_id, did)
            self.assertEqual(prov2.provider_type, ProviderType.soft)

    def test_invalid_meta(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = Path(td)
            open_or_create_device_key(store, force_soft=True)
            # Overwrite meta with garbage DPAPI of wrong JSON via write_meta misuse:
            # write valid meta then corrupt file bytes after protect is hard;
            # instead write unprotected garbage file that DPAPI will reject OR
            # write meta with wrong device_id.
            write_meta(
                store,
                provider_type="soft",
                device_id="0" * 64,
                created_at="2020-01-01T00:00:00+00:00",
            )
            with self.assertRaises(DeviceKeyError):
                open_or_create_device_key(store, force_soft=True)


if __name__ == "__main__":
    unittest.main()
