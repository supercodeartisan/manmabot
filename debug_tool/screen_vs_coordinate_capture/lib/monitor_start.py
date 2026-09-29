"""Optional: start realtime_monitor_full.exe if it sits next to this tool."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from paths import TOOL_DIR

MONITOR_EXE = "realtime_monitor_full.exe"
LogFn = Callable[[str], None]


def find_monitor_exe() -> Optional[Path]:
    here = TOOL_DIR
    candidates = [
        here / MONITOR_EXE,
        here / "analysis" / MONITOR_EXE,
        here.parent / MONITOR_EXE,
        here.parent / "analysis" / MONITOR_EXE,
        here.parent.parent / "engine" / "analysis" / MONITOR_EXE,
        here.parent.parent / "analysis" / MONITOR_EXE,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def is_monitor_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {MONITOR_EXE}", "/NH"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return MONITOR_EXE.lower() in out.lower()
    except Exception:
        return False


def try_start_monitor(*, log: Optional[LogFn] = None) -> tuple[bool, str]:
    """Start the monitor exe if found beside this folder. Pipe connect is separate."""
    _log = log or (lambda _m: None)
    if is_monitor_running():
        return True, "Monitor process already running"
    exe = find_monitor_exe()
    if exe is None:
        return False, (
            f"{MONITOR_EXE} not next to this folder — start it yourself "
            "(--pipe --interval 200), or copy the exe into this folder"
        )
    try:
        import ctypes

        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe),
            "--pipe --interval 200",
            str(exe.parent),
            1,
        )
        if int(rc) <= 32:
            subprocess.Popen(
                [str(exe), "--pipe", "--interval", "200"],
                cwd=str(exe.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _log(f"Started {exe.name} (no UAC)")
            time.sleep(0.8)
            return True, f"Started {exe.name}"
        _log(f"Started {exe.name} (admin)")
        time.sleep(0.8)
        return True, f"Started {exe.name} (admin)"
    except Exception as exc:
        return False, f"Could not start monitor: {exc}"
