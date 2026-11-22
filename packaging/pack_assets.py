"""Stage 5 — build asset packs inside the portable tree.

Default (Phase 1): **MMB2** via SellerData vault + pack_id reservation.
Legacy MMBA v1: ``--legacy-mmba`` (transition only).

Packs:
  Engine/data.pack           ← portable Engine/data (maps, cursors, catalog, world…)
  Engine/analysis_text.pack  ← repo Engine/analysis texts/csv/dll (offsets, tables)

Analysis membership is snapshotted from the **dev** ``Engine/analysis`` tree so a
stripped portable cannot shrink the pack. After packing, matching plains are
removed from the portable tree only. Dev tree is never modified. Customer packs
never contain CEK / signing private keys.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from mmb2_stage5 import (
    build_mmb2_blob,
    pack_directory_mmb2,
    publish_verified_pack_pair,
    snapshot_tree,
)

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
PORTABLE = REPO_ROOT / "release" / "portable" / "ManmabotV1"

ANALYSIS_INCLUDE_SUFFIXES = {".json", ".txt", ".yaml", ".yml", ".md", ".bak", ".csv"}


def _engine_on_sys_path() -> Path:
    eng = REPO_ROOT / "Engine"
    text = str(eng)
    if text not in sys.path:
        sys.path.insert(0, text)
    return eng


def _default_seller_root() -> Path:
    env = os.environ.get("MANMABOT_SELLER_DATA", "").strip()
    if env:
        return Path(env)
    # Prefer Seller/SellerData (tool+vault bundle); fall back to legacy root.
    nested = REPO_ROOT / "Seller" / "SellerData"
    legacy = REPO_ROOT / "SellerData"
    if (nested / "license.db").is_file() or (nested / "vault_key.bin").is_file():
        return nested
    if (legacy / "license.db").is_file() or (legacy / "vault_key.bin").is_file():
        return legacy
    return nested


def _should_pack_analysis_file(path: Path, analysis_root: Path) -> bool:
    if not path.is_file():
        return False
    rel = path.relative_to(analysis_root)
    parts_tuple = rel.parts
    parts = {p.lower() for p in parts_tuple}
    suffix = path.suffix.lower()
    # Analysis DLLs ship inside the same MMB2 as offset text (Wave 2).
    # Skip build debris (* .new.dll / *.old.dll) even under dll/.
    if suffix == ".dll":
        stem_l = path.name.lower()
        if stem_l.endswith(".new.dll") or stem_l.endswith(".old.dll"):
            return False
        return len(parts_tuple) >= 2 and parts_tuple[0].lower() == "dll"
    if suffix not in ANALYSIS_INCLUDE_SUFFIXES:
        return False
    if "image" in parts and suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return False
    return True


def _snapshot_analysis_entries(analysis: Path) -> tuple[dict[str, bytes], list[str]]:
    packed_rels: list[str] = []
    entries: dict[str, bytes] = {}
    for path in sorted(analysis.rglob("*")):
        if not _should_pack_analysis_file(path, analysis):
            continue
        rel = path.relative_to(analysis).as_posix()
        packed_rels.append(rel)
        entries[rel] = path.read_bytes()
    return entries, packed_rels


def _analysis_snapshot_root(portable_engine: Path) -> Path:
    """Dev ``Engine/analysis`` is the truth for pack membership.

    Portable analysis is often already stripped after a prior Stage 5. Snapshotting
    only leftovers (e.g. dll/csv) would replace a full ``analysis_text.pack`` with a
    shrunk one and drop registry/offsets. Always prefer the repo analysis tree when
    present; fall back to portable only if the dev tree is missing.
    """
    src = REPO_ROOT / "Engine" / "analysis"
    if src.is_dir():
        return src
    return portable_engine / "analysis"


def _build_mmb2_pair(
    engine: Path,
    *,
    seller_root: Path,
    cek_id: str,
    product_id: str | None,
    dry_run: bool,
) -> dict:
    """
    Build + independently verify both packs in memory, then publish together
    and write Engine/BUILD.json last (distinct pack_ids, shared cek_id).
    """
    data_src = engine / "data"
    portable_analysis = engine / "analysis"
    analysis_src = _analysis_snapshot_root(engine)

    data_entries: dict[str, bytes] | None = None
    analysis_entries: dict[str, bytes] | None = None
    analysis_rels: list[str] = []

    if data_src.is_dir():
        data_entries = snapshot_tree(data_src)
    if analysis_src.is_dir():
        analysis_entries, analysis_rels = _snapshot_analysis_entries(analysis_src)
        if not analysis_entries:
            analysis_entries = None

    if data_entries is None and analysis_entries is None:
        return {"skipped": True, "reason": "no data or analysis text sources"}

    if dry_run:
        return {
            "dry_run": True,
            "data_files": len(data_entries or {}),
            "analysis_files": len(analysis_entries or {}),
            "sample_analysis": analysis_rels[:8],
            "analysis_snapshot": str(analysis_src),
        }

    data_blob = data_meta = None
    analysis_blob = analysis_meta = None
    if data_entries is not None:
        data_blob, data_meta = build_mmb2_blob(
            data_entries,
            seller_root=seller_root,
            cek_id=cek_id,
            product_id=product_id,
            note="stage5-data",
        )
    if analysis_entries is not None:
        analysis_blob, analysis_meta = build_mmb2_blob(
            analysis_entries,
            seller_root=seller_root,
            cek_id=cek_id,
            product_id=product_id,
            note="stage5-analysis",
        )

    published = publish_verified_pack_pair(
        engine_dir=engine,
        data_blob=data_blob,
        data_meta=data_meta,
        analysis_blob=analysis_blob,
        analysis_meta=analysis_meta,
        seller_root=seller_root,
    )

    removed: dict[str, object] = {}
    if data_entries is not None and data_src.is_dir():
        shutil.rmtree(data_src)
        removed["data"] = str(data_src)
    # Strip packed plains from the *portable* tree only — never touch repo analysis.
    if analysis_rels and portable_analysis.is_dir():
        n = 0
        for rel in analysis_rels:
            plain = portable_analysis / rel
            if plain.is_file():
                plain.unlink()
                n += 1
                parent = plain.parent
                while parent != portable_analysis and parent.is_dir():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        removed["analysis_files"] = n

    return {
        "format": "MMB2",
        "published": published,
        "removed_plain": removed,
        "data": data_meta,
        "analysis_text": analysis_meta,
        "analysis_snapshot": str(analysis_src),
    }


def build_data_pack(engine: Path, *, dry_run: bool) -> dict:
    """Legacy MMBA v1 (transition). Prefer MMB2 via pack_portable_assets."""
    from session.asset_pack_format import build_pack

    src = engine / "data"
    out = engine / "data.pack"
    if not src.is_dir():
        return {"skipped": True, "reason": "no Engine/data"}
    if dry_run:
        files = sum(1 for _ in src.rglob("*") if _.is_file())
        return {"dry_run": True, "files": files, "pack": str(out)}
    info = build_pack(src, out)
    shutil.rmtree(src)
    info["removed_plain"] = str(src)
    info["format"] = "MMBA"
    return info


def build_analysis_text_pack(engine: Path, *, dry_run: bool) -> dict:
    """Legacy MMBA v1 analysis pack."""
    from session.asset_pack_format import build_pack

    analysis = engine / "analysis"
    out = engine / "analysis_text.pack"
    if not analysis.is_dir():
        return {"skipped": True, "reason": "no Engine/analysis"}

    with tempfile.TemporaryDirectory(prefix="manmabot_analysis_pack_") as tmp:
        staging = Path(tmp) / "analysis"
        staging.mkdir(parents=True, exist_ok=True)
        packed_rels: list[str] = []
        for path in sorted(analysis.rglob("*")):
            if not _should_pack_analysis_file(path, analysis):
                continue
            rel = path.relative_to(analysis)
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dry_run:
                shutil.copy2(path, dst)
            packed_rels.append(rel.as_posix())

        if not packed_rels:
            return {"skipped": True, "reason": "no analysis text files"}

        if dry_run:
            return {
                "dry_run": True,
                "files": len(packed_rels),
                "pack": str(out),
                "sample": packed_rels[:8],
            }

        info = build_pack(staging, out)
        removed = 0
        for rel in packed_rels:
            plain = analysis / rel
            if plain.is_file():
                plain.unlink()
                removed += 1
                parent = plain.parent
                while parent != analysis and parent.is_dir():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        info["removed_plain_files"] = removed
        info["format"] = "MMBA"
        return info


def pack_portable_assets(
    *,
    dry_run: bool = False,
    legacy_mmba: bool = False,
    cek_id: str | None = None,
    product_id: str | None = None,
    seller_root: Path | None = None,
) -> dict:
    if not PORTABLE.is_dir():
        raise FileNotFoundError(f"portable tree missing: {PORTABLE}")
    _engine_on_sys_path()
    engine = PORTABLE / "Engine"
    if not engine.is_dir():
        raise FileNotFoundError(f"Engine missing under portable: {engine}")

    if legacy_mmba:
        data_info = build_data_pack(engine, dry_run=dry_run)
        analysis_info = build_analysis_text_pack(engine, dry_run=dry_run)
        return {
            "format": "MMBA",
            "data": data_info,
            "analysis_text": analysis_info,
            "portable": str(PORTABLE),
        }

    cek_id = cek_id or os.environ.get("MANMABOT_CEK_ID", "").strip() or None
    if not cek_id:
        raise RuntimeError(
            "MMB2 Stage5 requires --cek-id or MANMABOT_CEK_ID "
            "(or pass --legacy-mmba for transition builds)"
        )
    seller = Path(seller_root) if seller_root else _default_seller_root()
    pair = _build_mmb2_pair(
        engine,
        seller_root=seller,
        cek_id=cek_id,
        product_id=product_id,
        dry_run=dry_run,
    )
    collapsed = 0
    if not dry_run:
        from build_release import collapse_empty_dirs_in_portable

        collapsed = collapse_empty_dirs_in_portable(dry_run=False)
    return {
        "format": "MMB2",
        "cek_id": cek_id,
        "pair": pair,
        "data": pair.get("data"),
        "analysis_text": pair.get("analysis_text"),
        "portable": str(PORTABLE),
        "seller_root": str(seller),
        "collapsed_empty": collapsed,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 5 asset pack builder")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--legacy-mmba",
        action="store_true",
        help="Build MMBA v1 packs (transition only)",
    )
    parser.add_argument("--cek-id", default=None, help="Vault cek_id for MMB2")
    parser.add_argument("--product-id", default=None)
    parser.add_argument("--seller-data", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        result = pack_portable_assets(
            dry_run=args.dry_run,
            legacy_mmba=args.legacy_mmba,
            cek_id=args.cek_id,
            product_id=args.product_id,
            seller_root=args.seller_data,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Stage 5 pack result:")
    for key, val in result.items():
        print(f"  {key}: {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
