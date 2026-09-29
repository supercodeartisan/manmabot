"""Paths and engine resolution for the product folder.

Layout: launcher folder owns ``engine\\`` (bot runtime) and creates
``userdata\\`` next to the exe or ``run.py``. Operator settings live only
under ``userdata/``. The engine tree is read-only from Version 1.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def app_root() -> Path:
    """Directory that owns the product (exe folder, or this package's parent)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def is_portable() -> bool:
    """True for the shipped portable folder (marker file or env)."""
    flag = os.environ.get("MANMABOT_PORTABLE", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return (app_root() / ".portable").is_file()


VERSION1_ROOT = app_root()
USERDATA = VERSION1_ROOT / "userdata"
PROFILE_PATH = USERDATA / "profile.json"
ACCOUNTS_PATH = USERDATA / "accounts.json"
PROFILES_DIR = USERDATA / "profiles"
LOG_DIR = USERDATA / "logs"
MAPS_OVERLAY = USERDATA / "maps"

_MAP_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAP_ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def ensure_userdata() -> None:
    USERDATA.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_OVERLAY.mkdir(parents=True, exist_ok=True)


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


def overlay_patrol_path(map_id: str) -> Path:
    return map_overlay_dir(map_id) / "patrol.yaml"


def assert_userdata_write(path: Path | str) -> Path:
    """Raise if ``path`` is not under Version 1 userdata (never the engine)."""
    p = Path(path).expanduser().resolve()
    if not _is_inside(p, USERDATA):
        raise RuntimeError(
            f"Version 1 settings must be written under {USERDATA.resolve()}, not {p}"
        )
    if _is_inside(p, manmabot_root()):
        raise RuntimeError(f"Refusing to write into the Manmabot engine: {p}")
    return p


def _looks_like_engine(path: Path) -> bool:
    return (path / "app").is_dir() and (path / "config").is_dir()


def manmabot_root() -> Path:
    """Resolve the Manmabot engine tree next to this product (``engine\\``).

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

    candidate = app_root() / "engine"
    if not _looks_like_engine(candidate):
        raise RuntimeError(
            f"Engine not found at {candidate}. Keep the engine folder "
            "next to ManmabotV1.bat / run.py."
        )
    return candidate
