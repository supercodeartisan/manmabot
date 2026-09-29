"""Manmabot Version 1 — operator console entry."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE = (ROOT / "engine").resolve()
os.environ["MANMABOT_ROOT"] = str(ENGINE)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


def _reexec_with_bundled_python() -> None:
    """Prefer the project interpreter so engine/UI packages resolve."""
    current = Path(sys.executable).resolve()
    console = ROOT / "python" / "python.exe"
    windowed = ROOT / "python" / "pythonw.exe"
    if not console.is_file() and not windowed.is_file():
        return
    # Terminal launches stay on python.exe; GUI double-clicks can use pythonw.
    preferred = console if console.is_file() else windowed
    if current == preferred.resolve():
        return
    if current.name.lower() == "pythonw.exe" and windowed.is_file():
        preferred = windowed
        if current == preferred.resolve():
            return
    os.execv(str(preferred), [str(preferred), str(ROOT / "run.py"), *sys.argv[1:]])


def _show_crash(text: str) -> None:
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text[-2500:], "Manmabot v1", 0x10)
            return
    except Exception:
        pass
    print(text, file=sys.stderr)


def main() -> int:
    try:
        _reexec_with_bundled_python()
        from manmabot_v1.elevate import prepare_runtime

        prepare_runtime()
        from manmabot_v1.ui.fonts import load_bundled_fonts

        load_bundled_fonts()
        if "--shopping-practice" in sys.argv:
            from debug_tools.shopping_practice import run_shopping_practice

            return int(run_shopping_practice())
        if "--hotbar-inspect" in sys.argv:
            from debug_tools.hotbar_inspector import run_hotbar_inspector

            return int(run_hotbar_inspector())
        if "--debug" in sys.argv:
            from manmabot_v1.ui.debug_ui import run_debug_player

            return int(run_debug_player())
        if "--dungeon-patrol" in sys.argv:
            from debug_tools.dungeon_patrol_editor import run_dungeon_patrol_editor

            return int(run_dungeon_patrol_editor())
        if "--operator" in sys.argv:
            from manmabot_v1.ui.app import run_app

            return int(run_app())
        from manmabot_v1.ui.schedule_ui import run_schedule_app

        return int(run_schedule_app())
    except Exception:
        _show_crash(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
