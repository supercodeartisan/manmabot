"""Ed25519 ticket + JCS unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from Engine.crypto.jcs import canonicalize, dumps, loads_strict
from Engine.crypto.ticket import TicketError, envelope_hash_hex, sign_ticket, verify_ticket


class TestJcs(unittest.TestCase):
    def test_key_order(self) -> None:
        a = canonicalize({"b": 1, "a": 2})
        self.assertEqual(a, '{"a":2,"b":1}')

    def test_dup_reject(self) -> None:
        with self.assertRaises(Exception):
            loads_strict('{"a":1,"a":2}')


class TestTicket(unittest.TestCase):
    def setUp(self) -> None:
        self.sk = Ed25519PrivateKey.generate()
        self.pk = self.sk.public_key()
        self.trusted = {"test-kid-1": self.pk}
        self.envelope = {
            "format_version": 1,
            "cek_id": "00000000-0000-4000-8000-0000000000ce",
            "wrapped_cek": "aa" * 32,
            "wrap_alg": "RSA-OAEP-SHA256",
        }
        self.core = {
            "format_version": 1,
            "kid": "test-kid-1",
            "license_id": "lic-1",
            "product_id": "00000000-0000-4000-8000-000000000001",
            "cek_id": "00000000-0000-4000-8000-0000000000ce",
            "device_id": "ab" * 32,
            "binding_generation": 1,
            "envelope_hash": envelope_hash_hex(self.envelope),
        }

    def test_sign_verify(self) -> None:
        ticket = sign_ticket(self.core, self.sk)
        vt = verify_ticket(
            ticket,
            trusted_keys=self.trusted,
            expected_device_id=self.core["device_id"],
            expected_product_id=self.core["product_id"],
            envelope=self.envelope,
        )
        self.assertEqual(vt.license_id, "lic-1")
        self.assertEqual(vt.binding_generation, 1)

    def test_bad_signature(self) -> None:
        ticket = sign_ticket(self.core, self.sk)
        ticket["signature"] = "00" * 64
        with self.assertRaises(TicketError):
            verify_ticket(ticket, trusted_keys=self.trusted, envelope=self.envelope)

    def test_envelope_mismatch(self) -> None:
        ticket = sign_ticket(self.core, self.sk)
        bad_env = dict(self.envelope)
        bad_env["wrapped_cek"] = "bb" * 32
        with self.assertRaises(TicketError):
            verify_ticket(ticket, trusted_keys=self.trusted, envelope=bad_env)

    def test_unknown_kid(self) -> None:
        ticket = sign_ticket(self.core, self.sk)
        with self.assertRaises(TicketError):
            verify_ticket(ticket, trusted_keys={}, envelope=self.envelope)

    def test_roundtrip_json_bytes(self) -> None:
        ticket = sign_ticket(self.core, self.sk)
        raw = dumps(ticket)
        vt = verify_ticket(raw, trusted_keys=self.trusted, envelope=self.envelope)
        self.assertEqual(vt.cek_id, self.core["cek_id"])


if __name__ == "__main__":
    unittest.main()
