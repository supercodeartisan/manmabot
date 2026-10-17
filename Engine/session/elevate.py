"""Self-elevate Manmabot so signeddrv.sys can start without a second UAC.

Purple / LC.exe already run elevated. Matching integrity at process start
lets ``load_signeddrv.ps1`` call ``sc.exe`` in-process. Later Start clicks
do not prompt again.
"""
from __future__ import annotations

import ctypes
import os
import sys

ELEVATED_FLAG = "--elevated-relaunch"
NO_ELEVATE_FLAG = "--no-elevate"


def is_admin() -> bool:
    """True when this process has a high-integrity (elevated) token."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _quote(arg: str) -> str:
    if not arg:
        return '""'
    if any(c in arg for c in ' \t"'):
        return '"%s"' % arg.replace('"', '\\"')
    return arg


def _relaunch_params() -> str:
    args: list[str] = []
    if getattr(sys, "frozen", False):
        for a in sys.argv[1:]:
            if a not in (ELEVATED_FLAG, NO_ELEVATE_FLAG):
                args.append(a)
    else:
        args.append(os.path.abspath(sys.argv[0]))
        for a in sys.argv[1:]:
            if a not in (ELEVATED_FLAG, NO_ELEVATE_FLAG):
                args.append(a)
    if ELEVATED_FLAG not in args:
        args.append(ELEVATED_FLAG)
    return " ".join(_quote(a) for a in args)


def relaunch_as_admin() -> bool:
    """Spawn an elevated copy via ShellExecute ``runas``.

    Returns True if Windows accepted the launch (UAC may still appear).
    """
    if is_admin() or NO_ELEVATE_FLAG in sys.argv or ELEVATED_FLAG in sys.argv:
        return False
    try:
        cwd = os.path.dirname(
            os.path.abspath(
                sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
            )
        )
        from win32_prototypes import bind_shell32

        bind_shell32(ctypes.windll.shell32)
        ret = int(
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, _relaunch_params(), cwd, 1
            )
            or 0
        )
        return ret > 32
    except Exception:
        return False


def ensure_elevated_or_continue() -> str:
    """Startup helper.

    Returns:
      elevated   — already admin
      relaunched — UAC accepted; caller must exit so the new process runs
      declined   — UAC cancelled / failed; caller may continue degraded
      skipped    — ``--no-elevate`` or a previous relaunch did not elevate
    """
    if is_admin():
        return "elevated"
    if NO_ELEVATE_FLAG in sys.argv or ELEVATED_FLAG in sys.argv:
        return "skipped"
    if relaunch_as_admin():
        return "relaunched"
    return "declined"


def _load_startup_warm_modules() -> None:
    """Import the admin warm path on the caller thread.

    The worker below still starts WinNotify and attaches the memory reader.
    Nuitka initializes each compiled module once. Doing that import from the
    worker while the main thread is still importing the UI crashes in
    python314.dll, so those modules are loaded here first. Later imports in
    the worker are cache hits and do not initialize again.
    """
    import importlib

    import session.monitor_launch  # noqa: F401
    import session.player_monitor as player_monitor

    try:
        player_monitor.reader_module()
    except Exception:
        pass
    for name in (
        "session.probes",
        "tool.utils",
        "app._01_perception.sensors",
        "app._01_perception.memory_client",
        "app._01_perception.print_state_reader",
        "app._01_perception.inventory_listen_reader",
        "app._01_perception.hotbar_listen_reader",
        "app._01_perception.shop_listen_reader",
        "app._01_perception.buff_listen_reader",
        "app._01_perception.uidialog_listen_reader",
        "app.bot_log",
    ):
        try:
            importlib.import_module(name)
        except Exception:
            pass


def prepare_runtime() -> str:
    """Elevate once, then start WinNotify and attach the memory reader.

    The medium-integrity process exits after a successful relaunch so only
    the elevated copy keeps running.
    """
    status = ensure_elevated_or_continue()
    if status == "relaunched":
        raise SystemExit(0)
    if is_admin():
        import threading

        _load_startup_warm_modules()

        def _start_driver() -> None:
            try:
                from session.monitor_launch import warm_memory_at_startup

                warm_memory_at_startup(wait_snapshot=False)
            except Exception:
                pass

        threading.Thread(
            target=_start_driver, name="signeddrv-start", daemon=True
        ).start()
    return status
