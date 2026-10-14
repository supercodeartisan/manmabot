"""Small, testable policies for automatic game-session recovery."""
from __future__ import annotations

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque


@dataclass
class RecoveryBudget:
    """Allow a bounded number of recoveries inside a rolling time window."""

    max_attempts: int = 3
    window_s: float = 600.0
    clock: Callable[[], float] = time.monotonic
    _attempts: Deque[float] = field(default_factory=deque)

    def claim(self) -> bool:
        now = self.clock()
        cutoff = now - max(1.0, float(self.window_s))
        while self._attempts and self._attempts[0] < cutoff:
            self._attempts.popleft()
        if len(self._attempts) >= max(1, int(self.max_attempts)):
            return False
        self._attempts.append(now)
        return True

    def reset(self) -> None:
        self._attempts.clear()

    @property
    def attempts_in_window(self) -> int:
        now = self.clock()
        cutoff = now - max(1.0, float(self.window_s))
        while self._attempts and self._attempts[0] < cutoff:
            self._attempts.popleft()
        return len(self._attempts)


@dataclass(frozen=True)
class SessionPreparation:
    ok: bool
    cancelled: bool = False
    detail: str = ""


def prepare_session(
    *,
    account: object | None,
    cancel_event: threading.Event,
    game_ready: Callable[[], bool],
    run_login: Callable[[object, threading.Event], object],
    ensure_memory: Callable[[], object],
) -> SessionPreparation:
    """Login only when needed, then require a working memory monitor."""
    if cancel_event.is_set():
        return SessionPreparation(False, True, "cancelled")
    if not game_ready():
        if account is None:
            return SessionPreparation(False, False, "account_required")
        login = run_login(account, cancel_event)
        if (
            cancel_event.is_set()
            or bool(getattr(login, "cancelled", False))
            or getattr(login, "state", "") == "cancelled"
        ):
            return SessionPreparation(False, True, "cancelled")
        if not bool(getattr(login, "succeeded", False)):
            return SessionPreparation(
                False, False, str(getattr(login, "detail", "") or "login_failed")
            )
    if cancel_event.is_set():
        return SessionPreparation(False, True, "cancelled")
    monitor = ensure_memory()
    return SessionPreparation(
        bool(getattr(monitor, "ok", False)),
        False,
        str(getattr(monitor, "detail", "") or ""),
    )
