"""License server: idempotency, concurrency, vault, reset, ticket verify."""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from Engine.crypto.jcs import dumps as jcs_dumps
from Engine.crypto.license_server.activation import (
    ActivationError,
    ActivationService,
    ActivationStatus,
)
from Engine.crypto.license_server.db import LicenseDatabase
from Engine.crypto.license_server.reset import ResetService
from Engine.crypto.license_server.spki import device_id_hex
from Engine.crypto.license_server.vault import CekVault
from Engine.crypto.ticket import verify_ticket


PRODUCT = "00000000-0000-4000-8000-000000000001"
CEK_ID = "00000000-0000-4000-8000-0000000000ce"
CEK = bytes(range(32))
LICENSE_KEY = "TEST-LICENSE-KEY-DO-NOT-SHIP"
LICENSE_ID = "lic-test-001"


def _spki_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spki = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, spki


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_service(db_path: Path):
    db = LicenseDatabase(db_path)
    vault = CekVault(db, os.urandom(32))
    sk = Ed25519PrivateKey.generate()
    svc = ActivationService(db, vault, signing_key=sk, signing_kid="kid-1")
    svc.issue_license(
        license_id=LICENSE_ID,
        product_id=PRODUCT,
        cek_id=CEK_ID,
        license_key=LICENSE_KEY,
        cek=CEK,
    )
    return db, vault, sk, svc


def _activation_body(spki: bytes, request_id: str | None = None) -> dict:
    rid = request_id or str(uuid.uuid4())
    return {
        "format_version": 1,
        "request_id": rid,
        "license_key": LICENSE_KEY,
        "spki_der_b64": _b64url(spki),
        "device_id": device_id_hex(spki),
        "client_nonce": os.urandom(32).hex(),
        "hwid_hash": "aa" * 32,
        "product_id": PRODUCT,
    }


