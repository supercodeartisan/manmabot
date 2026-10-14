"""Paths and engine resolution for the product folder.

Layout: product root owns ``Engine\\`` (bot runtime) and ``UserData\\``
(operator settings). Settings are written only under ``UserData/``.
The Engine tree is read-only from Version 1.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def app_root() -> Path:
    """Directory that owns the product (exe folder, or repo root)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Engine/session/paths.py → parents[2] = product root
    return Path(__file__).resolve().parents[2]


def is_portable() -> bool:
    """True for the shipped portable folder (marker file or env)."""
    flag = os.environ.get("MANMABOT_PORTABLE", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return (app_root() / ".portable").is_file()


VERSION1_ROOT = app_root()
USERDATA = VERSION1_ROOT / "UserData"
PROFILE_PATH = USERDATA / "profile.json"  # legacy; migrated → trial/
ACCOUNTS_PATH = USERDATA / "accounts.json"
PROFILES_DIR = USERDATA / "profiles"  # legacy named presets
LOG_DIR = USERDATA / "logs"
MAPS_OVERLAY = USERDATA / "maps"
# Ops hierarchy: timeline → schedules/{id}/(meta,settings,routine) + trial/
APP_PATH = USERDATA / "app.json"
TIMELINE_PATH = USERDATA / "timeline.json"
SCHEDULES_DIR = USERDATA / "schedules"
LEGACY_SCHEDULES_PATH = USERDATA / "schedules.json"
TRIAL_DIR = USERDATA / "trial"
TRIAL_SETTINGS_PATH = TRIAL_DIR / "settings.json"
TRIAL_ROUTINE_PATH = TRIAL_DIR / "routine.json"
TOOLS_USERDATA_DIR = USERDATA / "tools"
DRIVERS_DIR = VERSION1_ROOT / "Drivers"
SIGNED_DRIVER_DIR = DRIVERS_DIR / "SignedDriver"
INTERCEPTION_DIR = DRIVERS_DIR / "Interception"
TOOLS_DIR = VERSION1_ROOT / "Tools"
TOOLS_OUTPUT = TOOLS_DIR / "output"

_MAP_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAP_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def ensure_userdata() -> None:
    USERDATA.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_OVERLAY.mkdir(parents=True, exist_ok=True)
    SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS_USERDATA_DIR.mkdir(parents=True, exist_ok=True)


def schedule_dir(schedule_id: str) -> Path:
    sid = str(schedule_id or "").strip() or "_unknown"
    return SCHEDULES_DIR / sid


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def map_overlay_slug(map_id: str) -> str:
    raw = str(map_id or "").strip()
    if _MAP_ID_OK.fullmatch(raw):
        return raw
    cleaned = _MAP_ID_SAFE.sub("_", raw).strip("._")
    if _MAP_ID_OK.fullmatch(cleaned):
        return cleaned
    return "_unknown"


def map_overlay_dir(map_id: str) -> Path:
    return MAPS_OVERLAY / map_overlay_slug(map_id)


def overlay_farms_path(map_id: str) -> Path:
    return map_overlay_dir(map_id) / "farms.yaml"


def overlay_safe_path(map_id: str) -> Path:
    return map_overlay_dir(map_id) / "safe.yaml"


def overlay_patrol_path(map_id: str) -> Path:
    return map_overlay_dir(map_id) / "patrol.yaml"


def assert_userdata_write(path: Path | str) -> Path:
    """Raise if ``path`` is not under Version 1 UserData (never the Engine)."""
    p = Path(path).expanduser().resolve()
    if not _is_inside(p, USERDATA):
        raise RuntimeError(
            f"Version 1 settings must be written under {USERDATA.resolve()}, not {p}"
        )
    if _is_inside(p, manmabot_root()):
        raise RuntimeError(f"Refusing to write into the Manmabot engine: {p}")
    return p


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> Path:
    """Write text under UserData via a local temp file, then publish.

    SMB/network shares often deny creating ``.name.*.tmp`` beside the target
    (Errno 13). Building the file in the system temp directory avoids that.
    """
    target = assert_userdata_write(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="manmabot_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        try:
            os.replace(temp_name, target)
        except OSError:
            shutil.copyfile(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return target


def atomic_write_json(path: Path | str, payload: Any, *, indent: int = 2) -> Path:
    """JSON helper for :func:`atomic_write_text`."""
    body = json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"
    return atomic_write_text(path, body)


def _looks_like_engine(path: Path) -> bool:
    return (path / "app").is_dir() and (path / "config").is_dir()


def manmabot_root() -> Path:
    """Resolve the Manmabot engine tree (``Engine\\``).

    ``MANMABOT_ROOT`` may override. There is no fallback to a developer
    checkout such as ``D:\\manma\\Manmabot``.
    """
    env = os.environ.get("MANMABOT_ROOT", "").strip()
    if env:
        candidate = Path(env).expanduser()
        if not _looks_like_engine(candidate):
            raise RuntimeError(
                f"MANMABOT_ROOT is set but is not an engine tree: {candidate}"
            )
        return candidate

    for name in ("Engine", "engine"):
        candidate = app_root() / name
        if _looks_like_engine(candidate):
            return candidate
    raise RuntimeError(
        f"Engine not found under {app_root()}. Keep the Engine folder "
        "next to Bot_Manmabot.bat / run.py."
    )


def data_root() -> Path:
    """Engine data directory (Engine/data).

    Customer builds mount this path from data.pack in RAM
    (session.asset_pack.ensure_packed_assets). The directory is not
    created on disk. Dev trees keep the plain folder.
    """
    return manmabot_root() / "data"
