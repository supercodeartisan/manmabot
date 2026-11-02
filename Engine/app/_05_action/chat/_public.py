"""Game chat output: type one line into the LC client.

- ``native``  ctypes binding for ``enter_chat.dll`` (``app/_06_party/enter_chat/bin``)
- ``handoff`` lends the bot's Interception devices to the DLL for one call
- ``sender``  :class:`GameChat` / :func:`send_chat_line`

What to say (party commands, etc.) belongs to the caller, not this package.
"""
from __future__ import annotations

from .handoff import bot_input_released
from .native import EcFlag, EcStatus, EnterChatLibrary, EnterChatUnavailable
from .sender import (
    GAME_PROCESS,
    ChatResult,
    GameChat,
    TypingPace,
    default_game_chat,
    send_chat_line,
)

__all__ = [
    "GAME_PROCESS",
    "ChatResult",
    "EcFlag",
    "EcStatus",
    "EnterChatLibrary",
    "EnterChatUnavailable",
    "GameChat",
    "TypingPace",
    "bot_input_released",
    "default_game_chat",
    "send_chat_line",
]