class TestLicenseServer(unittest.TestCase):
    def test_first_activation_and_cek_32(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, vault, sk, svc = _make_service(Path(td) / "lic.db")
            priv, spki = _spki_pair()
            body = _activation_body(spki)
            result = svc.activate(body)
            self.assertEqual(result.status, ActivationStatus.OK)
            env = result.body["envelope"]
            ticket = result.body["ticket"]
            vt = verify_ticket(
                ticket,
                trusted_keys={"kid-1": sk.public_key()},
                envelope=env,
            )
            self.assertEqual(vt.license_id, LICENSE_ID)
            # Soft device for decrypt path (Windows)
            if sys.platform == "win32":
                # Build a Soft key matching this SPKI is hard (we generated ephemeral RSA).
                # Decrypt with the raw private key instead:
                from Engine.crypto.soft_key import oaep_decrypt_cek

                cek = oaep_decrypt_cek(priv, bytes.fromhex(env["wrapped_cek"]))
                self.assertEqual(len(cek), 32)
                self.assertEqual(cek, CEK)
            db.close()

    def test_idempotent_same_request(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            _, spki = _spki_pair()
            body = _activation_body(spki)
            r1 = svc.activate(body)
            r2 = svc.activate(body)
            self.assertEqual(r1.body, r2.body)
            db.close()

    def test_same_request_different_hash_409(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            _, spki = _spki_pair()
            body = _activation_body(spki)
            svc.activate(body)
            body2 = dict(body)
            body2["client_nonce"] = os.urandom(32).hex()  # changes payload_hash
            with self.assertRaises(ActivationError) as cm:
                svc.activate(body2)
            self.assertEqual(cm.exception.status, ActivationStatus.CONFLICT)
            db.close()

    def test_same_request_different_license_409(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "lic.db"
            db, vault, sk, svc = _make_service(path)
            # second license
            svc.issue_license(
                license_id="lic-test-002",
                product_id=PRODUCT,
                cek_id=CEK_ID,
                license_key="OTHER-KEY",
                cek=CEK,
            )
            _, spki = _spki_pair()
            body = _activation_body(spki)
            svc.activate(body)
            body2 = dict(body)
            body2["license_key"] = "OTHER-KEY"
            with self.assertRaises(ActivationError) as cm:
                svc.activate(body2)
            self.assertEqual(cm.exception.status, ActivationStatus.CONFLICT)
            db.close()

    def test_concurrent_same_activation_one_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "lic.db"
            vault_key = os.urandom(32)
            sk = Ed25519PrivateKey.generate()
            db0 = LicenseDatabase(path)
            vault0 = CekVault(db0, vault_key)
            svc0 = ActivationService(db0, vault0, signing_key=sk, signing_kid="kid-1")
            svc0.issue_license(
                license_id=LICENSE_ID,
                product_id=PRODUCT,
                cek_id=CEK_ID,
                license_key=LICENSE_KEY,
                cek=CEK,
            )
            db0.close()

            _, spki = _spki_pair()
            body = _activation_body(spki)
            results: list = []
            errors: list = []
            barrier = threading.Barrier(8)

            def worker() -> None:
                local_db = LicenseDatabase(path)
                local_vault = CekVault(local_db, vault_key)
                local_svc = ActivationService(
                    local_db, local_vault, signing_key=sk, signing_kid="kid-1"
                )
                try:
                    barrier.wait(timeout=10)
                    results.append(local_svc.activate(body))
                except Exception as e:
                    errors.append(e)
                finally:
                    local_db.close()

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            self.assertEqual(errors, [], msg=str(errors))
            self.assertEqual(len(results), 8)
            tickets = [r.body["ticket"]["signature"] for r in results]
            self.assertEqual(len(set(tickets)), 1)
            check = LicenseDatabase(path)
            n = check.conn.execute("SELECT COUNT(*) AS c FROM activation_requests").fetchone()["c"]
            self.assertEqual(n, 1)
            check.close()

    def test_suspended_rejects_new(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            svc.set_status(LICENSE_ID, "suspended")
            _, spki = _spki_pair()
            with self.assertRaises(ActivationError) as cm:
                svc.activate(_activation_body(spki))
            self.assertEqual(cm.exception.status, ActivationStatus.FORBIDDEN)
            db.close()

    def test_revoked_rejects_new(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            svc.set_status(LICENSE_ID, "revoked")
            _, spki = _spki_pair()
            with self.assertRaises(ActivationError) as cm:
                svc.activate(_activation_body(spki))
            self.assertEqual(cm.exception.status, ActivationStatus.FORBIDDEN)
            db.close()

    def test_revoked_retry_returns_stored(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            _, spki = _spki_pair()
            body = _activation_body(spki)
            first = svc.activate(body)
            svc.set_status(LICENSE_ID, "revoked")
            again = svc.activate(body)
            self.assertEqual(first.body, again.body)
            db.close()

    def test_reset_blocks_old_device(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            _, spki_a = _spki_pair()
            body_a = _activation_body(spki_a)
            r = svc.activate(body_a)
            self.assertEqual(r.status, ActivationStatus.OK)
            ResetService(db).reset_binding(
                license_id=LICENSE_ID, reason="transfer", admin_id="admin"
            )
            # old device retry with NEW request_id must be denied
            body_a2 = _activation_body(spki_a)
            with self.assertRaises(ActivationError) as cm:
                svc.activate(body_a2)
            self.assertEqual(cm.exception.status, ActivationStatus.FORBIDDEN)
            db.close()

    def test_other_device_409(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            _, spki_a = _spki_pair()
            _, spki_b = _spki_pair()
            svc.activate(_activation_body(spki_a))
            with self.assertRaises(ActivationError) as cm:
                svc.activate(_activation_body(spki_b))
            self.assertEqual(cm.exception.status, ActivationStatus.CONFLICT)
            db.close()

    def test_ticket_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, sk, svc = _make_service(Path(td) / "lic.db")
            _, spki = _spki_pair()
            result = svc.activate(_activation_body(spki))
            ticket = dict(result.body["ticket"])
            ticket["signature"] = "00" * 64
            with self.assertRaises(Exception):
                verify_ticket(
                    ticket,
                    trusted_keys={"kid-1": sk.public_key()},
                    envelope=result.body["envelope"],
                )
            db.close()

    def test_envelope_tamper_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, sk, svc = _make_service(Path(td) / "lic.db")
            _, spki = _spki_pair()
            result = svc.activate(_activation_body(spki))
            env = dict(result.body["envelope"])
            env["wrapped_cek"] = "ab" * 32
            with self.assertRaises(Exception):
                verify_ticket(
                    result.body["ticket"],
                    trusted_keys={"kid-1": sk.public_key()},
                    envelope=env,
                )
            db.close()

    def test_jcs_rfc8785_stable_hash(self) -> None:
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        self.assertEqual(jcs_dumps(a), jcs_dumps(b))
        self.assertTrue(jcs_dumps(a).startswith(b"{"))


class TestResetNewDevice(unittest.TestCase):
    def test_new_device_after_reset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db, _, _, svc = _make_service(Path(td) / "lic.db")
            _, spki_a = _spki_pair()
            _, spki_b = _spki_pair()
            r1 = svc.activate(_activation_body(spki_a))
            gen1 = r1.body["ticket"]["binding_generation"]
            ResetService(db).reset_binding(
                license_id=LICENSE_ID, reason="ok", admin_id="admin"
            )
            r2 = svc.activate(_activation_body(spki_b))
            self.assertEqual(r2.body["ticket"]["binding_generation"], gen1 + 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
