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
        ret = int(
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, _relaunch_params(), cwd, 1
            )
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


def prepare_runtime() -> str:
    """Elevate once, then start WinNotify if this process is admin.

    The medium-integrity process exits after a successful relaunch so only
    the elevated copy keeps running.
    """
    status = ensure_elevated_or_continue()
    if status == "relaunched":
        raise SystemExit(0)
    if is_admin():
        import threading

        def _start_driver() -> None:
            try:
                from manmabot_v1.monitor_launch import try_start_driver

                try_start_driver()
            except Exception:
                pass

        threading.Thread(
            target=_start_driver, name="signeddrv-start", daemon=True
        ).start()
    return status
