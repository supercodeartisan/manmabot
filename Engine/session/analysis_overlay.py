"""Analysis overlay root (TEMP materialize or plain Engine/analysis).

Perception readers resolve offset/registry *text* and analysis *DLLs* through
here. Pack-only builds materialize both under ``%TEMP%/manmabot_an_*`` from
``analysis_text.pack``. Dev trees keep plain ``Engine/analysis`` (including dll/).
"""

from __future__ import annotations

from pathlib import Path

from session.paths import manmabot_root

_OVERLAY_ROOT: Path | None = None


def set_analysis_overlay(root: Path | None) -> None:
    """Set process-wide analysis root (absolute TEMP dir), or clear."""
    global _OVERLAY_ROOT
    _OVERLAY_ROOT = root.resolve() if root is not None else None


def analysis_overlay_root() -> Path | None:
    return _OVERLAY_ROOT


def analysis_text_root() -> Path:
    """Directory that holds registry/* and related analysis text (and dll/ when packed)."""
    if _OVERLAY_ROOT is not None:
        return _OVERLAY_ROOT
    return manmabot_root() / "analysis"


def analysis_registry_file(*parts: str) -> Path:
    """Path under analysis text root (e.g. ``registry/offsets.json``)."""
    return analysis_text_root().joinpath(*parts)


def _dll_search_roots() -> list[Path]:
    """Overlay dll/ first (pack-only), then plain Engine/analysis/dll (dev / fallback)."""
    roots: list[Path] = []
    if _OVERLAY_ROOT is not None:
        roots.append(_OVERLAY_ROOT / "dll")
    plain = manmabot_root() / "analysis" / "dll"
    if not roots or plain.resolve() != roots[0].resolve():
        roots.append(plain)
    return roots


def analysis_dll_dir() -> Path:
    """Preferred dll directory (overlay when set, else plain analysis/dll)."""
    return _dll_search_roots()[0]


def analysis_dll_path(*names: str) -> Path:
    """First existing ``dll/<name>`` across overlay then plain; else last name under preferred dir."""
    if not names:
        raise ValueError("analysis_dll_path requires at least one file name")
    for name in names:
        for root in _dll_search_roots():
            path = root / name
            if path.is_file():
                return path
    return analysis_dll_dir() / names[-1]


def analysis_dll_prefer_newer(*names: str) -> Path:
    """Among existing candidates (one hit per name), pick newest mtime; else ``analysis_dll_path``."""
    found: list[Path] = []
    for name in names:
        for root in _dll_search_roots():
            path = root / name
            if path.is_file():
                found.append(path)
                break
    if not found:
        return analysis_dll_path(*names)
    return max(found, key=lambda path: path.stat().st_mtime)
