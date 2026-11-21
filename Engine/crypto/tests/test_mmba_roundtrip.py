"""Independent MMB2 Writer/Reader roundtrip tests (no asset_store)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Allow `python Engine/crypto/tests/test_mmba_roundtrip.py` from repo root.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Engine.crypto.errors import PackFormatError, PathPolicyError, SessionBindingError
from Engine.crypto.kdf import derive_manifest_key, derive_pack_aes_key, derived_nonce
from Engine.crypto.pack_format import Mmb2Reader, SimplePackSession, read_pack, write_pack
from Engine.crypto.paths import canonicalize_pack_path


PRODUCT = "00000000-0000-4000-8000-000000000001"
CEK_ID = "00000000-0000-4000-8000-0000000000ce"
# Fixed test CEK — NEVER use for customer licenses.
TEST_CEK = bytes(range(32))
TEST_PACK_ID = bytes(range(16, 32))


def _session() -> SimplePackSession:
    return SimplePackSession(
        authorized_product_id=PRODUCT,
        authorized_cek_id=CEK_ID,
        decrypted_cek_32=TEST_CEK,
    )


class TestPaths(unittest.TestCase):
    def test_canonical(self) -> None:
        self.assertEqual(canonicalize_pack_path("maps/a.png"), "maps/a.png")

    def test_reject_dotdot(self) -> None:
        with self.assertRaises(PathPolicyError):
            canonicalize_pack_path("a/../b")

    def test_reject_backslash(self) -> None:
        with self.assertRaises(PathPolicyError):
            canonicalize_pack_path("a\\b")

    def test_reject_reserved(self) -> None:
        with self.assertRaises(PathPolicyError):
            canonicalize_pack_path("maps/CON.txt")


class TestKdf(unittest.TestCase):
    def test_nonce(self) -> None:
        self.assertEqual(derived_nonce(0), b"\x00" * 12)
        self.assertEqual(derived_nonce(1), b"\x00" * 4 + (1).to_bytes(8, "big"))
        self.assertEqual(derived_nonce(0x1122334455667788), b"\x00" * 4 + bytes.fromhex("1122334455667788"))

    def test_hkdf_deterministic(self) -> None:
        k1 = derive_pack_aes_key(TEST_CEK, TEST_PACK_ID, CEK_ID)
        k2 = derive_pack_aes_key(TEST_CEK, TEST_PACK_ID, CEK_ID)
        m1 = derive_manifest_key(TEST_CEK, TEST_PACK_ID, CEK_ID)
        self.assertEqual(len(k1), 32)
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, m1)


class TestRoundtrip(unittest.TestCase):
    def test_basic_roundtrip(self) -> None:
        entries = {
            "maps/one.png": b"hello-map",
            "data/empty.bin": b"",
            "data/big.txt": os.urandom(4096),
        }
        blob = write_pack(
            entries,
            cek=TEST_CEK,
            product_id=PRODUCT,
            cek_id=CEK_ID,
            pack_id=TEST_PACK_ID,
        )
        self.assertTrue(blob.startswith(b"MMB2"))
        out = read_pack(blob, _session())
        self.assertEqual(set(out), set(entries))
        for k, v in entries.items():
            self.assertEqual(out[k], v)

    def test_empty_entry_only_with_others(self) -> None:
        # empty pack rejected; empty entry among others OK
        blob = write_pack(
            {"a.txt": b"", "b.txt": b"x"},
            cek=TEST_CEK,
            product_id=PRODUCT,
            cek_id=CEK_ID,
            pack_id=TEST_PACK_ID,
        )
        out = read_pack(blob, _session())
        self.assertEqual(out["a.txt"], b"")
        self.assertEqual(out["b.txt"], b"x")

    def test_reject_empty_pack(self) -> None:
        with self.assertRaises(PackFormatError):
            write_pack({}, cek=TEST_CEK, product_id=PRODUCT, cek_id=CEK_ID)

    def test_session_product_mismatch(self) -> None:
        blob = write_pack(
            {"a.txt": b"1"},
            cek=TEST_CEK,
            product_id=PRODUCT,
            cek_id=CEK_ID,
            pack_id=TEST_PACK_ID,
        )
        bad = SimplePackSession(
            authorized_product_id="00000000-0000-4000-8000-000000000099",
            authorized_cek_id=CEK_ID,
            decrypted_cek_32=TEST_CEK,
        )
        with self.assertRaises(SessionBindingError):
            Mmb2Reader(blob, bad)

    def test_tamper_manifest(self) -> None:
        blob = bytearray(
            write_pack(
                {"a.txt": b"1"},
                cek=TEST_CEK,
                product_id=PRODUCT,
                cek_id=CEK_ID,
                pack_id=TEST_PACK_ID,
            )
        )
        # Flip a byte in the middle of the file (likely manifest/data).
        mid = len(blob) // 2
        blob[mid] ^= 0x5A
        with self.assertRaises(PackFormatError):
            read_pack(bytes(blob), _session())

    def test_tamper_ciphertext(self) -> None:
        blob = bytearray(
            write_pack(
                {"a.txt": b"plaintext-payload"},
                cek=TEST_CEK,
                product_id=PRODUCT,
                cek_id=CEK_ID,
                pack_id=TEST_PACK_ID,
            )
        )
        # Last bytes are data region; flip last ciphertext byte.
        blob[-1] ^= 0x01
        with self.assertRaises(PackFormatError):
            read_pack(bytes(blob), _session())

    def test_wrong_cek(self) -> None:
        blob = write_pack(
            {"a.txt": b"1"},
            cek=TEST_CEK,
            product_id=PRODUCT,
            cek_id=CEK_ID,
            pack_id=TEST_PACK_ID,
        )
        bad = SimplePackSession(
            authorized_product_id=PRODUCT,
            authorized_cek_id=CEK_ID,
            decrypted_cek_32=bytes([x ^ 0xFF for x in TEST_CEK]),
        )
        with self.assertRaises(PackFormatError):
            read_pack(blob, bad)

    def test_case_collision_rejected(self) -> None:
        with self.assertRaises(PathPolicyError):
            write_pack(
                {"Maps/A.png": b"1", "maps/a.png": b"2"},
                cek=TEST_CEK,
                product_id=PRODUCT,
                cek_id=CEK_ID,
            )

    def test_list_and_single_read(self) -> None:
        blob = write_pack(
            {"x/y.bin": b"abc", "z.dat": b"zz"},
            cek=TEST_CEK,
            product_id=PRODUCT,
            cek_id=CEK_ID,
            pack_id=TEST_PACK_ID,
        )
        r = Mmb2Reader(blob, _session())
        self.assertEqual(sorted(r.list_paths()), ["x/y.bin", "z.dat"])
        self.assertEqual(r.read_entry("x/y.bin"), b"abc")


class TestVectorsExport(unittest.TestCase):
    """Emit deterministic vector snippets for interop with external vector packs."""

    def test_print_key_vectors(self) -> None:
        aes = derive_pack_aes_key(TEST_CEK, TEST_PACK_ID, CEK_ID)
        man = derive_manifest_key(TEST_CEK, TEST_PACK_ID, CEK_ID)
        # Stable hex for README / external compare
        self.assertEqual(len(aes.hex()), 64)
        self.assertEqual(len(man.hex()), 64)
        blob = write_pack(
            {"hello.txt": b"hello", "empty": b""},
            cek=TEST_CEK,
            product_id=PRODUCT,
            cek_id=CEK_ID,
            pack_id=TEST_PACK_ID,
        )
        out_dir = Path(__file__).resolve().parent / "_generated"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "sample.mmb2").write_bytes(blob)
        (out_dir / "hkdf_vectors.txt").write_text(
            f"cek={TEST_CEK.hex()}\n"
            f"pack_id={TEST_PACK_ID.hex()}\n"
            f"cek_id={CEK_ID}\n"
            f"pack_aes_key={aes.hex()}\n"
            f"manifest_key={man.hex()}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
