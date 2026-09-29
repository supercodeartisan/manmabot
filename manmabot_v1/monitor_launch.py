"""Attach the in-process player monitor and, if needed, load the signed driver."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from manmabot_v1.paths import manmabot_root
from manmabot_v1.probes import Lamp, MemoryProbe, probe_memory

LogFn = Callable[[str], None]

MONITOR_EXE_NAME = "realtime_monitor_full.exe"
DEFAULT_INTERVAL_MS = 200
DEFAULT_WAIT_S = 20.0


@dataclass
class MonitorEnsureResult:
    ok: bool
    detail: str
    started: bool = False
    probe: Optional[MemoryProbe] = None


def monitor_exe_path() -> Path:
    return manmabot_root() / "analysis" / MONITOR_EXE_NAME


def driver_script_path() -> Path:
    return manmabot_root() / "analysis" / "load_signeddrv.ps1"


def is_monitor_process_running() -> bool:
    """True if realtime_monitor_full.exe appears in the process list."""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {MONITOR_EXE_NAME}", "/NH"],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return MONITOR_EXE_NAME.lower() in out.lower()
    except Exception:
        return False


def _create_no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def start_monitor_process(*, elevate: bool = False) -> tuple[bool, str]:
    """Launch ``realtime_monitor_full.exe --pipe --interval 200``.

    ``--interval 200`` is the monitor poll cadence (ms); useful vitals/position
    updates from the game typically arrive closer to ~1 s apart in practice.

    Returns (ok, message). Does not wait for the pipe.
    """
    exe = monitor_exe_path()
    if not exe.is_file():
        return False, f"Monitor not found: {exe}"

    args = f'--pipe --interval {DEFAULT_INTERVAL_MS}'
    cwd = str(exe.parent)

    if elevate:
        try:
            import ctypes

            # SW_SHOWNORMAL = 1 — console can show errors; user sees UAC prompt.
            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(exe),
                args,
                cwd,
                1,
            )
            # ShellExecute returns >32 on success.
            if int(rc) <= 32:
                return False, f"Elevated start failed (ShellExecute={rc})"
            return True, "Started monitor (admin)"
        except Exception as exc:
            return False, f"Elevated start failed: {exc}"

    try:
        subprocess.Popen(
            [str(exe), "--pipe", "--interval", str(DEFAULT_INTERVAL_MS)],
            cwd=cwd,
            creationflags=_create_no_window(),
        )
        return True, "Started monitor"
    except Exception as exc:
        return False, f"Start failed: {exc}"


def _start_driver_inplace(script: Path, log: LogFn) -> tuple[bool, str]:
    """Start WinNotify with this process's token (no second UAC)."""
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Action",
                "start",
            ],
            cwd=str(script.parent),
            capture_output=True,
            text=True,
            timeout=45,
            creationflags=_create_no_window(),
        )
    except Exception as exc:
        return False, f"Driver start failed: {exc}"
    text = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if completed.returncode == 0:
        message = text or "WinNotify started"
        log(message)
        return True, message
    return False, text or f"Driver start failed (exit {completed.returncode})"


def try_start_driver(*, log: Optional[LogFn] = None) -> tuple[bool, str]:
    """Start signeddrv / WinNotify. No UAC if this process is already admin."""
    script = driver_script_path()
    if not script.is_file():
        return False, f"Driver script not found: {script}"
    _log = log or (lambda _m: None)
    from manmabot_v1.elevate import is_admin

    if is_admin():
        return _start_driver_inplace(script, _log)
    try:
        import ctypes

        cmd = f'-ExecutionPolicy Bypass -File "{script}" -Action start'
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "powershell.exe",
            cmd,
            str(script.parent),
            1,
        )
        if int(rc) <= 32:
            return False, f"Driver start failed (ShellExecute={rc})"
        _log("Requested signed driver start (admin)")
        time.sleep(1.5)
        return True, "Driver start requested"
    except Exception as exc:
        return False, f"Driver start failed: {exc}"


def wait_for_memory(
    *,
    timeout_s: float = DEFAULT_WAIT_S,
    poll_s: float = 0.4,
    log: Optional[LogFn] = None,
) -> MemoryProbe:
    """Poll probe_memory until green/yellow or timeout (last probe returned)."""
    _log = log or (lambda _m: None)
    deadline = time.time() + max(1.0, timeout_s)
    last = probe_memory()
    while time.time() < deadline:
        last = probe_memory()
        if last.lamp in (Lamp.GREEN, Lamp.YELLOW):
            return last
        time.sleep(poll_s)
    _log(f"Memory wait timed out: {last.detail}")
    return last


def ensure_monitor_connected(
    *,
    elevate: bool = True,
    start_driver: bool = False,
    timeout_s: float = DEFAULT_WAIT_S,
    log: Optional[LogFn] = None,
) -> MonitorEnsureResult:
    """Attach the in-process player monitor. Does not open a console.

    Order:
    1. Probe — already reading LC.exe?
    2. Optionally load the signed driver
    3. Probe again until player data arrives
    """
    _log = log or (lambda _m: None)

    probe = probe_memory()
    if probe.lamp in (Lamp.GREEN, Lamp.YELLOW):
        return MonitorEnsureResult(True, probe.detail, started=False, probe=probe)

    if start_driver:
        ok_drv, msg_drv = try_start_driver(log=_log)
        _log(msg_drv)
        if not ok_drv:
            pass

    _log("Reading player memory in this process (offsets.json)")
    probe = wait_for_memory(timeout_s=timeout_s, log=_log)
    ok = probe.lamp in (Lamp.GREEN, Lamp.YELLOW)
    return MonitorEnsureResult(ok, probe.detail, started=False, probe=probe)


def stop_monitor_process(*, log: Optional[LogFn] = None) -> tuple[bool, str]:
    """Close ``realtime_monitor_full.exe`` so the next Start can launch cleanly."""
    _log = log or (lambda _m: None)
    if not is_monitor_process_running():
        return True, "Monitor was not running"

    flags = _create_no_window()
    try:
        subprocess.run(
            ["taskkill", "/IM", MONITOR_EXE_NAME, "/T"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=flags,
        )
    except Exception as exc:
        _log(f"Monitor close: {exc}")
    time.sleep(0.4)
    if not is_monitor_process_running():
        return True, "Monitor closed"

    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", MONITOR_EXE_NAME, "/T"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
        )
    except Exception as exc:
        return False, str(exc)

    time.sleep(0.3)
    if is_monitor_process_running():
        err = (result.stderr or result.stdout or "Monitor still running").strip()
        return False, err
    return True, "Monitor closed"
