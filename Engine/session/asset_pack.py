"""Runtime ensure for obfuscated Engine asset packs.

Dev tree: plain ``Engine/data`` present → no-op.
Customer release:
  ``Engine/data.pack`` is served from RAM (no ``Engine/data`` folder).
  ``Engine/analysis_text.pack`` is written for the C offset readers and
  removed when the process exits.
"""
from __future__ import annotations

import atexit
import ctypes
import os
import shutil
from pathlib import Path

from session.asset_pack_format import load_pack_bytes
from session.paths import manmabot_root

DATA_PACK_NAME = "data.pack"
ANALYSIS_PACK_NAME = "analysis_text.pack"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def data_root() -> Path:
    """``Engine/data`` — a real folder in dev, a RAM mount in customer builds."""
    return manmabot_root() / "data"


def _is_reparse_point(path: Path) -> bool:
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
        # Junction already points somewhere — treat as "present" if non-empty.
        try:
            return any(path.iterdir())
        except OSError:
            return False
    try:
        return any(p.is_file() for p in path.rglob("*"))
    except OSError:
        return False


def _remove_junction_or_empty(path: Path) -> None:
    if not path.exists() and not _is_reparse_point(path):
        # broken junction may still "exist" via lexists
        if path.is_symlink() or os.path.lexists(path):
            try:
                os.rmdir(path)
            except OSError:
                path.unlink(missing_ok=True)  # type: ignore[arg-type]
        return
    if _is_reparse_point(path) or path.is_symlink():
        # rmdir removes the junction/symlink, not the target contents.
        os.rmdir(path)
        return
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        return
    raise RuntimeError(
        f"Refusing to replace non-empty real directory: {path}"
    )


_ANALYSIS_CLEANUP: list[Path] = []
_ANALYSIS_ROOT: Path | None = None
_CLEANUP_ARMED = False


def _drop_exported_data_cache(data_dir: Path) -> None:
    """Remove a previous junction and the on-disk PNG cache."""
    if _is_reparse_point(data_dir) or data_dir.is_symlink():
        os.rmdir(data_dir)
    cache = manmabot_root().parent / "UserData" / ".asset_cache"
    data_cache = cache / "data"
    if data_cache.exists() and not _is_reparse_point(data_cache):
        shutil.rmtree(data_cache, ignore_errors=True)
    staging = cache / "analysis_text"
    if staging.exists() and not _is_reparse_point(staging):
        shutil.rmtree(staging, ignore_errors=True)


def _cleanup_analysis_text() -> None:
    root = _ANALYSIS_ROOT
    for path in list(_ANALYSIS_CLEANUP):
        try:
            path.unlink()
        except OSError:
            continue
        parent = path.parent
        while root is not None and parent != root and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _arm_analysis_cleanup(paths: list[Path], root: Path) -> None:
    global _ANALYSIS_ROOT, _CLEANUP_ARMED
    _ANALYSIS_ROOT = root
    _ANALYSIS_CLEANUP[:] = paths
    if not _CLEANUP_ARMED:
        atexit.register(_cleanup_analysis_text)
        _CLEANUP_ARMED = True


def ensure_data_pack(*, force: bool = False) -> dict:
    """Mount ``Engine/data.pack`` in RAM. Does not create ``Engine/data``."""
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

    files = load_pack_bytes(pack_path)
    info = mount_bytes(data_dir, files)
    info["action"] = "memory"
    return info


def ensure_analysis_text_pack(*, force: bool = False) -> dict:
    """Write analysis text for C DLL readers; delete those files on exit."""
    engine = manmabot_root()
    pack_path = engine / ANALYSIS_PACK_NAME
    analysis_dir = engine / "analysis"
    if not pack_path.is_file():
        return {"action": "skipped", "reason": "no_pack"}

    files = load_pack_bytes(pack_path)
    written: list[Path] = []
    for rel, raw in files.items():
        dst = analysis_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        written.append(dst)
    _arm_analysis_cleanup(written, analysis_dir)
    return {
        "action": "temp_overlay",
        "files": len(written),
        "overlay": str(analysis_dir),
        "removed_on_exit": True,
    }


def ensure_packed_assets(*, force: bool = False) -> dict:
    """Idempotent startup hook: materialize packed assets if present."""
    return {
        "data": ensure_data_pack(force=force),
        "analysis_text": ensure_analysis_text_pack(force=force),
    }
