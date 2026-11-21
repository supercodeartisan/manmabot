"""Runtime TEMP materialize + MMB2 → asset_store wiring (no bot logic)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ENGINE = _ROOT / "Engine"
for p in (_ROOT, _ENGINE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from crypto.pack_format import SimplePackSession, write_pack
from session.analysis_overlay import (
    analysis_registry_file,
    analysis_overlay_root,
    set_analysis_overlay,
)
from session.analysis_temp import (
    cleanup_analysis_temp,
    create_analysis_temp,
    materialize_files,
    wipe_stale_analysis_temps,
)
from session.asset_store import is_mounted, mount_bytes
from session.licensed_runtime import load_pack_files, pack_magic


PRODUCT = "00000000-0000-4000-8000-000000000001"
CEK_ID = "00000000-0000-4000-8000-0000000000ce"
CEK = bytes(range(32))


class TestAnalysisTemp(unittest.TestCase):
    def tearDown(self) -> None:
        cleanup_analysis_temp()
        set_analysis_overlay(None)

    def test_materialize_and_overlay(self) -> None:
        root = create_analysis_temp()
        self.assertTrue(root.name.startswith("manmabot_an_"))
        self.assertEqual(analysis_overlay_root(), root.resolve())
        written = materialize_files(
            root,
            {"registry/offsets.json": b'{"PlayerBase": 1}\n'},
        )
        self.assertEqual(len(written), 1)
        offsets = analysis_registry_file("registry", "offsets.json")
        self.assertTrue(offsets.is_file())
        self.assertTrue(str(offsets).startswith(str(root)))
        # Absolute path (not CWD-relative)
        self.assertTrue(offsets.is_absolute())
        cleanup_analysis_temp()
        self.assertIsNone(analysis_overlay_root())
        self.assertFalse(root.exists())

    def test_stale_wipe_skips_alive(self) -> None:
        root = create_analysis_temp()
        # Alive pid → protect
        n = wipe_stale_analysis_temps(protect=root)
        self.assertGreaterEqual(n, 0)
        self.assertTrue(root.exists())
        cleanup_analysis_temp()


class TestMmb2ToAssetStore(unittest.TestCase):
    def test_pack_magic_and_mount(self) -> None:
        entries = {
            "maps/a.png": b"png-bytes",
            "catalog/items.json": b"[]",
        }
        blob = write_pack(
            entries,
            cek=CEK,
            product_id=PRODUCT,
            cek_id=CEK_ID,
        )
        with tempfile.TemporaryDirectory() as td:
            pack = Path(td) / "data.pack"
            pack.write_bytes(blob)
            self.assertEqual(pack_magic(pack), "mmb2")
            session = SimplePackSession(
                authorized_product_id=PRODUCT,
                authorized_cek_id=CEK_ID,
                decrypted_cek_32=CEK,
            )
            files = load_pack_files(pack, session=session)
            self.assertEqual(files["maps/a.png"], b"png-bytes")
            mount_root = Path(td) / "data"
            info = mount_bytes(mount_root, files)
            self.assertTrue(is_mounted())
            self.assertEqual(info["files"], 2)


class TestReaderOffsetsHook(unittest.TestCase):
    def tearDown(self) -> None:
        cleanup_analysis_temp()
        set_analysis_overlay(None)

    def test_realtime_default_offsets_uses_overlay(self) -> None:
        root = create_analysis_temp()
        materialize_files(root, {"registry/offsets.json": b"{}\n"})
        from app._01_perception.fix_realtime_monitor_reader import default_offsets_path

        path = default_offsets_path()
        self.assertEqual(path.resolve(), (root / "registry" / "offsets.json").resolve())


if __name__ == "__main__":
    unittest.main()
