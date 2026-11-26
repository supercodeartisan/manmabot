"""E2E customer activation: Seller → Stage5 packs → Activation → Runtime.

Does not start the game bot. Login/move/combat/HP/party decision logic untouched.
Permanent offline: after first activation, ticket+envelope on disk suffice.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ENGINE = _ROOT / "Engine"
_PACKAGING = _ROOT / "packaging"
for p in (_ROOT, _ENGINE, _PACKAGING):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from crypto.authorized_session import open_authorized_session
from crypto.device_key import open_or_create_device_key
from crypto.license_server.activation import ActivationService, ActivationStatus
from crypto.pack_format import PackFormatError
from crypto.seller_cli import cek_ops, license_ops, signing
from crypto.seller_cli.store import SellerStore
from mmb2_stage5 import build_mmb2_blob, publish_verified_pack_pair
from session.analysis_temp import cleanup_analysis_temp, create_analysis_temp, materialize_files
from session.analysis_overlay import analysis_registry_file, set_analysis_overlay
from session.asset_store import is_mounted, mount_bytes
from session.build_manifest import BuildManifestError, verify_engine_build_manifest
from session.licensed_runtime import (
    clear_trusted_keys,
    load_pack_files,
    load_trusted_kids_file,
)

PRODUCT = "00000000-0000-4000-8000-000000000001"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _device_spki():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spki = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, spki


@unittest.skipUnless(sys.platform == "win32", "Soft device key uses DPAPI")
class TestE2ECustomerActivation(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.seller = SellerStore(self.root / "SellerData")
        signing.create_signing_key(self.seller)
        self.trust = signing.export_public_trust_bundle(self.seller)
        self.cek = cek_ops.create_cek(self.seller, product_id=PRODUCT)
        self.lic = license_ops.create_license(self.seller, cek_id=self.cek["cek_id"])

        # Fake customer Engine tree
        self.engine = self.root / "Customer" / "Engine"
        self.engine.mkdir(parents=True)
        self.data_src = self.root / "src_data"
        self.an_src = self.root / "src_analysis"
        (self.data_src / "maps").mkdir(parents=True)
        (self.data_src / "maps" / "a.png").write_bytes(b"png-bytes")
        (self.data_src / "catalog").mkdir()
        (self.data_src / "catalog" / "mobs.json").write_text("[]", encoding="utf-8")
        (self.an_src / "registry").mkdir(parents=True)
        (self.an_src / "registry" / "offsets.json").write_text(
            '{"PlayerBase": 1}\n', encoding="utf-8"
        )

        clear_trusted_keys()
        cleanup_analysis_temp()
        set_analysis_overlay(None)

    def tearDown(self) -> None:
        cleanup_analysis_temp()
        set_analysis_overlay(None)
        clear_trusted_keys()
        self.seller.close()
        self._td.cleanup()

    def _build_customer_packs(self) -> dict:
        data_blob, data_meta = build_mmb2_blob(
            {
                "maps/a.png": b"png-bytes",
                "catalog/mobs.json": b"[]",
            },
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
            note="e2e-data",
        )
        an_blob, an_meta = build_mmb2_blob(
            {"registry/offsets.json": b'{"PlayerBase": 1}\n'},
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
            note="e2e-analysis",
        )
        self.assertNotEqual(data_meta["pack_id_hex"], an_meta["pack_id_hex"])
        return publish_verified_pack_pair(
            engine_dir=self.engine,
            data_blob=data_blob,
            data_meta=data_meta,
            analysis_blob=an_blob,
            analysis_meta=an_meta,
            seller_root=self.seller.root,
        )

    def _activate_customer(self, *, userdata: Path, force_soft: bool = True):
        priv, spki = _device_spki()
        # Soft device key in customer userdata — but activation uses SPKI from request;
        # for unwrap we need DeviceKey matching that SPKI. Soft keygen creates its own.
        # So for E2E unwrap we use the RSA private from _device_spki via a custom path:
        # write ticket/envelope after server activation with this SPKI, then decrypt
        # with SoftKey oaep using `priv` OR install Soft key that matches.
        # Simplest: activate with SPKI, decrypt CEK with `priv`, use SimplePackSession
        # for pack load; separately test open_authorized_session with Soft device by
        # using Soft device SPKI for activation.
        device_dir = userdata / "license" / "device_key"
        device_dir.mkdir(parents=True, exist_ok=True)
        # Use Soft DeviceKey for full path
        os.environ["MANMABOT_FORCE_SOFT_DEVICE"] = "1"
        device = open_or_create_device_key(device_dir, force_soft=True)
        spki = device.get_public_key_spki_der()

        kid, sk = signing.load_private(self.seller)
        svc = ActivationService(
            self.seller.db(), self.seller.vault(), signing_key=sk, signing_kid=kid
        )
        body = {
            "format_version": 1,
            "request_id": str(uuid.uuid4()),
            "license_key": self.lic["license_key"],
            "spki_der_b64": _b64url(spki),
            "device_id": device.device_id,
            "client_nonce": os.urandom(32).hex(),
            "product_id": PRODUCT,
        }
        result = svc.activate(body)
        self.assertEqual(result.status, ActivationStatus.OK)
        ticket = result.body["ticket"]
        envelope = result.body["envelope"]

        # Persist as customer would
        lic_dir = userdata / "license"
        lic_dir.mkdir(parents=True, exist_ok=True)
        (lic_dir / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
        (lic_dir / "envelope.json").write_text(json.dumps(envelope), encoding="utf-8")

        trusted = signing.trusted_public_map(self.seller)
        session = open_authorized_session(
            ticket=ticket,
            envelope=envelope,
            device=device,
            trusted_keys=trusted,
            expected_product_id=PRODUCT,
        )
        self.assertEqual(len(session.decrypted_cek_32), 32)
        return session, ticket, envelope, device, trusted

    def test_full_chain_and_offline_restart(self) -> None:
        published = self._build_customer_packs()
        load_trusted_kids_file(Path(self.trust["path"]))
        manifest = verify_engine_build_manifest(self.engine)
        self.assertEqual(manifest["build_id"], published["build_id"])
        self.assertEqual(
            manifest["packs"]["data.pack"]["pack_id_hex"],
            published["packs"]["data.pack"]["pack_id_hex"],
        )
        self.assertNotEqual(
            published["packs"]["data.pack"]["pack_id_hex"],
            published["packs"]["analysis_text.pack"]["pack_id_hex"],
        )

        userdata = self.root / "Customer" / "UserData"
        session, ticket, envelope, device, trusted = self._activate_customer(
            userdata=userdata
        )

        # Load both packs via session
        data_files = load_pack_files(self.engine / "data.pack", session=session)
        an_files = load_pack_files(self.engine / "analysis_text.pack", session=session)
        self.assertEqual(data_files["maps/a.png"], b"png-bytes")
        mount_bytes(self.engine / "data", data_files)
        self.assertTrue(is_mounted())

        # TEMP materialize analysis
        root = create_analysis_temp()
        materialize_files(root, an_files)
        offsets = analysis_registry_file("registry", "offsets.json")
        self.assertTrue(offsets.is_file())
        self.assertTrue(str(offsets).startswith(str(root)))

        # Offline restart: no server — reload ticket from disk + same Soft key
        session2 = open_authorized_session(
            ticket=json.loads((userdata / "license" / "ticket.json").read_text()),
            envelope=json.loads((userdata / "license" / "envelope.json").read_text()),
            device=device,
            trusted_keys=trusted,
            expected_product_id=PRODUCT,
        )
        self.assertEqual(session2.decrypted_cek_32, session.decrypted_cek_32)

    def test_unknown_kid_rejected(self) -> None:
        _, ticket, envelope, device, _ = self._activate_customer(
            userdata=self.root / "ud1"
        )
        with self.assertRaises(Exception):
            open_authorized_session(
                ticket=ticket,
                envelope=envelope,
                device=device,
                trusted_keys={},  # unknown / empty
                expected_product_id=PRODUCT,
            )

    def test_modified_ticket_rejected(self) -> None:
        _, ticket, envelope, device, trusted = self._activate_customer(
            userdata=self.root / "ud2"
        )
        bad = dict(ticket)
        bad["signature"] = "00" * 64
        with self.assertRaises(Exception):
            open_authorized_session(
                ticket=bad,
                envelope=envelope,
                device=device,
                trusted_keys=trusted,
                expected_product_id=PRODUCT,
            )

    def test_modified_envelope_rejected(self) -> None:
        _, ticket, envelope, device, trusted = self._activate_customer(
            userdata=self.root / "ud3"
        )
        bad = dict(envelope)
        bad["wrapped_cek"] = "ab" * 32
        with self.assertRaises(Exception):
            open_authorized_session(
                ticket=ticket,
                envelope=bad,
                device=device,
                trusted_keys=trusted,
                expected_product_id=PRODUCT,
            )

    def test_wrong_device_rejected(self) -> None:
        _, ticket, envelope, _, trusted = self._activate_customer(
            userdata=self.root / "ud4"
        )
        other_dir = self.root / "ud4b" / "license" / "device_key"
        other_dir.mkdir(parents=True)
        other = open_or_create_device_key(other_dir, force_soft=True)
        with self.assertRaises(Exception):
            open_authorized_session(
                ticket=ticket,
                envelope=envelope,
                device=other,
                trusted_keys=trusted,
                expected_product_id=PRODUCT,
            )

    def test_modified_pack_rejected(self) -> None:
        self._build_customer_packs()
        session, *_ = self._activate_customer(userdata=self.root / "ud5")
        blob = bytearray((self.engine / "data.pack").read_bytes())
        blob[-3] ^= 0x11
        tampered = self.root / "tampered.pack"
        tampered.write_bytes(bytes(blob))
        with self.assertRaises(PackFormatError):
            load_pack_files(tampered, session=session)

    def test_mixed_build_artifacts_rejected(self) -> None:
        published = self._build_customer_packs()
        load_trusted_kids_file(Path(self.trust["path"]))
        # Corrupt BUILD.json sha for data.pack (also breaks signature)
        build_path = self.engine / "BUILD.json"
        obj = json.loads(build_path.read_text(encoding="utf-8"))
        obj["packs"]["data.pack"]["sha256"] = "0" * 64
        build_path.write_text(json.dumps(obj), encoding="utf-8")
        with self.assertRaises(BuildManifestError):
            verify_engine_build_manifest(self.engine)
        _ = published

    def test_build_signature_tamper_rejected(self) -> None:
        self._build_customer_packs()
        load_trusted_kids_file(Path(self.trust["path"]))
        build_path = self.engine / "BUILD.json"
        obj = json.loads(build_path.read_text(encoding="utf-8"))
        obj["signature"] = "00" * 64
        build_path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        with self.assertRaises(BuildManifestError):
            verify_engine_build_manifest(self.engine)

    def test_full_chain_loads_trusted_kids_for_build(self) -> None:
        # Ensure BUILD verify uses the same pinned kids as tickets
        published = self._build_customer_packs()
        clear_trusted_keys()
        n = load_trusted_kids_file(Path(self.trust["path"]))
        self.assertGreaterEqual(n, 1)
        m = verify_engine_build_manifest(self.engine)
        self.assertEqual(m["build_id"], published["build_id"])
        self.assertEqual(m.get("kid"), published["kid"])

    def test_trusted_kids_export_has_no_private(self) -> None:
        text = Path(self.trust["path"]).read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE", text)
        n = load_trusted_kids_file(Path(self.trust["path"]))
        self.assertGreaterEqual(n, 1)

    def test_multi_instance_temp_isolation(self) -> None:
        # Two TEMP roots in one process aren't supported (singleton); simulate
        # sequential instances: cleanup then create new → different path.
        a = create_analysis_temp()
        path_a = str(a)
        cleanup_analysis_temp()
        b = create_analysis_temp()
        self.assertNotEqual(path_a, str(b))
        cleanup_analysis_temp()


if __name__ == "__main__":
    unittest.main()
