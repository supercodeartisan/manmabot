"""Farm keyboard input through the hunt input backend."""
from __future__ import annotations

import random
import threading
import time
from typing import Optional

from app._05_action import humanize as hz
from app._05_action import input_backend as ib

_held_lock = threading.Lock()
_held_keys: set[str] = set()


class KeyboardController:
    """Low-level keyboard control for game interaction (hunt input backend)."""

    def __init__(
        self,
        enabled: bool = True,
        humanize: bool = True,
        rng: Optional[random.Random] = None,
    ):
        self.enabled = enabled
        self.humanize = humanize
        self._rng = rng if rng is not None else random.Random()

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def press(self, key: str, duration: float | None = None) -> None:
        """Press and release a key with a humanized hold duration."""
        name = str(key or "")
        _log_key("request", name, enabled=self.enabled)
        if not self.enabled:
            return
        ib.ensure_open()
        if duration is None:
            duration = (
                hz.uniform(hz.KEY_HOLD, self._rng)
                if self.humanize
                else 0.05
            )
        overlap = _mark_down(name)
        try:
            ib.key_down(name)
        except Exception as exc:
            _mark_up(name)
            _log_key("down", name, ok=False, error=exc)
            raise
        _log_key("down", name, ok=True, overlap=overlap)
        time.sleep(duration)
        try:
            ib.key_up(name)
        except Exception as exc:
            _log_key("up", name, ok=False, error=exc, missing_down=False)
            raise
        missing = _mark_up(name)
        _log_key("up", name, ok=True, missing_down=missing)

    def hold(self, key: str) -> None:
        """Hold a key down (call release to let go)."""
        name = str(key or "")
        _log_key("request", name, enabled=self.enabled, hold=True)
        if not self.enabled:
            return
        ib.ensure_open()
        overlap = _mark_down(name)
        try:
            ib.key_down(name)
        except Exception as exc:
            _mark_up(name)
            _log_key("down", name, ok=False, error=exc, hold=True)
            raise
        _log_key("down", name, ok=True, overlap=overlap, hold=True)

    def release(self, key: str) -> None:
        """Release a held key."""
        name = str(key or "")
        if not self.enabled:
            _log_key("request", name, enabled=False, release=True)
            return
        ib.ensure_open()
        try:
            ib.key_up(name)
        except Exception as exc:
            _log_key("up", name, ok=False, error=exc, release=True)
            raise
        missing = _mark_up(name)
        _log_key("up", name, ok=True, missing_down=missing, release=True)

    def tap(self, key: str, count: int = 1, interval: float | None = None) -> None:
        """Tap a key multiple times."""
        for i in range(count):
            self.press(key)
            if i + 1 < count:
                gap = (
                    interval
                    if interval is not None
                    else (
                        hz.uniform((0.06, 0.18), self._rng)
                        if self.humanize
                        else 0.1
                    )
                )
                time.sleep(gap)

    def combo(self, *keys: str, hold_time: float | None = None) -> None:
        """Press multiple keys simultaneously."""
        if not self.enabled:
            return
        ib.ensure_open()
        if hold_time is None:
            hold_time = (
                hz.uniform(hz.KEY_HOLD, self._rng)
                if self.humanize
                else 0.1
            )
        for key in keys:
            ib.key_down(key)
            _mark_down(str(key))
        time.sleep(hold_time)
        for key in reversed(keys):
            ib.key_up(key)
            _mark_up(str(key))


def _mark_down(key: str) -> bool:
    """True when this key was already recorded down. Does not send input."""
    with _held_lock:
        overlap = key in _held_keys
        _held_keys.add(key)
    return overlap


def _mark_up(key: str) -> bool:
    """True when Key Up ran without a matching Key Down record."""
    with _held_lock:
        missing = key not in _held_keys
        _held_keys.discard(key)
    return missing


def _log_key(
    stage: str,
    key: str,
    *,
    enabled: bool | None = None,
    ok: bool | None = None,
    overlap: bool | None = None,
    missing_down: bool | None = None,
    error: BaseException | None = None,
    hold: bool = False,
    release: bool = False,
) -> None:
    """Diagnostic only. A logging failure must not change the key sequence."""
    try:
        from app.bot_log import event

        parts = [f"key {stage} key={key}"]
        if enabled is not None:
            parts.append(f"enabled={int(bool(enabled))}")
        if ok is not None:
            parts.append(f"ok={int(bool(ok))}")
        if overlap is not None:
            parts.append(f"overlap={int(bool(overlap))}")
        if missing_down is not None:
            parts.append(f"missing_down={int(bool(missing_down))}")
        if hold:
            parts.append("hold=1")
        if release:
            parts.append("release=1")
        if error is not None:
            parts.append(f"error={error}")
        if stage in ("request", "down", "up"):
            parts.append(ib.expected_key_scan(key))
        if stage in ("down", "up") or (stage == "request" and enabled):
            parts.append(ib.input_diag())
        parts.append(f"thread={threading.get_ident()}")
        event("input", "%s", " ".join(parts))
    except Exception:
        return
