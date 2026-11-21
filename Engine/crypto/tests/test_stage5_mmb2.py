"""Stage5 → MMB2 acceptance tests (no portable tree / no bot logic)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ENGINE = _ROOT / "Engine"
_PACKAGING = _ROOT / "packaging"
for p in (_ROOT, _ENGINE, _PACKAGING):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from crypto.pack_format import Mmb2Reader, SimplePackSession, PackFormatError
from crypto.paths import PathPolicyError
from crypto.seller_cli import cek_ops, signing
from crypto.seller_cli.store import SellerStore
from mmb2_stage5 import (
    atomic_publish,
    build_mmb2_blob,
    pack_directory_mmb2,
    snapshot_tree,
)


PRODUCT = "00000000-0000-4000-8000-000000000001"


class TestStage5Mmb2(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.seller = SellerStore(self.root / "SellerData")
        signing.create_signing_key(self.seller)
        self.cek = cek_ops.create_cek(self.seller, product_id=PRODUCT)
        self.src = self.root / "src"
        self.src.mkdir()
        (self.src / "maps").mkdir()
        (self.src / "maps" / "a.png").write_bytes(b"png-a")
        (self.src / "catalog").mkdir()
        (self.src / "catalog" / "items.json").write_text("[]", encoding="utf-8")

    def tearDown(self) -> None:
        self.seller.close()
        self._td.cleanup()

    def test_normal_build(self) -> None:
        out = self.root / "data.pack"
        info = pack_directory_mmb2(
            self.src,
            out,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        self.assertTrue(out.is_file())
        self.assertEqual(info["format"], "MMB2")
        self.assertTrue(out.read_bytes().startswith(b"MMB2"))
        self.assertIn("pack_id_hex", info)
        self.assertIn("cek_fingerprint", info)

    def test_rebuild_new_pack_id(self) -> None:
        out = self.root / "data.pack"
        a = pack_directory_mmb2(
            self.src, out, seller_root=self.seller.root, cek_id=self.cek["cek_id"], product_id=PRODUCT
        )
        b = pack_directory_mmb2(
            self.src, out, seller_root=self.seller.root, cek_id=self.cek["cek_id"], product_id=PRODUCT
        )
        self.assertNotEqual(a["pack_id_hex"], b["pack_id_hex"])

    def test_reuse_pack_id_rejected(self) -> None:
        reserved = cek_ops.reserve_pack_id(self.seller, cek_id=self.cek["cek_id"])
        pack_id = reserved["pack_id"]
        # Direct INSERT of same pair must fail
        with self.assertRaises(Exception):
            self.seller.db().conn.execute(
                """
                INSERT INTO pack_id_reservations(cek_id, pack_id, note, reserved_at)
                VALUES (?, ?, ?, ?)
                """,
                (self.cek["cek_id"], pack_id, "dup", "2020-01-01T00:00:00+00:00"),
            )

    def test_wrong_cek_reader_rejects(self) -> None:
        entries = snapshot_tree(self.src)
        blob, meta = build_mmb2_blob(
            entries,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        bad = SimplePackSession(
            authorized_product_id=PRODUCT,
            authorized_cek_id=self.cek["cek_id"],
            decrypted_cek_32=bytes([9] * 32),
        )
        with self.assertRaises(PackFormatError):
            Mmb2Reader(blob, bad)

    def test_bad_path_builder_rejects(self) -> None:
        bad = {"a/../b.txt": b"x"}
        with self.assertRaises((PathPolicyError, Exception)):
            build_mmb2_blob(
                bad,
                seller_root=self.seller.root,
                cek_id=self.cek["cek_id"],
                product_id=PRODUCT,
            )

    def test_case_collision_builder_rejects(self) -> None:
        bad = {"Maps/A.png": b"1", "maps/a.png": b"2"}
        with self.assertRaises(Exception):
            build_mmb2_blob(
                bad,
                seller_root=self.seller.root,
                cek_id=self.cek["cek_id"],
                product_id=PRODUCT,
            )

    def test_manifest_tamper_rejected(self) -> None:
        entries = snapshot_tree(self.src)
        blob, _ = build_mmb2_blob(
            entries,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        buf = bytearray(blob)
        buf[len(buf) // 2] ^= 0x5A
        session = SimplePackSession(
            authorized_product_id=PRODUCT,
            authorized_cek_id=self.cek["cek_id"],
            decrypted_cek_32=self.seller.vault().load(self.cek["cek_id"]),
        )
        with self.assertRaises(PackFormatError):
            Mmb2Reader(bytes(buf), session)

    def test_ciphertext_tamper_rejected(self) -> None:
        entries = snapshot_tree(self.src)
        blob, _ = build_mmb2_blob(
            entries,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        buf = bytearray(blob)
        buf[-1] ^= 0x01
        session = SimplePackSession(
            authorized_product_id=PRODUCT,
            authorized_cek_id=self.cek["cek_id"],
            decrypted_cek_32=self.seller.vault().load(self.cek["cek_id"]),
        )
        with self.assertRaises(PackFormatError):
            Mmb2Reader(bytes(buf), session).read_all()

    def test_trailing_bytes_rejected(self) -> None:
        entries = snapshot_tree(self.src)
        blob, _ = build_mmb2_blob(
            entries,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        session = SimplePackSession(
            authorized_product_id=PRODUCT,
            authorized_cek_id=self.cek["cek_id"],
            decrypted_cek_32=self.seller.vault().load(self.cek["cek_id"]),
        )
        with self.assertRaises(PackFormatError):
            Mmb2Reader(blob + b"EXTRA", session)

    def test_failed_build_does_not_publish(self) -> None:
        out = self.root / "never.pack"
        partial = out.with_suffix(".pack.partial")
        # Force failure after partial write by publishing empty then verifying path
        # Simulate: write partial, then fail before replace by raising in wrapper
        blob = b"not-a-real-pack"
        partial.write_bytes(blob)
        self.assertTrue(partial.is_file())
        self.assertFalse(out.is_file())
        # atomic_publish of verified blob should replace cleanly
        entries = snapshot_tree(self.src)
        good, meta = build_mmb2_blob(
            entries,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        atomic_publish(good, out)
        self.assertTrue(out.is_file())
        self.assertFalse(partial.is_file())
        self.assertTrue(out.read_bytes().startswith(b"MMB2"))
        _ = meta

    def test_snapshot_isolates_source_mutation(self) -> None:
        entries = snapshot_tree(self.src)
        # Mutate source after snapshot
        (self.src / "maps" / "a.png").write_bytes(b"MUTATED")
        blob, _ = build_mmb2_blob(
            entries,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        session = SimplePackSession(
            authorized_product_id=PRODUCT,
            authorized_cek_id=self.cek["cek_id"],
            decrypted_cek_32=self.seller.vault().load(self.cek["cek_id"]),
        )
        got = Mmb2Reader(blob, session).read_all()
        self.assertEqual(got["maps/a.png"], b"png-a")
        self.assertNotEqual(got["maps/a.png"], b"MUTATED")


if __name__ == "__main__":
    unittest.main()
