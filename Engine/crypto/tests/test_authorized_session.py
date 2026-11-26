"""Ticket → CEK → AuthorizedSession → MMB2 roundtrip."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

from Engine.crypto.authorized_session import SessionError, open_authorized_session
from Engine.crypto.device_key import open_or_create_device_key
from Engine.crypto.pack_format import Mmb2Reader, write_pack
from Engine.crypto.soft_key import oaep_encrypt_cek
from Engine.crypto.ticket import envelope_hash_hex, sign_ticket


@unittest.skipUnless(sys.platform == "win32", "DPAPI Soft key")
class TestAuthorizedSession(unittest.TestCase):
    def test_full_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = Path(td)
            device = open_or_create_device_key(store, force_soft=True)
            pub = load_der_public_key(device.get_public_key_spki_der())
            cek = bytes(range(32))
            wrapped = oaep_encrypt_cek(pub, cek)  # type: ignore[arg-type]

            product = "00000000-0000-4000-8000-000000000001"
            cek_id = "00000000-0000-4000-8000-0000000000ce"
            envelope = {
                "format_version": 1,
                "cek_id": cek_id,
                "wrap_alg": "RSA-OAEP-SHA256",
                "wrapped_cek": wrapped.hex(),
            }
            sk = Ed25519PrivateKey.generate()
            core = {
                "format_version": 1,
                "kid": "k1",
                "license_id": "lic-demo",
                "product_id": product,
                "cek_id": cek_id,
                "device_id": device.device_id,
                "binding_generation": 1,
                "envelope_hash": envelope_hash_hex(envelope),
            }
            ticket = sign_ticket(core, sk)
            session = open_authorized_session(
                ticket=ticket,
                envelope=envelope,
                device=device,
                trusted_keys={"k1": sk.public_key()},
                expected_product_id=product,
            )
            self.assertEqual(session.decrypted_cek_32, cek)

            blob = write_pack(
                {"maps/a.png": b"png-bytes"},
                cek=cek,
                product_id=product,
                cek_id=cek_id,
            )
            out = Mmb2Reader(blob, session).read_all()
            self.assertEqual(out["maps/a.png"], b"png-bytes")

    def test_reject_before_decrypt_on_bad_sig(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            device = open_or_create_device_key(Path(td), force_soft=True)
            pub = load_der_public_key(device.get_public_key_spki_der())
            cek = bytes(range(32))
            wrapped = oaep_encrypt_cek(pub, cek)  # type: ignore[arg-type]
            product = "00000000-0000-4000-8000-000000000001"
            cek_id = "00000000-0000-4000-8000-0000000000ce"
            envelope = {
                "format_version": 1,
                "cek_id": cek_id,
                "wrap_alg": "RSA-OAEP-SHA256",
                "wrapped_cek": wrapped.hex(),
            }
            sk = Ed25519PrivateKey.generate()
            core = {
                "format_version": 1,
                "kid": "k1",
                "license_id": "lic-demo",
                "product_id": product,
                "cek_id": cek_id,
                "device_id": device.device_id,
                "binding_generation": 1,
                "envelope_hash": envelope_hash_hex(envelope),
            }
            ticket = sign_ticket(core, sk)
            ticket["signature"] = "00" * 64
            with self.assertRaises(SessionError):
                open_authorized_session(
                    ticket=ticket,
                    envelope=envelope,
                    device=device,
                    trusted_keys={"k1": sk.public_key()},
                    expected_product_id=product,
                )


if __name__ == "__main__":
    unittest.main()
