"""BUILD carry-forward + public MMB2 header peek."""
from __future__ import annotations

import json
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

from crypto.pack_format import peek_mmb2_public_header
from crypto.seller_cli import cek_ops, signing
from crypto.seller_cli.store import SellerStore
from mmb2_stage5 import (
    carry_forward_existing_pack,
    pack_directory_mmb2,
    publish_verified_pack_pair,
    build_mmb2_blob,
)

PRODUCT = "00000000-0000-4000-8000-000000000001"


class TestPackCarryForward(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.seller = SellerStore(self.root / "SellerData")
        signing.create_signing_key(self.seller)
        self.cek = cek_ops.create_cek(self.seller, product_id=PRODUCT)
        self.engine = self.root / "Engine"
        self.engine.mkdir()
        self.data_src = self.root / "data_src"
        self.data_src.mkdir()
        (self.data_src / "maps").mkdir()
        (self.data_src / "maps" / "a.png").write_bytes(b"png")
        self.an_src = self.root / "an_src"
        self.an_src.mkdir()
        (self.an_src / "registry").mkdir()
        (self.an_src / "registry" / "offsets.json").write_text("{}", encoding="utf-8")
        (self.an_src / "data").mkdir()
        (self.an_src / "data" / "names.csv").write_text("a,b\n", encoding="utf-8")
        (self.an_src / "dll").mkdir()
        (self.an_src / "dll" / "print_state.dll").write_bytes(b"MZ-fake")

    def tearDown(self) -> None:
        self.seller.close()
        self._td.cleanup()

    def test_peek_public_header(self) -> None:
        out = self.root / "one.pack"
        info = pack_directory_mmb2(
            self.data_src,
            out,
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
        )
        header = peek_mmb2_public_header(out.read_bytes())
        self.assertEqual(header["cek_id"], self.cek["cek_id"])
        self.assertEqual(header["product_id"], PRODUCT)
        self.assertEqual(header["pack_id_hex"], info["pack_id_hex"])

    def test_data_only_publish_carry_forwards_analysis(self) -> None:
        data_blob, data_meta = build_mmb2_blob(
            {"maps/a.png": b"png"},
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
            note="stage5-data",
        )
        an_blob, an_meta = build_mmb2_blob(
            {
                "registry/offsets.json": b"{}",
                "data/names.csv": b"a,b\n",
                "dll/print_state.dll": b"MZ-fake",
            },
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
            note="stage5-analysis",
        )
        first = publish_verified_pack_pair(
            engine_dir=self.engine,
            data_blob=data_blob,
            data_meta=data_meta,
            analysis_blob=an_blob,
            analysis_meta=an_meta,
            seller_root=self.seller.root,
        )
        self.assertIn("analysis_text.pack", first["packs"])
        an_sha = first["packs"]["analysis_text.pack"]["sha256"]
        an_pid = first["packs"]["analysis_text.pack"]["pack_id_hex"]

        data_blob2, data_meta2 = build_mmb2_blob(
            {"maps/a.png": b"png2"},
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
            note="stage5-data",
        )
        second = publish_verified_pack_pair(
            engine_dir=self.engine,
            data_blob=data_blob2,
            data_meta=data_meta2,
            analysis_blob=None,
            analysis_meta=None,
            seller_root=self.seller.root,
        )
        packs = second["packs"]
        self.assertIn("data.pack", packs)
        self.assertIn("analysis_text.pack", packs)
        self.assertTrue(packs["analysis_text.pack"].get("carried_forward"))
        self.assertEqual(packs["analysis_text.pack"]["sha256"], an_sha)
        self.assertEqual(packs["analysis_text.pack"]["pack_id_hex"], an_pid)
        build = json.loads((self.engine / "BUILD.json").read_text(encoding="utf-8"))
        self.assertEqual(set(build["packs"]), {"data.pack", "analysis_text.pack"})

    def test_carry_forward_cek_mismatch_refused(self) -> None:
        blob, meta = build_mmb2_blob(
            {"registry/offsets.json": b"{}"},
            seller_root=self.seller.root,
            cek_id=self.cek["cek_id"],
            product_id=PRODUCT,
            note="stage5-analysis",
        )
        (self.engine / "analysis_text.pack").write_bytes(blob)
        with self.assertRaises(RuntimeError):
            carry_forward_existing_pack(
                self.engine,
                "analysis_text.pack",
                cek_id="00000000-0000-4000-8000-000000000099",
                product_id=PRODUCT,
            )
        del meta


class TestAnalysisDllOverlay(unittest.TestCase):
    def test_overlay_dll_preferred(self) -> None:
        from session.analysis_overlay import (
            analysis_dll_path,
            set_analysis_overlay,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "dll").mkdir()
            (root / "dll" / "print_state.dll").write_bytes(b"MZ")
            set_analysis_overlay(root)
            try:
                path = analysis_dll_path("print_state.dll")
                self.assertEqual(path.resolve(), (root / "dll" / "print_state.dll").resolve())
            finally:
                set_analysis_overlay(None)


if __name__ == "__main__":
    unittest.main()
