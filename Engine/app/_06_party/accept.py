"""Member side of the in-game invite: invite popup → Y → ``invite_accept``.

The member reads the Yes/No invite popup itself (``invite_popup.party_invite``
on the uidialog snapshot) — no leader notice, no delay. Y goes out as a
physical key through Interception (``app._05_action.chat`` → enter_chat; a
typed ``y`` as ``WM_CHAR`` is ignored by the popup), with the game IME held in
English for the key (in 한글 mode Y is the jamo ``ㅛ``).

Accepted = the popup closed after Y. The member then sends ``invite_accept``
to the leader (repeated ``ACK_SENDS`` times, same ``accept_id``) and reports
phase ``accepted`` in ``member_state``. Y is pressed again if the popup is
still open ``REPRESS_S`` after a press, at most ``MAX_PRESSES`` per popup.

A popup from someone other than the leader (``leader_name`` from the policy,
when known) is left alone. Once party memory showed the join, losing it for
``LEFT_CONFIRM_S`` turns ``accepted`` into ``left`` so the leader invites again.

``phase`` (sent to the leader in ``member_state``):
idle · popup (open, Y due) · pressed · accepted · left · missed (closed before
Y) · skipped (not from the leader) · failed (Y did not reach the game / popup
stayed open after every press).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .invite_popup import same_name

# Set-1 scancode of the Y key.
ACCEPT_SCANCODE = 0x15
# Popup still open this long after Y: press again.
REPRESS_S = 2.0
MAX_PRESSES = 3
# ``invite_accept`` is sent this many times (the leader books one per id).
ACK_SENDS = 3
ACK_EVERY_S = 2.0
# Party memory lost this long after it showed the join = left the party.
LEFT_CONFIRM_S = 10.0


def _press_y_hunt() -> str:
    """Y through the hunt keyboard when ``enter_chat.dll`` is missing."""
    from app._05_action import input_backend as ib
    from app._05_action.chat.ime import english_ime
    from app._05_action.window_bounds import find_game_window

    hwnd = find_game_window("LC.exe")
    try:
        ib.ensure_open()
        if hwnd:
            with english_ime(int(hwnd)):
                ib.key_down("y")
                time.sleep(0.04)
                ib.key_up("y")
                time.sleep(0.15)
        else:
            ib.key_down("y")
            time.sleep(0.04)
            ib.key_up("y")
        return ""
    except Exception as exc:
        return str(exc)


def type_accept_key() -> str:
    """Press Y in the game window (IME held in English). "" on success, else the error."""
    from app._05_action.chat import default_game_chat
    from app._05_action.chat.native import EnterChatUnavailable

    dll_error = ""
    try:
        result = default_game_chat().press_key(
            ACCEPT_SCANCODE, label="Y (party invite)", english=True
        )
        if result.ok:
            return ""
        dll_error = result.describe()
    except EnterChatUnavailable as exc:
        dll_error = str(exc)
    except Exception as exc:
        dll_error = str(exc)
    hunt_error = _press_y_hunt()
    if not hunt_error:
        return ""
    return dll_error or hunt_error


def _note_monitor(text: str) -> None:
    try:
        from websocket.traffic_log import note_local

        note_local(text)
    except Exception:
        pass


class InviteAccepter:
    """One per member run; ``tick`` every bot tick with the current popup."""

    def __init__(
        self,
        *,
        press: Callable[[], str] = type_accept_key,
        send_ack: Callable[[dict[str, Any]], bool] = lambda _body: False,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda _m: None,
    ) -> None:
        self._press = press
        self._send_ack = send_ack
        self._clock = clock
        self._log = log
        self.reset()

    def reset(self) -> None:
        self.phase = "idle"
        self.accept_id = ""
        self.inviter = ""
        self.msg = ""
        self.ask = 0
        self.seen_at: Optional[float] = None
        self.pressed_at: Optional[float] = None
        self.accepted_at: Optional[float] = None
        self.presses = 0
        self.popups = 0
        self.error = ""
        self.skipped = ""
        self.acks_sent = 0
        self._open = False
        self._last_press: Optional[float] = None
        self._ack_at: Optional[float] = None
        self._mem_seen = False
        self._mem_out_since: Optional[float] = None

    def tick(
        self,
        popup: Optional[dict[str, Any]],
        *,
        leader_name: str = "",
        name: str = "",
        session: str = "",
        in_party: Optional[bool] = None,
    ) -> bool:
        """One step. ``popup`` = ``invite_popup.party_invite`` (None = no invite
        popup open). ``in_party`` None = party memory unreadable. True when Y
        reached the game this tick."""
        pressed = False
        if in_party is True:
            if popup is not None and self.phase not in ("accepted", "left"):
                if self.skipped != "already in party":
                    self.skipped = "already in party"
                    self.phase = "skipped"
                    self._log(
                        "Party invite popup ignored — already in party (memory)"
                    )
            self._track_membership(in_party)
            return False
        if popup is not None:
            pressed = self._on_open(popup, leader_name)
        elif self._open:
            self._on_closed()
        self._track_membership(in_party)
        self._maybe_ack(name, session)
        return pressed

    def _on_open(self, popup: dict[str, Any], leader_name: str) -> bool:
        if not self._open:
            from .comms.orders import new_invite_id

            self._open = True
            self.popups += 1
            self.accept_id = new_invite_id()
            self.inviter = str(popup.get("inviter") or "")
            self.msg = str(popup.get("msg") or "")
            self.ask = int(popup.get("ask") or 0)
            self.seen_at = time.time()
            self.pressed_at = None
            self.accepted_at = None
            self.presses = 0
            self.error = ""
            self.skipped = ""
            self.acks_sent = 0
            self._ack_at = None
            self._last_press = None
            self._mem_seen = False
            self._mem_out_since = None
            if leader_name and self.inviter and not same_name(self.inviter, leader_name):
                self.skipped = f"invite from {self.inviter}, leader is {leader_name} — Y not pressed"
                self.phase = "skipped"
                self._log(f"Party invite popup: {self.skipped}")
                return False
            self.phase = "popup"
            self._log(
                f"Party invite popup from {self.inviter or '—'} (ask {self.ask}) — pressing Y"
            )
            _note_monitor(f"invite popup from {self.inviter or '—'}")
        if self.phase not in ("popup", "pressed"):
            return False
        now = self._clock()
        if self._last_press is not None and now - self._last_press < REPRESS_S:
            return False
        if self.presses >= MAX_PRESSES:
            if self.phase != "failed":
                self.phase = "failed"
                self.error = f"popup still open after {self.presses} Y presses"
                self._log(f"Party invite accept failed: {self.error}")
                _note_monitor(f"Y FAILED: {self.error}")
            return False
        error = self._press()
        self._last_press = now
        if error:
            self.presses += 1
            self.error = error
            self._log(f"Party invite accept (Y) failed: {error}")
            _note_monitor(f"Y FAILED: {error}")
            return False
        self.presses += 1
        self.error = ""
        self.pressed_at = time.time()
        self.phase = "pressed"
        self._log(f"Party invite accept: Y pressed (#{self.presses}) for {self.inviter or '—'}")
        _note_monitor(f"Y key pressed #{self.presses} (accept invite)")
        return True

    def _on_closed(self) -> None:
        self._open = False
        if self.phase == "pressed":
            self.phase = "accepted"
            self.accepted_at = time.time()
            self._log(
                f"Party invite accepted: popup closed after Y "
                f"(from {self.inviter or '—'}, {self.presses} press(es))"
            )
            _note_monitor("invite accepted (popup closed after Y)")
        elif self.phase == "popup":
            self.phase = "missed"
            self._log("Party invite popup closed before Y was pressed")

    def _track_membership(self, in_party: Optional[bool]) -> None:
        if self.phase != "accepted" or in_party is None:
            self._mem_out_since = None
            return
        if in_party:
            self._mem_seen = True
            self._mem_out_since = None
            return
        if not self._mem_seen:
            return
        now = self._clock()
        if self._mem_out_since is None:
            self._mem_out_since = now
            return
        if now - self._mem_out_since >= LEFT_CONFIRM_S:
            self.phase = "left"
            self._log(
                f"Party: party memory lost the party for {int(LEFT_CONFIRM_S)}s "
                "after the accept — reported as left"
            )

    def _maybe_ack(self, name: str, session: str) -> None:
        if self.phase != "accepted" or self.acks_sent >= ACK_SENDS:
            return
        now = self._clock()
        if self._ack_at is not None and now - self._ack_at < ACK_EVERY_S:
            return
        from .comms.orders import invite_accept_message

        body = invite_accept_message(
            name=name,
            session=session,
            accept_id=self.accept_id,
            inviter=self.inviter,
            presses=self.presses,
        )
        try:
            ok = bool(self._send_ack(body))
        except Exception:
            ok = False
        if not ok:
            return
        self._ack_at = now
        self.acks_sent += 1
        if self.acks_sent == 1:
            self._log(f"Party invite accept sent to leader (id {self.accept_id})")
            _note_monitor(f"invite_accept → leader (id {self.accept_id})")

    def report(self) -> dict[str, Any]:
        """The ``invite`` part of ``member_state``."""
        return {
            "id": self.accept_id,
            "phase": self.phase,
            "presses": self.presses,
            "inviter": self.inviter,
        }

    def status(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "accept_id": self.accept_id,
            "inviter": self.inviter,
            "ask": self.ask,
            "msg": self.msg,
            "popup_open": self._open,
            "popups": self.popups,
            "seen_at": self.seen_at,
            "pressed_at": self.pressed_at,
            "accepted_at": self.accepted_at,
            "presses": self.presses,
            "acks_sent": self.acks_sent,
            "error": self.error,
            "skipped": self.skipped,
        }


__all__ = [
    "ACCEPT_SCANCODE",
    "ACK_SENDS",
    "InviteAccepter",
    "MAX_PRESSES",
    "REPRESS_S",
    "type_accept_key",
]
