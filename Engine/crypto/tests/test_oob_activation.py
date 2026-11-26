"""OOB activation: request ↔ fulfill ↔ apply (no HTTP server)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ENGINE = _ROOT / "Engine"
for p in (_ROOT, _ENGINE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from crypto.oob_activation import (
    OobActivationError,
    REQ_PREFIX,
    RSP_PREFIX,
    build_activation_request,
    decode_wire,
    encode_wire,
    validate_activation_request,
    validate_activation_response,
)
from crypto.seller_cli import cek_ops, license_ops, signing
from crypto.seller_cli import fulfill_ops
from crypto.seller_cli.store import SellerStore

PRODUCT = "00000000-0000-4000-8000-000000000001"


@unittest.skipUnless(sys.platform == "win32", "Soft device key uses DPAPI")
class TestOobActivation(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.seller = SellerStore(self.root / "SellerData")
        signing.create_signing_key(self.seller)
        signing.export_public_trust_bundle(self.seller)
        self.cek = cek_ops.create_cek(self.seller, product_id=PRODUCT)
        self.lic = license_ops.create_license(self.seller, cek_id=self.cek["cek_id"])
        os.environ["MANMABOT_FORCE_SOFT_DEVICE"] = "1"
        # Point session paths at temp userdata via env if supported; else patch.
        self.customer = self.root / "Customer"
        self.customer.mkdir()
        self.userdata = self.customer / "UserData"
        self.userdata.mkdir()

    def tearDown(self) -> None:
        self.seller.close()
        self._td.cleanup()

    def test_wire_roundtrip_and_expiry(self) -> None:
        from crypto.device_key import open_or_create_device_key

        device = open_or_create_device_key(
            self.userdata / "license" / "device_key", force_soft=True
        )
        req = build_activation_request(
            license_key=self.lic["license_key"],
            product_id=PRODUCT,
            spki_der=device.get_public_key_spki_der(),
            device_id=device.device_id,
            ttl_hours=48,
        )
        wire = encode_wire(REQ_PREFIX, req)
        self.assertTrue(wire.startswith(REQ_PREFIX))
        self.assertEqual(decode_wire(wire)["request_id"], req["request_id"])
        validate_activation_request(req)

        expired = dict(req)
        expired["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).replace(microsecond=0).isoformat()
        with self.assertRaises(OobActivationError):
            validate_activation_request(expired)

    def test_fulfill_and_customer_apply(self) -> None:
        # Patch session license paths to temp customer tree.
        import session.licensed_runtime as lr
        import session.paths as paths
        import session.oob_activation as oob

        old_ud = paths.USERDATA
        paths.USERDATA = self.userdata
        lr.LICENSE_DIR = self.userdata / "license"
        lr.TICKET_PATH = lr.LICENSE_DIR / "ticket.json"
        lr.ENVELOPE_PATH = lr.LICENSE_DIR / "envelope.json"
        lr.DEVICE_KEY_DIR = lr.LICENSE_DIR / "device_key"
        oob.LICENSE_DIR = lr.LICENSE_DIR
        oob.REQUEST_PATH = lr.LICENSE_DIR / "activation_request.json"
        oob.RESPONSE_APPLIED_PATH = lr.LICENSE_DIR / "activation_response.applied.json"
        oob.TICKET_PATH = lr.TICKET_PATH
        oob.ENVELOPE_PATH = lr.ENVELOPE_PATH
        oob.DEVICE_KEY_DIR = lr.DEVICE_KEY_DIR
        oob.USERDATA = self.userdata
        lr.clear_trusted_keys()
        lr._SESSION = None

        try:
            # Pin trusted kids from seller export
            trust = self.root / "SellerData" / "signing" / "trusted_kids.json"
            self.assertTrue(trust.is_file())
            # Copy pin next to a fake session module path — load_trusted_kids_file(path=)
            n = lr.load_trusted_kids_file(trust)
            self.assertGreaterEqual(n, 1)

            info = oob.create_activation_request(
                license_key=self.lic["license_key"],
                product_id=PRODUCT,
                force_soft_device=True,
            )
            self.assertTrue(Path(info["path"]).is_file())

            fulfilled = fulfill_ops.fulfill(self.seller, info["path"])
            self.assertEqual(fulfilled["status"], "ok")
            self.assertTrue(Path(fulfilled["path"]).is_file())
            validate_activation_response(fulfilled["response"])
            self.assertTrue(fulfilled["wire"].startswith(RSP_PREFIX))

            applied = oob.apply_activation_response(
                fulfilled["path"], force_soft_device=True
            )
            self.assertEqual(applied["status"], "ok")
            self.assertTrue(lr.TICKET_PATH.is_file())
            self.assertTrue(lr.ENVELOPE_PATH.is_file())
            # Request consumed
            self.assertFalse(Path(info["path"]).is_file())

            # Offline reopen
            lr._SESSION = None
            sess = lr.open_licensed_session(force_soft_device=True)
            self.assertEqual(len(sess.decrypted_cek_32), 32)
        finally:
            paths.USERDATA = old_ud
            lr.clear_trusted_keys()
            lr._SESSION = None


if __name__ == "__main__":
    unittest.main()
