"""Per-instance analysis TEMP tree: materialize, ACL, stale wipe (F-12)."""

from __future__ import annotations

import atexit
import ctypes
import os
import shutil
from pathlib import Path

from session.analysis_overlay import set_analysis_overlay

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_PREFIX = "manmabot_an_"
_PID_NAME = "owner.pid"
_LOCK_NAME = "owner.lock"

_ACTIVE_ROOT: Path | None = None
_LOCK_FH = None
_CLEANUP_ARMED = False


def _temp_base() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or os.getcwd())


def _is_reparse(path: Path) -> bool:
    if os.name != "nt":
        return path.is_symlink()
    if not path.exists() and not os.path.lexists(path):
        return False
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == -1:
        return path.is_symlink()
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as e:
        raise RuntimeError(f"path escapes analysis TEMP root: {path}") from e


def _mkdir_one(path: Path) -> None:
    if path.exists():
        if _is_reparse(path):
            raise RuntimeError(f"reparse point blocked: {path}")
        if not path.is_dir():
            raise RuntimeError(f"not a directory: {path}")
        return
    path.mkdir(parents=False, exist_ok=False)
    if _is_reparse(path):
        raise RuntimeError(f"reparse created unexpectedly: {path}")


def _mkdir_tree(root: Path, rel: str) -> Path:
    """Create ``root/rel`` one component at a time; refuse reparse."""
    cur = root
    if rel in ("", "."):
        return cur
    for part in Path(rel).parts:
        if part in (".", ".."):
            raise RuntimeError(f"illegal path component {part!r}")
        cur = cur / part
        _assert_inside(root, cur)
        _mkdir_one(cur)
    return cur


def _apply_user_acl(path: Path) -> None:
    """Best-effort: strip inheritance, grant current user full (Windows)."""
    if os.name != "nt":
        return
    try:
        import subprocess

        user = os.environ.get("USERNAME") or os.getlogin()
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{user}:(OI)(CI)F",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    # Windows: OpenProcess SYNCHRONIZE
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def wipe_stale_analysis_temps(*, protect: Path | None = None) -> int:
    """Remove ``manmabot_an_*`` dirs whose owner pid is dead. Returns count."""
    base = _temp_base()
    removed = 0
    if not base.is_dir():
        return 0
    protect_res = protect.resolve() if protect is not None else None
    for child in base.iterdir():
        if not child.name.startswith(_PREFIX):
            continue
        if not child.is_dir():
            continue
        if protect_res is not None and child.resolve() == protect_res:
            continue
        pid_file = child / _PID_NAME
        alive = False
        if pid_file.is_file():
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
                alive = _pid_alive(pid)
            except (OSError, ValueError):
                alive = False
        if alive:
            continue
        try:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed


def create_analysis_temp() -> Path:
    """Create ``%TEMP%/manmabot_an_<32 hex>/`` with pid + exclusive lock."""
    global _ACTIVE_ROOT, _LOCK_FH
    if _ACTIVE_ROOT is not None:
        return _ACTIVE_ROOT

    wipe_stale_analysis_temps()
    token = os.urandom(16).hex()
    root = _temp_base() / f"{_PREFIX}{token}"
    root.mkdir(parents=False, exist_ok=False)
    if _is_reparse(root):
        raise RuntimeError("analysis TEMP root is a reparse point")
    _apply_user_acl(root)
    (root / _PID_NAME).write_text(str(os.getpid()), encoding="utf-8")
    lock_path = root / _LOCK_NAME
    # Exclusive create — second open in another process would fail if we held it;
    # we keep the handle for the process lifetime.
    if os.name == "nt":
        _LOCK_FH = open(lock_path, "x", encoding="utf-8")
        _LOCK_FH.write(str(os.getpid()))
        _LOCK_FH.flush()
    else:
        _LOCK_FH = open(lock_path, "x", encoding="utf-8")
        _LOCK_FH.write(str(os.getpid()))
        _LOCK_FH.flush()

    _ACTIVE_ROOT = root
    set_analysis_overlay(root)
    _arm_cleanup()
    return root


def materialize_files(root: Path, files: dict[str, bytes]) -> list[Path]:
    """Write pack entries under ``root``; paths are posix relative."""
    written: list[Path] = []
    for rel, raw in files.items():
        rel_posix = rel.replace("\\", "/")
        parent = str(Path(rel_posix).parent).replace("\\", "/")
        if parent in (".", ""):
            dest_dir = root
        else:
            dest_dir = _mkdir_tree(root, parent)
        dest = dest_dir / Path(rel_posix).name
        _assert_inside(root, dest)
        if _is_reparse(dest) or (dest.exists() and _is_reparse(dest)):
            raise RuntimeError(f"refusing reparse dest: {dest}")
        # Write via temp name then replace to avoid partial reads.
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(raw)
        if _is_reparse(tmp):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"reparse after write: {tmp}")
        os.replace(tmp, dest)
        if _is_reparse(dest):
            raise RuntimeError(f"reparse after replace: {dest}")
        _assert_inside(root, dest.resolve())
        written.append(dest)
    return written


def active_analysis_temp() -> Path | None:
    return _ACTIVE_ROOT


def cleanup_analysis_temp() -> None:
    """Remove this process TEMP tree; clear overlay."""
    global _ACTIVE_ROOT, _LOCK_FH
    root = _ACTIVE_ROOT
    set_analysis_overlay(None)
    if _LOCK_FH is not None:
        try:
            _LOCK_FH.close()
        except OSError:
            pass
        _LOCK_FH = None
    _ACTIVE_ROOT = None
    if root is not None and root.exists():
        shutil.rmtree(root, ignore_errors=True)


def _arm_cleanup() -> None:
    global _CLEANUP_ARMED
    if _CLEANUP_ARMED:
        return
    atexit.register(cleanup_analysis_temp)
    _CLEANUP_ARMED = True
