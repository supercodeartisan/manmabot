"""Manmabot Version 1 — thin keep-script entry (path + bundled Python).

Dispatch / UI routing lives in ``session.run_entry`` (Nuitka ``.pyd`` in release).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE = (ROOT / "Engine").resolve()
UI_ROOT = (ROOT / "UI").resolve()
TOOLS = (ROOT / "Tools").resolve()
os.environ["MANMABOT_ROOT"] = str(ENGINE)

_TOOL_FLAGS = (
    "--shopping-practice",
    "--hotbar-inspect",
    "--dungeon-patrol",
    "--dungeon-combat",
    "--memory-bench",
    "--follow-player",
    "--action-view",
    "--world-nav",
)
 

def _setup_path(*, include_tools: bool) -> None:
    paths = [ROOT, ENGINE, UI_ROOT]
    if include_tools:
        paths.insert(0, TOOLS)
    for path in paths:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _reexec_with_bundled_python() -> None:
    current = Path(sys.executable).resolve()
    console = ROOT / "python" / "python.exe"
    windowed = ROOT / "python" / "pythonw.exe"
    if not console.is_file() and not windowed.is_file():
        return
    preferred = console if console.is_file() else windowed
    if current == preferred.resolve():
        return
    if current.name.lower() == "pythonw.exe" and windowed.is_file():
        preferred = windowed
        if current == preferred.resolve():
            return
    os.execv(str(preferred), [str(preferred), str(ROOT / "run.py"), *sys.argv[1:]])


def main() -> int:
    _reexec_with_bundled_python()
    want_tools = any(flag in sys.argv for flag in _TOOL_FLAGS)
    _setup_path(include_tools=want_tools)
    # The loading window starts in run_entry after the UAC prompt is answered.
    from session.run_entry import main as run_main

    return int(run_main())


if __name__ == "__main__":
    raise SystemExit(main())
