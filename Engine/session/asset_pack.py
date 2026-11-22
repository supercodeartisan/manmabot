"""Runtime ensure for Engine asset packs (MMBA v1 transition + MMB2).

Dev tree: plain ``Engine/data`` present → no-op.
Customer release:
  ``Engine/data.pack`` (MMBA or MMB2) → RAM via ``asset_store`` (no plain folder).
  ``Engine/analysis_text.pack`` → ``%TEMP%/manmabot_an_<id>/`` for registry text
  **and** ``dll/*.dll``; absolute paths via ``analysis_overlay``; wiped on exit.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from session.analysis_overlay import analysis_registry_file, set_analysis_overlay
from session.analysis_temp import (
    active_analysis_temp,
    cleanup_analysis_temp,
    create_analysis_temp,
    materialize_files,
    wipe_stale_analysis_temps,
)
from session.licensed_runtime import LicensedRuntimeError, load_pack_files, pack_magic
from session.paths import manmabot_root

DATA_PACK_NAME = "data.pack"
ANALYSIS_PACK_NAME = "analysis_text.pack"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def data_root() -> Path:
    """``Engine/data`` — a real folder in dev, a RAM mount in customer builds."""
    return manmabot_root() / "data"


def _is_reparse_point(path: Path) -> bool:
    import ctypes
    import os

    if os.name != "nt" or not path.exists():
        return path.is_symlink() if path.exists() else False
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == -1:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _dir_has_real_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    if _is_reparse_point(path):
        try:
            return any(path.iterdir())
        except OSError:
            return False
    try:
        return any(p.is_file() for p in path.rglob("*"))
    except OSError:
        return False


def _drop_exported_data_cache(data_dir: Path) -> None:
    import os

    if _is_reparse_point(data_dir) or data_dir.is_symlink():
        os.rmdir(data_dir)
    cache = manmabot_root().parent / "UserData" / ".asset_cache"
    data_cache = cache / "data"
    if data_cache.exists() and not _is_reparse_point(data_cache):
        shutil.rmtree(data_cache, ignore_errors=True)
    staging = cache / "analysis_text"
    if staging.exists() and not _is_reparse_point(staging):
        shutil.rmtree(staging, ignore_errors=True)


def ensure_data_pack(*, force: bool = False) -> dict:
    """Mount ``Engine/data.pack`` in RAM. Does not create plain ``Engine/data``."""
    engine = manmabot_root()
    pack_path = engine / DATA_PACK_NAME
    data_dir = engine / "data"
    if not pack_path.is_file():
        return {"action": "skipped", "reason": "no_pack"}

    if (
        data_dir.is_dir()
        and not _is_reparse_point(data_dir)
        and _dir_has_real_files(data_dir)
        and not force
    ):
        return {"action": "skipped", "reason": "plain_data_present"}

    _drop_exported_data_cache(data_dir)
    from session.asset_store import is_mounted, mount_bytes

    if is_mounted() and not force:
        return {"action": "memory", "root": str(data_dir), "reused": True}

    kind = pack_magic(pack_path)
    try:
        files = load_pack_files(pack_path)
    except LicensedRuntimeError as e:
        return {"action": "error", "reason": str(e), "pack_kind": kind}

    info = mount_bytes(data_dir, files)
    info["action"] = "memory"
    info["pack_kind"] = kind
    return info


def ensure_analysis_text_pack(*, force: bool = False) -> dict:
    """Materialize analysis text + dlls under per-instance TEMP; wire overlay paths."""
    engine = manmabot_root()
    pack_path = engine / ANALYSIS_PACK_NAME
    if not pack_path.is_file():
        # Dev / unpack tree: plain analysis under Engine/analysis (text + dll).
        set_analysis_overlay(None)
        return {"action": "skipped", "reason": "no_pack"}

    kind = pack_magic(pack_path)
    try:
        files = load_pack_files(pack_path)
    except LicensedRuntimeError as e:
        return {"action": "error", "reason": str(e), "pack_kind": kind}

    wipe_stale_analysis_temps(protect=active_analysis_temp())
    root = create_analysis_temp()
    written = materialize_files(root, files)
    offsets = analysis_registry_file("registry", "offsets.json")
    return {
        "action": "temp_materialize",
        "files": len(written),
        "overlay": str(root),
        "offsets_abs": str(offsets) if offsets.is_file() else None,
        "pack_kind": kind,
        "removed_on_exit": True,
    }


def ensure_packed_assets(*, force: bool = False) -> dict:
    """Idempotent startup hook: materialize packed assets if present."""
    from session.build_manifest import BuildManifestError, verify_engine_build_manifest

    engine = manmabot_root()
    try:
        manifest = verify_engine_build_manifest(engine)
    except BuildManifestError as e:
        return {
            "data": {"action": "error", "reason": str(e)},
            "analysis_text": {"action": "error", "reason": str(e)},
            "build": {"action": "error", "reason": str(e)},
        }
    return {
        "data": ensure_data_pack(force=force),
        "analysis_text": ensure_analysis_text_pack(force=force),
        "build": {
            "action": "ok" if manifest else "skipped",
            "build_id": (manifest or {}).get("build_id"),
            "cek_id": (manifest or {}).get("cek_id"),
        },
    }


def shutdown_packed_assets() -> None:
    """Explicit cleanup (also registered via atexit from analysis_temp)."""
    cleanup_analysis_temp()
