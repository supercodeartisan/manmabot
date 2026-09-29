"""Close the Lineage client so the next scheduled account can log in.

This is the same process-tree shutdown autologin already uses between
relaunches. It runs off the UI thread and does not pause the scheduler.
"""
from __future__ import annotations

import ctypes
import subprocess
import time

CREATE_NO_WINDOW = 0x08000000


def close_game_client(timeout_s: float = 8.0) -> None:
    pid = _game_pid()
    command = (
        ["taskkill", "/PID", str(pid), "/T", "/F"]
        if pid
        else ["taskkill", "/IM", "LC.exe", "/T", "/F"]
    )
    subprocess.run(command, creationflags=CREATE_NO_WINDOW, capture_output=True)
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        if not _game_pid():
            return
        time.sleep(0.3)


def _game_pid() -> int:
    try:
        from manmabot_v1.probes import probe_game

        hwnd = int(getattr(probe_game(), "hwnd", 0) or 0)
    except Exception:
        return 0
    if not hwnd:
        return 0
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value or 0)
