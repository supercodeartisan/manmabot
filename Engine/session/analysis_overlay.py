"""Analysis text overlay root (TEMP materialize or plain Engine/analysis).

Perception readers resolve offset/registry *text* through here.
DLLs stay under ``Engine/analysis/dll`` (plain ship).
"""

from __future__ import annotations

from pathlib import Path

from session.paths import manmabot_root

_OVERLAY_ROOT: Path | None = None


def set_analysis_overlay(root: Path | None) -> None:
    """Set process-wide analysis text root (absolute TEMP dir), or clear."""
    global _OVERLAY_ROOT
    _OVERLAY_ROOT = root.resolve() if root is not None else None


def analysis_overlay_root() -> Path | None:
    return _OVERLAY_ROOT


def analysis_text_root() -> Path:
    """Directory that holds registry/*.json and related analysis text."""
    if _OVERLAY_ROOT is not None:
        return _OVERLAY_ROOT
    return manmabot_root() / "analysis"


def analysis_registry_file(*parts: str) -> Path:
    """Path under analysis text root (e.g. ``registry/offsets.json``)."""
    return analysis_text_root().joinpath(*parts)
