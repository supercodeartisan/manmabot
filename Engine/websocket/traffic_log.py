"""In-process log of party socket frames for the party monitor.

Status advertisements stay out. The leader records what it sends and what
members send in. A member records what it sends and what the leader sends.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

_lock = threading.Lock()
_lines: deque[str] = deque(maxlen=400)


def clear() -> None:
    with _lock:
        _lines.clear()


def snapshot() -> list[str]:
    with _lock:
        return list(_lines)


def note(direction: str, message: Any) -> None:
    try:
        body = getattr(message, "message", message)
        if isinstance(body, dict) and str(body.get("type") or "") == "status":
            return
        sender = str(getattr(message, "sender", "") or "?").strip() or "?"
        ts = getattr(message, "ts", None) or time.time()
        try:
            stamp = time.strftime("%H:%M:%S", time.localtime(float(ts)))
        except (TypeError, ValueError, OSError):
            stamp = time.strftime("%H:%M:%S")
        line = f"{stamp}  {str(direction or '?'):<4}  {sender}  {_body_text(body)}"
        with _lock:
            _lines.append(line)
    except Exception:
        return


def _body_text(body: Any) -> str:
    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    if body is None:
        return ""
    return str(body)


__all__ = ["clear", "note", "snapshot"]
