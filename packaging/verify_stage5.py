"""Verify Stage 5 asset packs inside the portable tree (MMB2 or legacy MMBA)."""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
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


def _pack_magic(path: Path) -> str:
    with path.open("rb") as fh:
        magic = fh.read(4)
    if magic == b"MMB2":
        return "MMB2"
    if magic == b"MMBA":
        return "MMBA"
    return "unknown"


def _verify_mmb2(data_pack: Path, errors: list[str]) -> None:
    """Seller-side verify: needs MANMABOT_CEK_ID + SellerData (no CEK in package)."""
    sys.path.insert(0, str(ROOT / "Engine"))
    cek_id = os.environ.get("MANMABOT_CEK_ID", "").strip()
    if not cek_id:
        print("WARN MMB2 pack present; set MANMABOT_CEK_ID to round-trip verify")
        print(f"OK data.pack magic=MMB2 size={data_pack.stat().st_size}")
        return
    from crypto.seller_cli.store import SellerStore
    from crypto.pack_format import Mmb2Reader, SimplePackSession

    env = os.environ.get("MANMABOT_SELLER_DATA", "").strip()
    if env:
        seller = Path(env)
    else:
        nested = ROOT / "Seller" / "SellerData"
        legacy = ROOT / "SellerData"
        if (nested / "license.db").is_file() or (nested / "vault_key.bin").is_file():
            seller = nested
        elif (legacy / "license.db").is_file() or (legacy / "vault_key.bin").is_file():
            seller = legacy
        else:
            seller = nested
    store = SellerStore(seller)
    try:
        cfg = store.config()
        product_id = cfg.get("product_id")
        cek = store.vault().load(cek_id)
        session = SimplePackSession(
            authorized_product_id=product_id,
            authorized_cek_id=cek_id,
            decrypted_cek_32=cek,
        )
        files = Mmb2Reader(data_pack.read_bytes(), session).read_all()
        if not any(k.startswith("maps/") for k in files):
            errors.append("MMB2 data.pack has no maps/ entries")
        else:
            print(f"OK MMB2 data.pack files={len(files)} maps_ok")
        build_json = data_pack.with_suffix(data_pack.suffix + ".BUILD.json")
        if build_json.is_file():
            text = build_json.read_text(encoding="utf-8").upper()
            if "BEGIN PRIVATE" in text or '"CEK"' in text:
                errors.append("BUILD.json appears to contain secrets")
            else:
                print("OK BUILD.json has no private key / raw CEK field")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"MMB2 verify failed: {exc}")
    finally:
        store.close()


def _verify_mmba(data_pack: Path, errors: list[str]) -> None:
    sys.path.insert(0, str(ROOT / "Engine"))
    try:
        from session.asset_pack_format import extract_pack

        with tempfile.TemporaryDirectory(prefix="verify_stage5_") as tmp:
            dest = Path(tmp) / "data"
            info = extract_pack(data_pack, dest)
            maps = dest / "maps"
            if not maps.is_dir():
                errors.append("extracted pack missing maps/")
            else:
                print(f"OK extract MMBA data.pack files={info.get('files')} maps_ok")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"data.pack extract failed: {exc}")


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
        magic = _pack_magic(data_pack)
        print(f"OK data.pack size={data_pack.stat().st_size} magic={magic}")
        if magic == "MMB2":
            _verify_mmb2(data_pack, errors)
        elif magic == "MMBA":
            _verify_mmba(data_pack, errors)
        else:
            errors.append(f"unknown data.pack magic: {magic}")

    analysis_pack = engine / "analysis_text.pack"
    if not analysis_pack.is_file():
        errors.append("missing Engine/analysis_text.pack")
    else:
        print(
            f"OK analysis_text.pack size={analysis_pack.stat().st_size} "
            f"magic={_pack_magic(analysis_pack)}"
        )

    data_dir = engine / "data"
    if data_dir.is_dir() and not _is_reparse_point(data_dir) and not data_dir.is_symlink():
        pngs = list((data_dir / "maps").rglob("*.png")) if (data_dir / "maps").is_dir() else []
        if len(pngs) > 10:
            errors.append(
                f"Engine/data is a real folder with {len(pngs)} PNGs "
                "(Stage 5 should leave only data.pack, or a junction after ensure)"
            )
    elif data_dir.exists():
        print("OK Engine/data present as junction/symlink (post-ensure OK)")

    offsets = engine / "analysis" / "registry" / "offsets.json"
    if offsets.is_file() and not analysis_pack.is_file():
        errors.append("plain offsets.json without analysis_text.pack")
    elif not offsets.is_file() and analysis_pack.is_file():
        print("OK offsets.json absent (pre-ensure / packed)")
    elif offsets.is_file():
        print("OK offsets.json present (likely post-ensure overlay)")

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("OK — Stage 5 asset pack verify passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
