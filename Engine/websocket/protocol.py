"""Party WebSocket message envelope (schema only).

Wire format is one JSON object per WebSocket text frame::

    {"sender": "캐릭터이름", "ts": 1713000000.123, "message": "..."}

``message`` may be a string or a JSON object (dict/list) for structured
party commands later. This module does not interpret command semantics.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Union

MessageBody = Union[str, dict[str, Any], list[Any]]


@dataclass
class PartyMessage:
    """One party frame: who sent it, when, and the payload."""

    sender: str
    message: MessageBody
    ts: float = 0.0
    # Local only. The server stamps the socket id; it is not on the wire.
    peer: str = ""

    def __post_init__(self) -> None:
        self.sender = str(self.sender or "").strip()
        if not self.ts:
            self.ts = time.time()
        else:
            try:
                self.ts = float(self.ts)
            except (TypeError, ValueError):
                self.ts = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sender": self.sender,
            "ts": self.ts,
            "message": self.message,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Any) -> "PartyMessage":
        if not isinstance(data, dict):
            raise TypeError("party message must be a JSON object")
        sender = data.get("sender")
        if sender is None and "name" in data:
            sender = data.get("name")
        raw_ts = data.get("ts", data.get("time"))
        body = data.get("message")
        if body is None and "msg" in data:
            body = data.get("msg")
        if body is None:
            body = ""
        return cls(sender=str(sender or ""), message=body, ts=float(raw_ts or 0.0) or 0.0)

    @classmethod
    def from_json(cls, raw: str | bytes) -> "PartyMessage":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        text = str(raw or "").strip()
        if not text:
            raise ValueError("empty party message")
        return cls.from_dict(json.loads(text))


def parse_frame(raw: str | bytes) -> PartyMessage:
    """Parse one WebSocket text/binary payload into :class:`PartyMessage`."""
    return PartyMessage.from_json(raw)


__all__ = [
    "MessageBody",
    "PartyMessage",
    "parse_frame",
]
