"""Stage 5 — build obfuscated asset packs inside the portable tree.

Packs:
  Engine/data.pack           ← entire Engine/data (maps, cursors, catalog, world…)
  Engine/analysis_text.pack  ← sensitive analysis text/json (offsets, tables)

After packing, plain sources are removed from the portable tree so customers
cannot casually browse PNGs / offset files. DLLs and binaries under analysis
remain on disk.

Dev tree is never modified.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
PORTABLE = REPO_ROOT / "release" / "portable" / "ManmabotV1"

# Sensitive analysis text/json kept out of plain folders in customer builds.
# DLLs / .pyd / binaries are left alone.
ANALYSIS_INCLUDE_SUFFIXES = {".json", ".txt", ".yaml", ".yml", ".md", ".bak"}
ANALYSIS_INCLUDE_NAMES = {
    "offsets.json",
    "char_offsets.txt",
    "zone_table.json",
    "entity_offsets.txt",
    "inventory_offsets.txt",
    "skill_offsets.txt",
}


def _engine_on_sys_path() -> Path:
    """Import format helpers from the *development* Engine (not portable .pyd)."""
    eng = REPO_ROOT / "Engine"
    text = str(eng)
    if text not in sys.path:
        sys.path.insert(0, text)
    return eng


def _should_pack_analysis_file(path: Path, analysis_root: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in ANALYSIS_INCLUDE_SUFFIXES:
        return False
    # Skip huge image dumps under analysis/*/image if any remain.
    parts = {p.lower() for p in path.relative_to(analysis_root).parts}
    if "image" in parts and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return False
    return True


def build_data_pack(engine: Path, *, dry_run: bool) -> dict:
    from session.asset_pack_format import build_pack

    src = engine / "data"
    out = engine / "data.pack"
    if not src.is_dir():
        return {"skipped": True, "reason": "no Engine/data"}
    if dry_run:
        files = sum(1 for _ in src.rglob("*") if _.is_file())
        return {"dry_run": True, "files": files, "pack": str(out)}
    info = build_pack(src, out)
    # Remove plain tree after successful pack.
    shutil.rmtree(src)
    info["removed_plain"] = str(src)
    return info


def build_analysis_text_pack(engine: Path, *, dry_run: bool) -> dict:
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
        # Delete packed plain text from portable analysis (keep DLLs etc.).
        removed = 0
        for rel in packed_rels:
            plain = analysis / rel
            if plain.is_file():
                plain.unlink()
                removed += 1
                # prune empty parents up to analysis/
                parent = plain.parent
                while parent != analysis and parent.is_dir():
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
        info["removed_plain_files"] = removed
        return info


def pack_portable_assets(*, dry_run: bool = False) -> dict:
    if not PORTABLE.is_dir():
        raise FileNotFoundError(f"portable tree missing: {PORTABLE}")
    _engine_on_sys_path()
    engine = PORTABLE / "Engine"
    if not engine.is_dir():
        raise FileNotFoundError(f"Engine missing under portable: {engine}")

    data_info = build_data_pack(engine, dry_run=dry_run)
    analysis_info = build_analysis_text_pack(engine, dry_run=dry_run)
    return {"data": data_info, "analysis_text": analysis_info, "portable": str(PORTABLE)}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 5 asset pack builder")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = pack_portable_assets(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Stage 5 pack result:")
    for key, val in result.items():
        print(f"  {key}: {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
