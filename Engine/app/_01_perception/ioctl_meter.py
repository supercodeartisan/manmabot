"""Read the process-wide reader IOCTL counter (``Local\\ManmabotPgIoctl``).

Slot 0 is the total pages filled by the snapshot DLLs (print_state, monitor,
inventory, hotbar, buff, uidialog, shop). ``body_pose`` DeviceIoControl is
outside this meter.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional

from app.bot_log import get_logger

FILE_MAP_ALL_ACCESS = 0xF001F
_MAP_NAME = "Local\\ManmabotPgIoctl"

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_size_t,
]


class _WinStats:
    __slots__ = ("n", "total", "min_v", "max_v")

    def __init__(self) -> None:
        self.n = 0
        self.total = 0
        self.min_v: Optional[int] = None
        self.max_v: Optional[int] = None

    def add(self, v: int) -> None:
        if v < 0:
            return
        self.n += 1
        self.total += v
        if self.min_v is None or v < self.min_v:
            self.min_v = v
        if self.max_v is None or v > self.max_v:
            self.max_v = v

    def avg(self) -> float:
        if self.n <= 0:
            return 0.0
        return self.total / self.n

    def reset(self) -> None:
        self.n = 0
        self.total = 0
        self.min_v = None
        self.max_v = None

    def fmt(self) -> str:
        if self.n <= 0 or self.min_v is None or self.max_v is None:
            return "min=- max=- avg=-"
        return f"min={self.min_v} max={self.max_v} avg={self.avg():.1f}"


class IoctlMeterLogger:
    """Sample after each ``capture_tick``; log min/max/avg on an interval."""

    def __init__(self, *, log_every_s: float = 10.0) -> None:
        self._log_every_s = max(1.0, float(log_every_s))
        self._view: Optional[ctypes.POINTER(ctypes.c_longlong)] = None
        self._map_handle = None
        self._last_total: Optional[int] = None
        self._tick = _WinStats()
        self._rate = _WinStats()
        self._life_tick = _WinStats()
        self._life_rate = _WinStats()
        self._sec_sum = 0
        self._sec_t0 = time.perf_counter()
        self._log_t0 = time.perf_counter()
        self._log = get_logger("ioctl")
        self._warned_missing = False

    def _ensure_view(self) -> bool:
        if self._view is not None:
            return True
        h = _k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, _MAP_NAME)
        if not h:
            return False
        p = _k32.MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, 64)
        if not p:
            return False
        self._map_handle = h
        self._view = ctypes.cast(p, ctypes.POINTER(ctypes.c_longlong))
        return True

    def read_total(self) -> Optional[int]:
        if not self._ensure_view():
            return None
        assert self._view is not None
        return int(self._view[0])

    def note_after_capture(self) -> None:
        """Call once after ``sensors.capture_tick`` returns."""
        total = self.read_total()
        if total is None:
            if not self._warned_missing:
                self._warned_missing = True
                self._log.info(
                    "ioctl meter unavailable (reader DLLs not attached yet)"
                )
            return
        self._warned_missing = False
        if self._last_total is None:
            self._last_total = total
            self._sec_t0 = time.perf_counter()
            self._log_t0 = time.perf_counter()
            return
        delta = total - self._last_total
        self._last_total = total
        if delta < 0:
            # Mapping replaced (re-attach). Resync.
            return
        self._tick.add(delta)
        self._life_tick.add(delta)
        self._sec_sum += delta
        now = time.perf_counter()
        if now - self._sec_t0 >= 1.0:
            # Normalize to per-second for the elapsed window.
            elapsed = now - self._sec_t0
            rate = int(round(self._sec_sum / elapsed)) if elapsed > 0 else self._sec_sum
            self._rate.add(rate)
            self._life_rate.add(rate)
            self._sec_sum = 0
            self._sec_t0 = now
        if now - self._log_t0 >= self._log_every_s:
            self._emit(window=True)
            self._tick.reset()
            self._rate.reset()
            self._log_t0 = now

    def _emit(self, *, window: bool) -> None:
        label = "ioctl window" if window else "ioctl session"
        self._log.info(
            "%s tick %s (n=%d) | per_s %s (n=%d)",
            label,
            self._tick.fmt() if window else self._life_tick.fmt(),
            self._tick.n if window else self._life_tick.n,
            self._rate.fmt() if window else self._life_rate.fmt(),
            self._rate.n if window else self._life_rate.n,
        )

    def flush(self) -> None:
        """Log lifetime min/max/avg (call on bot stop)."""
        # Close the open second window into rate stats.
        now = time.perf_counter()
        if self._sec_sum > 0 and now > self._sec_t0:
            elapsed = now - self._sec_t0
            rate = int(round(self._sec_sum / elapsed)) if elapsed > 0 else self._sec_sum
            self._rate.add(rate)
            self._life_rate.add(rate)
            self._sec_sum = 0
            self._sec_t0 = now
        if self._life_tick.n <= 0 and self._tick.n > 0:
            # Short run: fold the unfinished window into life.
            self._life_tick.n = self._tick.n
            self._life_tick.total = self._tick.total
            self._life_tick.min_v = self._tick.min_v
            self._life_tick.max_v = self._tick.max_v
            self._life_rate.n = self._rate.n
            self._life_rate.total = self._rate.total
            self._life_rate.min_v = self._rate.min_v
            self._life_rate.max_v = self._rate.max_v
        if self._life_tick.n <= 0:
            self._log.info("ioctl session no samples")
            return
        self._emit(window=False)
