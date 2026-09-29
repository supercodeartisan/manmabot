"""Launch inventory_listen.exe --pipe for bag scans (optional companion process)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from manmabot_v1.paths import manmabot_root

LogFn = Callable[[str], None]

INVENTORY_EXE_NAME = "inventory_listen.exe"
PIPE_NAME = r"\\.\pipe\inv_listen"


def inventory_exe_path() -> Path:
    return manmabot_root() / "analysis" / "inventories" / INVENTORY_EXE_NAME


def is_inventory_process_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {INVENTORY_EXE_NAME}", "/NH"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return INVENTORY_EXE_NAME.lower() in out.lower()
    except Exception:
        return False


def start_inventory_process(*, elevate: bool = True) -> tuple[bool, str]:
    exe = inventory_exe_path()
    if not exe.is_file():
        return False, f"Inventory listen not found: {exe}"
    cwd = str(exe.parent)
    args = "--pipe"
    if elevate:
        try:
            import ctypes

            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(exe), args, cwd, 1,
            )
            if int(rc) <= 32:
                return False, f"Elevated start failed (ShellExecute={rc})"
            return True, "Started inventory_listen (admin)"
        except Exception as exc:
            return False, f"Elevated start failed: {exc}"
    try:
        subprocess.Popen(
            [str(exe), "--pipe"],
            cwd=cwd,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True, "Started inventory_listen"
    except Exception as exc:
        return False, f"Start failed: {exc}"


def ensure_inventory_listen(*, log: Optional[LogFn] = None) -> bool:
    """Start inventory_listen --pipe when the exe exists and is not already running.

    Returns True when a process is running (or was started). Soft-fails when the
    binary is missing so the bot can still use inv.json fallback.
    """
    def _log(msg: str) -> None:
        if log is not None:
            log(msg)

    if is_inventory_process_running():
        _log("inventory_listen already running")
        return True
    exe = inventory_exe_path()
    if not exe.is_file():
        _log(f"inventory_listen.exe missing at {exe} (optional until built)")
        return False
    ok, detail = start_inventory_process(elevate=True)
    _log(detail)
    return ok


__all__ = [
    "PIPE_NAME",
    "inventory_exe_path",
    "is_inventory_process_running",
    "start_inventory_process",
    "ensure_inventory_listen",
]
