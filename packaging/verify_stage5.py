"""Verify Stage 5 asset packs inside the portable tree."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "release" / "portable" / "ManmabotV1"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_reparse_point(path: Path) -> bool:
    if os.name != "nt" or not path.exists():
        return path.is_symlink() if path.exists() else False
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == -1:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def main() -> int:
    if not PORTABLE.is_dir():
        print(f"missing {PORTABLE}", file=sys.stderr)
        return 1

    engine = PORTABLE / "Engine"
    errors: list[str] = []

    data_pack = engine / "data.pack"
    if not data_pack.is_file():
        errors.append("missing Engine/data.pack")
    else:
        print(f"OK data.pack size={data_pack.stat().st_size}")

    analysis_pack = engine / "analysis_text.pack"
    if not analysis_pack.is_file():
        errors.append("missing Engine/analysis_text.pack")
    else:
        print(f"OK analysis_text.pack size={analysis_pack.stat().st_size}")

    data_dir = engine / "data"
    if data_dir.is_dir() and not _is_reparse_point(data_dir) and not data_dir.is_symlink():
        pngs = list((data_dir / "maps").rglob("*.png")) if (data_dir / "maps").is_dir() else []
        if len(pngs) > 10:
            errors.append(
                f"Engine/data is a real folder with {len(pngs)} PNGs "
                "(Stage 5 should leave only data.pack, or a junction after ensure)"
            )
    elif data_dir.exists():
        print(f"OK Engine/data present as junction/symlink (post-ensure OK)")

    # offsets.json may be restored by ensure_packed_assets (overlay). That is OK
    # when analysis_text.pack exists. Fail only if pack is missing (handled above)
    # and plain offsets remain without a pack.
    offsets = engine / "analysis" / "offsets.json"
    if offsets.is_file() and not analysis_pack.is_file():
        errors.append("plain offsets.json without analysis_text.pack")
    elif not offsets.is_file() and analysis_pack.is_file():
        print("OK offsets.json absent (pre-ensure / packed)")
    elif offsets.is_file():
        print("OK offsets.json present (likely post-ensure overlay)")

    # Round-trip smoke using development Engine helpers.
    sys.path.insert(0, str(ROOT / "Engine"))
    try:
        from session.asset_pack_format import extract_pack
        import tempfile

        with tempfile.TemporaryDirectory(prefix="verify_stage5_") as tmp:
            dest = Path(tmp) / "data"
            info = extract_pack(data_pack, dest)
            maps = dest / "maps"
            if not maps.is_dir():
                errors.append("extracted pack missing maps/")
            else:
                print(f"OK extract data.pack files={info.get('files')} maps_ok")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"data.pack extract failed: {exc}")

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("OK — Stage 5 asset pack verify passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
