"""Windows UAC elevation helpers for the launcher and bot.

Purple / Lineage Classic run elevated (requireAdministrator). A medium-
integrity launcher cannot reliably minimize Purple or keep the game on top
(UIPI). Matching integrity via one UAC prompt removes that class of failures.
"""
from __future__ import annotations

import ctypes
import os
import sys

ELEVATED_FLAG = "--elevated-relaunch"
NO_ELEVATE_FLAG = "--no-elevate"


def is_admin() -> bool:
    """True when this process has a high-integrity (elevated) token."""
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


def build_relaunch_params(extra_args=None) -> str:
    """Command-line parameters for an elevated relaunch of this app."""
    args = []
    if getattr(sys, "frozen", False):
        # Frozen exe: argv[0] is the exe itself; only forward user args.
        for a in sys.argv[1:]:
            if a in (ELEVATED_FLAG, NO_ELEVATE_FLAG):
                continue
            args.append(a)
    else:
        script = os.path.abspath(sys.argv[0])
        args.append(script)
        for a in sys.argv[1:]:
            if a in (ELEVATED_FLAG, NO_ELEVATE_FLAG):
                continue
            args.append(a)
    if extra_args:
        for a in extra_args:
            if a and a not in args:
                args.append(a)
    if ELEVATED_FLAG not in args:
        args.append(ELEVATED_FLAG)
    return " ".join(_quote(a) for a in args)


def relaunch_as_admin(extra_args=None, show_cmd: int = 1) -> bool:
    """Spawn an elevated copy of this process via ShellExecute 'runas'.

    Returns True if Windows accepted the launch (UAC may still be shown;
    ret > 32 means the elevated process was started or the prompt was
    displayed successfully). Returns False on cancel/error or if elevation
    was already attempted / disabled.
    """
    if is_admin():
        return True
    if NO_ELEVATE_FLAG in sys.argv:
        return False
    if ELEVATED_FLAG in sys.argv:
        # Previous relaunch did not actually gain elevation (UAC declined
        # mid-flight, or policy blocked it) — do not loop.
        return False
    try:
        params = build_relaunch_params(extra_args)
        cwd = os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, "frozen", False)
            else sys.argv[0]))
        ret = int(ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, cwd, show_cmd))
        return ret > 32
    except Exception:
        return False


def ensure_elevated_or_continue() -> str:
    """Startup helper for GUI / CLI entry points.

    Returns one of:
      'elevated'  — already admin
      'relaunched'— UAC accepted; caller should exit so the new process runs
      'declined'  — UAC cancelled / failed; caller may continue degraded
      'skipped'   — --no-elevate or already tried once
    """
    if is_admin():
        return "elevated"
    if NO_ELEVATE_FLAG in sys.argv:
        return "skipped"
    if ELEVATED_FLAG in sys.argv:
        return "declined"
    if relaunch_as_admin():
        return "relaunched"
    return "declined"
