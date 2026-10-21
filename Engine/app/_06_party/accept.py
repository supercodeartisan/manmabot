"""Member side of the in-game invite: leader notice → wait → type Y.

The leader sends ``party_invite`` right after ``/초대 <to>`` reached its game.
The popup ([Yes]/[No]) has no memory sensor, so the notice is the only signal.
Y goes out through the same typing module as the leader's ``/초대`` line
(``app._05_action.chat`` → enter_chat), without opening chat and without Enter.

The leader repeats the invite every 20 s; a notice while one is already queued
keeps the first due time, so the repeats never push the press back.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Optional

ACCEPT_TEXT = "y"
ACCEPT_DELAY_S = 30.0


def type_accept_key() -> str:
    """Type Y into the game window. Returns "" on success, else the error."""
    from app._05_action.chat import send_chat_line

    try:
        result = send_chat_line(ACCEPT_TEXT, open_chat=False, press_enter=False)
    except Exception as exc:
        return str(exc)
    return "" if result.ok else result.describe()


def _note_monitor(text: str) -> None:
    try:
        from websocket.traffic_log import note_local

        note_local(text)
    except Exception:
        pass


class InviteAccepter:
    """One per member run. ``on_notice`` queues, ``tick`` presses when due."""

    def __init__(
        self,
        *,
        delay_s: float = ACCEPT_DELAY_S,
        press: Callable[[], str] = type_accept_key,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda _m: None,
    ) -> None:
        self.delay_s = max(0.0, float(delay_s))
        self._press = press
        self._clock = clock
        self._log = log
        self._due: Optional[float] = None
        self.to = ""
        self.received_at: Optional[float] = None
        self.pressed_at: Optional[float] = None
        self.presses = 0
        self.error = ""
        self.skipped = ""

    @property
    def pending(self) -> bool:
        return self._due is not None

    def reset(self) -> None:
        self._due = None
        self.to = ""
        self.received_at = None
        self.pressed_at = None
        self.presses = 0
        self.error = ""
        self.skipped = ""

    def on_notice(
        self,
        invite: dict[str, Any],
        *,
        self_name: str = "",
        roster_names: Iterable[str] = (),
        in_party: bool = False,
    ) -> None:
        to = str(invite.get("to") or "").strip()
        roster = {str(n or "").strip().casefold() for n in roster_names if str(n or "").strip()}
        name = str(self_name or "").strip()
        skip = ""
        if in_party:
            skip = "already in a party — Y not pressed"
        # Only a confirmed roster name may veto; a wrong local name must not block accept.
        elif name and to and name.casefold() != to.casefold() and name.casefold() in roster:
            skip = f"invite is for {to}, this is {name} — Y not pressed"
        self.to = to
        if skip:
            self._due = None
            self.skipped = skip
            self._log(f"Party invite notice: {skip}")
            return
        self.skipped = ""
        self.error = ""
        if self._due is not None:
            return
        self.received_at = time.time()
        self._due = self._clock() + self.delay_s
        self._log(f"Party invite notice for {to or '—'} — typing Y in {int(self.delay_s)}s")

    def tick(self, *, in_party: bool = False) -> bool:
        """Type Y once the delay is over. True when Y reached the game this tick."""
        if self._due is None or self._clock() < self._due:
            return False
        self._due = None
        if in_party:
            self.skipped = "joined before the delay — Y not pressed"
            self._log(f"Party invite accept: {self.skipped}")
            return False
        error = self._press()
        if error:
            self.error = error
            self._log(f"Party invite accept (Y) failed: {error}")
            _note_monitor(f"Y FAILED: {error}")
            return False
        self.pressed_at = time.time()
        self.presses += 1
        self._log(f"Party invite accept: Y typed for {self.to or '—'}")
        _note_monitor("Y typed (accept invite)")
        return True

    def status(self) -> dict[str, Any]:
        due_in = None
        if self._due is not None:
            due_in = round(max(0.0, self._due - self._clock()), 1)
        return {
            "pending": self.pending,
            "due_in_s": due_in,
            "delay_s": self.delay_s,
            "to": self.to,
            "received_at": self.received_at,
            "pressed_at": self.pressed_at,
            "presses": self.presses,
            "error": self.error,
            "skipped": self.skipped,
        }


__all__ = [
    "ACCEPT_DELAY_S",
    "ACCEPT_TEXT",
    "InviteAccepter",
    "type_accept_key",
]
