"""Member side of the in-game invite: leader notice → wait → type Y.

The leader sends ``party_invite`` right after ``/초대 <to>`` reached its game.
The popup ([Yes]/[No]) has no memory sensor, so the notice is the only signal.
Y goes out through the same typing module as the leader's ``/초대`` line
(``app._05_action.chat`` → enter_chat), as a physical key through Interception:
a typed ``y`` (``WM_CHAR``) reaches the game but the popup ignores it.

The leader may resend one notice (same ``invite_id``) until this member's
``member_state`` echoes it; a repeated id is ignored. A new id while one is
queued keeps the first due time, so repeats never push the press back.

``phase`` (sent to the leader in ``member_state``):
idle · waiting (Y queued) · pressed (join check running) · joined · missed
(no join after Y) · unverified (party memory unreadable) · skipped · failed.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Optional

# Set-1 scancode of the Y key.
ACCEPT_SCANCODE = 0x15
ACCEPT_DELAY_S = 30.0
# After Y, party memory should show the join within this time.
JOIN_CHECK_S = 5.0


def type_accept_key() -> str:
    """Press Y in the game window. Returns "" on success, else the error."""
    from app._05_action.chat import default_game_chat

    try:
        result = default_game_chat().press_key(ACCEPT_SCANCODE, label="Y (party invite)")
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
        self.reset()

    @property
    def pending(self) -> bool:
        return self._due is not None

    def reset(self) -> None:
        self._due = None
        self._check_at = None
        self._seen_ids: list[str] = []
        self.invite_id = ""
        self.join_missed = 0
        self.joined = False
        self.unverified = False
        self.to = ""
        self.received_at: Optional[float] = None
        self.pressed_at: Optional[float] = None
        self.presses = 0
        self.error = ""
        self.skipped = ""

    @property
    def phase(self) -> str:
        if self._due is not None:
            return "waiting"
        if self.error:
            return "failed"
        if self.skipped:
            return "joined" if self.joined else "skipped"
        if self._check_at is not None:
            return "pressed"
        if self.pressed_at is not None:
            if self.joined:
                return "joined"
            return "unverified" if self.unverified else "missed"
        return "idle"

    def on_notice(
        self,
        invite: dict[str, Any],
        *,
        self_name: str = "",
        roster_names: Iterable[str] = (),
        in_party: Optional[bool] = False,
    ) -> None:
        """``in_party`` None = party memory unreadable (does not block Y)."""
        iid = str(invite.get("invite_id") or "")
        if iid:
            if iid in self._seen_ids:
                return
            self._seen_ids = (self._seen_ids + [iid])[-32:]
            self.invite_id = iid
        to = str(invite.get("to") or "").strip()
        roster = {str(n or "").strip().casefold() for n in roster_names if str(n or "").strip()}
        name = str(self_name or "").strip()
        skip = ""
        if in_party:
            skip = "already in a party — Y not pressed"
            self.joined = True
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
        self._log(
            f"Party invite notice for {to or '—'} (id {iid or '—'}) — "
            f"pressing Y in {int(self.delay_s)}s"
        )

    def tick(self, *, in_party: Optional[bool] = False) -> bool:
        """Press Y once the delay is over. True when Y reached the game this tick.

        ``in_party`` None = party memory unreadable: the join is "unverified".
        """
        if in_party and self.pressed_at is not None and not self.joined:
            self.joined = True
            self.unverified = False
            if self._check_at is None:
                self._log("Party invite accept: joined (party memory)")
        if self._check_at is not None and (in_party or self._clock() >= self._check_at):
            self._check_at = None
            if in_party:
                self._log("Party invite accept: joined after Y")
            elif in_party is None:
                self.unverified = True
                self._log(
                    "Party invite accept: party memory unreadable — "
                    "join after Y not verified"
                )
            else:
                self.join_missed += 1
                self._log(
                    f"Party invite accept: still not in a party {int(JOIN_CHECK_S)}s after Y "
                    "(popup closed / expired, or the key did not reach it)"
                )
        if self._due is None or self._clock() < self._due:
            return False
        self._due = None
        if in_party:
            self.joined = True
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
        self.joined = False
        self.unverified = False
        self._check_at = self._clock() + JOIN_CHECK_S
        self._log(f"Party invite accept: Y key pressed for {self.to or '—'}")
        _note_monitor("Y key pressed (accept invite)")
        return True

    def status(self) -> dict[str, Any]:
        due_in = None
        if self._due is not None:
            due_in = round(max(0.0, self._due - self._clock()), 1)
        return {
            "phase": self.phase,
            "invite_id": self.invite_id,
            "pending": self.pending,
            "due_in_s": due_in,
            "delay_s": self.delay_s,
            "to": self.to,
            "received_at": self.received_at,
            "pressed_at": self.pressed_at,
            "presses": self.presses,
            "join_missed": self.join_missed,
            "error": self.error,
            "skipped": self.skipped,
        }


__all__ = [
    "ACCEPT_DELAY_S",
    "ACCEPT_SCANCODE",
    "InviteAccepter",
    "type_accept_key",
]
