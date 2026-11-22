"""analysis_dll_path prefers TEMP overlay then plain Engine/analysis/dll."""
from __future__ import annotations

import tempfile
from pathlib import Path

from session.analysis_overlay import (
    analysis_dll_path,
    analysis_dll_prefer_newer,
    set_analysis_overlay,
)


def test_overlay_then_plain(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain_analysis" / "dll"
    plain.mkdir(parents=True)
    (plain / "only_plain.dll").write_bytes(b"P")
    overlay = tmp_path / "overlay"
    (overlay / "dll").mkdir(parents=True)
    (overlay / "dll" / "print_state.dll").write_bytes(b"O")

    monkeypatch.setattr(
        "session.analysis_overlay.manmabot_root",
        lambda: tmp_path / "plain_engine",
    )
    # Redirect plain search: manmabot_root()/analysis/dll
    eng = tmp_path / "plain_engine"
    (eng / "analysis" / "dll").mkdir(parents=True)
    (eng / "analysis" / "dll" / "only_plain.dll").write_bytes(b"P")

    set_analysis_overlay(overlay)
    try:
        assert analysis_dll_path("print_state.dll").read_bytes() == b"O"
        assert analysis_dll_path("only_plain.dll").read_bytes() == b"P"
        newest = analysis_dll_prefer_newer("print_state.dll", "missing.dll")
        assert newest.name == "print_state.dll"
    finally:
        set_analysis_overlay(None)
