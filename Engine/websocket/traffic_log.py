"""In-process log of party socket frames for the party monitor.

Status advertisements stay out. Lines are short and readable, not raw JSON.
"""
from __future__ import annotations

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


def _mirror_party_file(level: str, text: str) -> None:
    """Also write to ``party-*.log`` when that session file is open."""
    try:
        from app._06_party import party_log

        if not party_log.active():
            return
        logger = party_log.get_logger("socket")
        if level == "debug":
            logger.debug("%s", text)
        else:
            logger.info("%s", text)
    except Exception:
        return


def note_local(text: str) -> None:
    """Session note in the party monitor (not a socket frame)."""
    try:
        stamp = time.strftime("%H:%M:%S")
        body = str(text or "").strip()
        line = f"{stamp}  ---  local    {body}"
        with _lock:
            _lines.append(line)
        _mirror_party_file("info", f"local {body}")
    except Exception:
        return


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
        way = "OUT" if str(direction or "").lower().startswith("s") else "IN "
        detail = _body_text(body)
        line = f"{stamp}  {way}  {sender:<7}  {detail}"
        with _lock:
            _lines.append(line)
        # Player heartbeats are frequent — file DEBUG; decisions/orders at INFO.
        kind = ""
        if isinstance(body, dict):
            kind = str(body.get("type") or "").strip().lower()
        level = "debug" if kind in ("player", "report") else "info"
        _mirror_party_file(level, f"{way.strip()} {sender} {detail}")
    except Exception:
        return


def _body_text(body: Any) -> str:
    if isinstance(body, dict):
        kind = str(body.get("type") or "").strip().lower()
        if kind == "player":
            return _fmt_player(body)
        if kind == "decision":
            return _fmt_decision(body)
        return _fmt_generic(body)
    if isinstance(body, list):
        return " · ".join(_fmt_value(x) for x in body[:8])
    if body is None:
        return ""
    return str(body)


def _fmt_player(body: dict[str, Any]) -> str:
    parts = ["player"]
    hp = body.get("hp")
    max_hp = body.get("max_hp")
    if hp is not None or max_hp is not None:
        parts.append(f"HP {_pair(hp, max_hp)}")
    mp = body.get("mp")
    max_mp = body.get("max_mp")
    if mp is not None or max_mp is not None:
        parts.append(f"MP {_pair(mp, max_mp)}")
    xy = _xy(body.get("x"), body.get("y"))
    if xy:
        parts.append(xy)
    map_id = body.get("map_id")
    if map_id is not None and map_id != "":
        parts.append(f"map {map_id}")
    level = body.get("level")
    if level is not None and level != "":
        parts.append(f"Lv{level}")
    if body.get("alive") is False:
        parts.append("dead")
    return " · ".join(parts)


def _fmt_decision(body: dict[str, Any]) -> str:
    action = str(body.get("action") or "decision").strip() or "decision"
    parts = [action]
    reason = str(body.get("reason") or "").strip()
    if reason:
        parts.append(reason)
    map_id = body.get("map_id")
    if map_id is not None and map_id != "":
        parts.append(f"map {map_id}")
    xy = _xy(body.get("x"), body.get("y"))
    if xy:
        parts.append(xy)
    shop = str(body.get("shop_kind") or "").strip()
    if shop:
        parts.append(f"shop {shop}")
    gate_to = body.get("gate_to")
    if gate_to is not None and gate_to != "":
        edge = str(body.get("gate_edge") or "").strip()
        parts.append(f"gate→{gate_to}" + (f" ({edge})" if edge else ""))
    dest = body.get("destination")
    if isinstance(dest, (list, tuple)) and len(dest) >= 2:
        dxy = _xy(dest[0], dest[1])
        if dxy:
            parts.append(f"to {dxy}")
    return " · ".join(parts)


def _fmt_generic(body: dict[str, Any]) -> str:
    kind = str(body.get("type") or "msg").strip() or "msg"
    parts = [kind]
    for key, value in body.items():
        if key == "type" or value is None or value == "":
            continue
        parts.append(f"{key}={_fmt_value(value)}")
        if len(parts) >= 6:
            break
    return " · ".join(parts)


def _pair(cur: Any, total: Any) -> str:
    if cur is None and total is None:
        return "—"
    if total is None or total == "":
        return str(cur)
    if cur is None or cur == "":
        return f"—/{total}"
    return f"{cur}/{total}"


def _xy(x: Any, y: Any) -> str:
    if x is None and y is None:
        return ""
    try:
        return f"{int(float(x))},{int(float(y))}"
    except (TypeError, ValueError):
        if x is None or y is None:
            return ""
        return f"{x},{y}"


def _fmt_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, (dict, list)):
        return str(value)[:40]
    return str(value)


__all__ = ["clear", "note", "note_local", "snapshot"]
