"""Python client for the in-process player monitor.

``open_monitor_from_config`` loads ``realtime_monitor.dll`` in this process.
``LineageMonitor`` remains for tools that still speak the named pipe.
"""
from __future__ import annotations

import ctypes
import json
import time
from ctypes import wintypes
from typing import Any, Optional

PIPE_NAME = r"\\.\pipe\realtime_monitor"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE = wintypes.HANDLE(-1).value
ERROR_PIPE_BUSY = 231
ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.WriteFile.restype = wintypes.BOOL
_k32.WriteFile.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.ReadFile.restype = wintypes.BOOL
_k32.ReadFile.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.WaitNamedPipeW.restype = wintypes.BOOL
_k32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]


class LineageMonitor:
    """Named-pipe client for LC.exe memory snapshots."""

    def __init__(
        self,
        pipe: str = PIPE_NAME,
        connect_retries: int = 150,
        connect_delay: float = 0.2,
    ) -> None:
        self._pipe = pipe
        self._retries = connect_retries
        self._delay = connect_delay
        self._h = INVALID_HANDLE

    @property
    def connected(self) -> bool:
        return self._h != INVALID_HANDLE

    def connect(self) -> None:
        """Open the named pipe (retries while the monitor exe starts)."""
        last_err = 0
        for _ in range(self._retries):
            h = _k32.CreateFileW(
                self._pipe,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            if h != INVALID_HANDLE:
                self._h = h
                return
            last_err = ctypes.get_last_error()
            # Another client (bot worker / status probe) may hold the only instance.
            if last_err == ERROR_PIPE_BUSY:
                _k32.WaitNamedPipeW(self._pipe, max(1, int(self._delay * 1000)))
            time.sleep(self._delay)
        hint = (
            "pipe not available - is realtime_monitor_full.exe --pipe running as admin?"
        )
        if last_err == ERROR_PIPE_BUSY:
            hint = (
                "memory pipe busy — stop the running bot worker (and wait a second) "
                "so Shopping Practice can connect; only one client can hold the pipe"
            )
        elif last_err == ERROR_ACCESS_DENIED:
            hint = (
                "memory pipe access denied (WinError 5) — the monitor runs as admin, "
                "so Shopping Practice must too. Use “Start Shopping Practice.bat” "
                "(UAC) or relaunch this window as Administrator"
            )
        elif last_err not in (0, ERROR_FILE_NOT_FOUND):
            hint = f"{hint} (WinError {last_err})"
        raise ConnectionError(hint)

    def try_connect(self) -> bool:
        """Connect once without long retries. Returns False on failure."""
        h = _k32.CreateFileW(
            self._pipe,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if h == INVALID_HANDLE:
            return False
        self._h = h
        return True

    def _rpc(self, req: str) -> dict[str, Any]:
        if self._h == INVALID_HANDLE:
            self.connect()
        payload = (req + "\n").encode("ascii")
        nw = wintypes.DWORD(0)
        if (
            not _k32.WriteFile(self._h, payload, len(payload), ctypes.byref(nw), None)
            or nw.value != len(payload)
        ):
            self.close()
            raise ConnectionError("write to monitor failed")
        out = b""
        buf = ctypes.create_string_buffer(8192)
        nr = wintypes.DWORD(0)
        while b"\n" not in out:
            if (
                not _k32.ReadFile(self._h, buf, len(buf) - 1, ctypes.byref(nr), None)
                or nr.value == 0
            ):
                self.close()
                raise ConnectionError("monitor closed the connection")
            out += buf.raw[:nr.value]
            if len(out) > 10_000_000:
                raise ConnectionError("response too large")
        line = out.split(b"\n", 1)[0]
        return json.loads(line)

    def snapshot(self, fresh: bool = False) -> dict[str, Any]:
        """Request a full dataset snapshot."""
        req = '{"cmd":"snapshot","fresh":true}' if fresh else '{"cmd":"snapshot"}'
        return self._rpc(req)

    def ping(self) -> dict[str, Any]:
        """Health check."""
        return self._rpc('{"cmd":"ping"}')

    def close(self) -> None:
        if self._h != INVALID_HANDLE:
            _k32.CloseHandle(self._h)
        self._h = INVALID_HANDLE


def open_monitor_from_config(
    config: Optional[dict[str, Any]] = None,
    *,
    quiet: bool = False,
    connect_retries: Optional[int] = None,
) -> Optional["InProcessMonitor"]:
    """Open the in-process player monitor when ``memory.enabled`` is true.

    Returns ``None`` when disabled or LC.exe / the driver is unavailable.
    ``connect_retries`` is unused; the DLL attaches on the snapshot call.
    """
    del connect_retries
    section = (config or {}).get("memory") or {}
    if not bool(section.get("enabled", False)):
        return None
    try:
        from manmabot_v1.player_monitor import shared_monitor

        reader = shared_monitor()
        mon = InProcessMonitor(reader)
        mon.ping()
        return mon
    except Exception as exc:
        if not quiet:
            from app.bot_log import get_logger

            get_logger("memory").warning("player memory unavailable: %s", exc)
        return None


class InProcessMonitor:
    """Same snapshot/ping/close surface the pipe client used to provide."""

    def __init__(self, reader: Any) -> None:
        self._reader = reader

    @property
    def connected(self) -> bool:
        return not getattr(self._reader, "_closed", True)

    def snapshot(self, fresh: bool = False) -> dict[str, Any]:
        data = self._reader.snapshot(fresh=fresh)
        if not isinstance(data, dict) or "player" not in data:
            raise ConnectionError("player memory unavailable")
        return data

    def ping(self) -> dict[str, Any]:
        self.snapshot(fresh=False)
        return {"cmd": "ping", "pong": True}

    def close(self) -> None:
        return None


__all__ = [
    "PIPE_NAME",
    "LineageMonitor",
    "InProcessMonitor",
    "open_monitor_from_config",
]
