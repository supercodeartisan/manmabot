"""Seller Keygen CLI acceptance tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ENGINE = _ROOT / "Engine"
for p in (_ROOT, _ENGINE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from crypto.seller_cli import artifact as artifact_ops
from crypto.seller_cli import cek_ops
from crypto.seller_cli import license_ops
from crypto.seller_cli import signing
from crypto.seller_cli.store import SellerStore
from crypto.ticket import sign_ticket, verify_ticket
from crypto.license_server.vault import VaultError


class TestSellerCli(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.store = SellerStore(Path(self._td.name))

    def tearDown(self) -> None:
        self.store.close()
        self._td.cleanup()

    def test_signing_keypair_and_verify(self) -> None:
        info = signing.create_signing_key(self.store)
        kid = info["kid"]
        self.assertTrue(kid.startswith("e1-"))
        kid2, sk = signing.load_private(self.store)
        self.assertEqual(kid, kid2)
        pk = signing.load_public(self.store, kid)
        msg = b"hello-jcs"
        sig = sk.sign(msg)
        pk.verify(sig, msg)  # raises if mismatch

    def test_unknown_kid_rejected(self) -> None:
        signing.create_signing_key(self.store)
        trusted = signing.trusted_public_map(self.store)
        other = Ed25519PrivateKey.generate()
        core = {
            "format_version": 1,
            "kid": "unknown-kid",
            "license_id": "x",
            "product_id": "00000000-0000-4000-8000-000000000001",
            "cek_id": "00000000-0000-4000-8000-0000000000ce",
            "device_id": "ab" * 32,
            "binding_generation": 1,
            "envelope_hash": "cd" * 32,
        }
        # Sign with other key but claim unknown kid — verify uses trusted map
        ticket = dict(core)
        from crypto.jcs import dumps as jcs_dumps

        ticket["signature"] = other.sign(jcs_dumps(core)).hex()
        with self.assertRaises(Exception):
            verify_ticket(ticket, trusted_keys=trusted)

    def test_previous_kid_accepted(self) -> None:
        first = signing.create_signing_key(self.store)
        second = signing.create_signing_key(self.store)
        self.assertNotEqual(first["kid"], second["kid"])
        insp = signing.inspect_signing(self.store)
        self.assertEqual(insp["current_kid"], second["kid"])
        self.assertEqual(insp["previous_kid"], first["kid"])
        trusted = signing.trusted_public_map(self.store)
        self.assertIn(first["kid"], trusted)
        self.assertIn(second["kid"], trusted)
        # Ticket signed with previous kid still verifies
        kid, sk = signing.load_private(self.store, first["kid"])
        env = {"format_version": 1, "cek_id": "c", "wrap_alg": "RSA-OAEP-SHA256", "wrapped_cek": "aa"}
        from crypto.ticket import envelope_hash_hex

        core = {
            "format_version": 1,
            "kid": kid,
            "license_id": "lic",
            "product_id": "00000000-0000-4000-8000-000000000001",
            "cek_id": "00000000-0000-4000-8000-0000000000ce",
            "device_id": "ab" * 32,
            "binding_generation": 1,
            "envelope_hash": envelope_hash_hex(env),
        }
        ticket = sign_ticket(core, sk)
        verify_ticket(ticket, trusted_keys=trusted, envelope=env)

    def test_cek_32_and_duplicate_rejected(self) -> None:
        a = cek_ops.create_cek(self.store)
        self.assertEqual(a["cek_len"], 32)
        cek = self.store.vault().load(a["cek_id"])
        # Same bytes idempotent
        self.store.vault().store(
            cek_id=a["cek_id"], product_id=a["product_id"], cek=cek
        )
        # Different bytes under same id → error
        with self.assertRaises(VaultError):
            self.store.vault().store(
                cek_id=a["cek_id"],
                product_id=a["product_id"],
                cek=bytes([1] * 32),
            )

    def test_rotate_new_cek_id(self) -> None:
        a = cek_ops.create_cek(self.store)
        b = cek_ops.rotate_cek(self.store)
        self.assertNotEqual(a["cek_id"], b["cek_id"])

    def test_pack_id_reservation_unique(self) -> None:
        a = cek_ops.create_cek(self.store)
        p1 = cek_ops.reserve_pack_id(self.store, cek_id=a["cek_id"])
        p2 = cek_ops.reserve_pack_id(self.store, cek_id=a["cek_id"])
        self.assertNotEqual(p1["pack_id_hex"], p2["pack_id_hex"])

    def test_license_and_artifact(self) -> None:
        signing.create_signing_key(self.store)
        cek = cek_ops.create_cek(self.store)
        lic = license_ops.create_license(self.store, cek_id=cek["cek_id"])
        self.assertEqual(lic["cek_id"], cek["cek_id"])
        self.assertEqual(lic["status"], "issued")
        info = license_ops.inspect_license(self.store, lic["license_id"])
        self.assertNotIn("license_key", info)
        art = artifact_ops.generate_artifact(
            self.store,
            license_id=lic["license_id"],
            license_key=lic["license_key"],
        )
        artifact_ops.verify_artifact_file(Path(art["path"]))
        # Inject private key into copy → verify fails
        bad = dict(art["artifact"])
        bad["leak"] = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
        with self.assertRaises(RuntimeError):
            artifact_ops.verify_artifact_dict(bad)

    def test_reset_preserves_audit(self) -> None:
        signing.create_signing_key(self.store)
        cek = cek_ops.create_cek(self.store)
        lic = license_ops.create_license(self.store, cek_id=cek["cek_id"])
        # Bind manually via activation would need device — reset without binding fails
        # Create a fake binding row then reset
        self.store.db().conn.execute(
            """
            INSERT INTO bindings(
                license_id, device_id, hwid_hash, spki_der,
                activation_id, binding_generation, bound_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lic["license_id"],
                "ab" * 32,
                None,
                b"\x00" * 16,
                str(uuid.uuid4()),
                1,
                "2020-01-01T00:00:00+00:00",
            ),
        )
        out = license_ops.reset_license(
            self.store, lic["license_id"], reason="test", admin_id="admin"
        )
        self.assertEqual(out["old_generation"], 1)
        self.assertEqual(out["new_generation"], 2)
        n = self.store.db().conn.execute(
            "SELECT COUNT(*) AS c FROM binding_resets WHERE license_id = ?",
            (lic["license_id"],),
        ).fetchone()["c"]
        self.assertEqual(n, 1)

    def test_export_public_no_private(self) -> None:
        signing.create_signing_key(self.store)
        bundle = signing.export_public_trust_bundle(self.store)
        text = Path(bundle["path"]).read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE", text)
        data = json.loads(text)
        self.assertTrue(data["kids"])


if __name__ == "__main__":
    unittest.main()
