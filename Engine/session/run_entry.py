"""Operator console dispatch (compiled to .pyd in customer builds).

``run.py`` stays a thin keep-script: path bootstrap + re-exec, then calls
:func:`main` here so release trees do not ship the routing source.
"""
from __future__ import annotations

import sys
import traceback


def _show_crash(text: str) -> None:
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text[-2500:], "ZF", 0x10)
            return
    except Exception:
        pass
    print(text, file=sys.stderr)


def _show_startup_splash() -> None:
    """Loading window for the operator console, after UAC has been answered."""
    try:
        from session.startup_splash import open_until_main_window

        open_until_main_window()
    except Exception:
        pass


def main() -> int:
    try:
        # Customer builds ship Engine/data.pack (+ analysis_text.pack). Materialize
        # before any map/offset readers run. Dev trees with plain Engine/data no-op.
        from session.paths import ensure_userdata
        from session.asset_pack import ensure_packed_assets

        ensure_userdata()
        ensure_packed_assets()
        from session.elevate import prepare_runtime

        prepare_runtime()
        if "--shopping-practice" in sys.argv:
            from shopping.shopping_practice import run_shopping_practice

            return int(run_shopping_practice())
        if "--hotbar-inspect" in sys.argv:
            from hotbar_tool.hotbar_inspector import run_hotbar_inspector

            return int(run_hotbar_inspector())
        if "--debug" in sys.argv:
            from ui_qt.debug.debug_player import run_debug_player

            return int(run_debug_player())
        if "--dungeon-patrol" in sys.argv:
            from dungeon.dungeon_patrol_editor import run_dungeon_patrol_editor

            return int(run_dungeon_patrol_editor())
        if "--dungeon-combat" in sys.argv:
            from dungeon.dungeon_combat_gui import run_dungeon_combat

            return int(run_dungeon_combat())
        if "--memory-bench" in sys.argv:
            from memory_bench.memory_bench_gui import run_memory_bench

            return int(run_memory_bench())
        if "--follow-player" in sys.argv:
            from follow_player.follow_gui import run_follow_player

            return int(run_follow_player())
        if "--action-view" in sys.argv:
            from action_view.action_view_gui import run_action_view

            return int(run_action_view())
        if "--ui" in sys.argv:
            # Legacy ttk console: run.py --ui tk
            try:
                flag_i = sys.argv.index("--ui")
                toolkit = str(sys.argv[flag_i + 1]).strip().lower()
            except (ValueError, IndexError):
                toolkit = "qt"
            if toolkit in ("tk", "ttk", "classic"):
                _show_startup_splash()
                from ui.schedule_ui import run_schedule_app

                return int(run_schedule_app())
        # Default / --operator: Qt schedule console.
        _show_startup_splash()
        from ui_qt.app import run_schedule_app

        return int(run_schedule_app())
    except Exception:
        try:
            from session.startup_splash import close_startup_splash

            close_startup_splash()
        except Exception:
            pass
        _show_crash(traceback.format_exc())
        return 1
