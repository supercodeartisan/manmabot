"""Type one chat line into the LC client through ``enter_chat``.

Hangul goes out as 2-beolsik jamo keys through Interception and the Korean
IME; other characters as ``WM_CHAR`` (the bot runs elevated). Enter opens the
input line and sends it. No clipboard and no SendInput.
"""
from __future__ import annotations

import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable, Optional

from .handoff import bot_input_released
from .native import EcFlag, EcRequest, EcStatus, EnterChatLibrary

GAME_PROCESS = "LC.exe"


@dataclass(frozen=True)
class TypingPace:
    chars_per_second: float = 9.0
    jitter_ms: int = 35
    jamo_delay_ms: int = 8
    focus_timeout_ms: int = 1500


@dataclass(frozen=True)
class ChatResult:
    text: str
    status: EcStatus
    message: str = ""
    chars: int = 0
    keys: int = 0
    failed: int = 0
    enter_pressed: bool = False
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status == EcStatus.OK

    def describe(self) -> str:
        detail = f"{self.status.name.lower()}"
        if self.message:
            detail += f": {self.message}"
        return detail


def _find_game_hwnd() -> Optional[int]:
    from app._05_action.window_bounds import find_game_window

    return find_game_window(GAME_PROCESS)


class GameChat:
    """Send chat lines to the game. One line per call, serialized."""

    def __init__(
        self,
        *,
        library: Optional[EnterChatLibrary] = None,
        pace: TypingPace = TypingPace(),
        find_hwnd: Callable[[], Optional[int]] = _find_game_hwnd,
        input_handoff: Callable[[], AbstractContextManager] = bot_input_released,
    ) -> None:
        self._library = library or EnterChatLibrary()
        self._pace = pace
        self._find_hwnd = find_hwnd
        self._input_handoff = input_handoff
        self._lock = threading.Lock()

    def send(
        self,
        text: str,
        *,
        open_chat: bool = True,
        press_enter: bool = True,
        dry_run: bool = False,
    ) -> ChatResult:
        line = str(text or "").strip()
        if not line:
            return ChatResult(text=line, status=EcStatus.ARGUMENT, message="empty line")
        hwnd = self._find_hwnd()
        if not hwnd:
            return ChatResult(
                text=line, status=EcStatus.PID, message=f"{GAME_PROCESS} window not found"
            )
        flags = EcFlag.NONE
        if open_chat:
            flags |= EcFlag.OPEN_CHAT
        if dry_run:
            flags |= EcFlag.DRY_RUN
        request = EcRequest(
            text=line,
            pid=0,
            hwnd=int(hwnd),
            chars_per_second=float(self._pace.chars_per_second),
            jitter_ms=int(self._pace.jitter_ms),
            jamo_delay_ms=int(self._pace.jamo_delay_ms),
            press_enter=bool(press_enter),
            flags=int(flags),
            focus_timeout_ms=int(self._pace.focus_timeout_ms),
        )
        with self._lock:
            if dry_run:
                raw = self._library.run(request)
            else:
                with self._input_handoff():
                    raw = self._library.run(request)
        try:
            status = EcStatus(int(raw.status))
        except ValueError:
            status = EcStatus.INTERNAL
        return ChatResult(
            text=line,
            status=status,
            message=str(raw.message or "").strip(),
            chars=int(raw.chars),
            keys=int(raw.keys),
            failed=int(raw.failed),
            enter_pressed=bool(raw.enter_pressed),
            elapsed_ms=int(raw.elapsed_ms),
        )


    def press_key(
        self,
        scancode: int,
        *,
        label: str = "",
        hold_ms: int = 40,
        english: bool = False,
    ) -> ChatResult:
        """One physical key in the game window (a key event, not ``WM_CHAR``).

        ``english`` = hold the game IME out of 한글 mode for this key (a letter
        key in 한글 mode is a jamo composition, not the letter)."""
        name = label or f"scan 0x{int(scancode):02X}"
        hwnd = self._find_hwnd()
        if not hwnd:
            return ChatResult(
                text=name, status=EcStatus.PID, message=f"{GAME_PROCESS} window not found"
            )
        ime_note = ""
        with self._lock:
            with self._input_handoff():
                if english:
                    from .ime import english_ime

                    with english_ime(int(hwnd)) as ime_note:
                        raw = self._library.press_key(
                            hwnd=int(hwnd),
                            scancode=int(scancode),
                            hold_ms=int(hold_ms),
                            focus_timeout_ms=int(self._pace.focus_timeout_ms),
                        )
                        # The game reads the key after we return; keep English until then.
                        time.sleep(0.15)
                else:
                    raw = self._library.press_key(
                        hwnd=int(hwnd),
                        scancode=int(scancode),
                        hold_ms=int(hold_ms),
                        focus_timeout_ms=int(self._pace.focus_timeout_ms),
                    )
        try:
            status = EcStatus(int(raw.status))
        except ValueError:
            status = EcStatus.INTERNAL
        message = str(raw.message or "").strip()
        if ime_note:
            message = f"{message} [ime {ime_note}]".strip()
        return ChatResult(
            text=name,
            status=status,
            message=message,
            keys=int(raw.keys),
            failed=int(raw.failed),
            elapsed_ms=int(raw.elapsed_ms),
        )


_default_chat: Optional[GameChat] = None
_default_lock = threading.Lock()


def default_game_chat() -> GameChat:
    global _default_chat
    with _default_lock:
        if _default_chat is None:
            _default_chat = GameChat()
        return _default_chat


def send_chat_line(text: str, **kwargs) -> ChatResult:
    """Open chat, type ``text``, press Enter. See :meth:`GameChat.send`."""
    return default_game_chat().send(text, **kwargs)


__all__ = [
    "ChatResult",
    "GAME_PROCESS",
    "GameChat",
    "TypingPace",
    "default_game_chat",
    "send_chat_line",
]
