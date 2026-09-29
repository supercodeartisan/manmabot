"""Persist AUTH relaunch / boot-shake arm across bot2 process restarts.

When GameFlow closes LC for 퍼플간편인증, the launcher LC watchdog may kill
bot2 and spawn a fresh process. In-memory `_shake_after_relaunch` and
`_auth_relaunch_count` would be lost — this marker survives that restart.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

log = logging.getLogger("auth_relaunch_state")

MARKER_FILENAME = "auth_relaunch_state.json"
# Controller cooldown is ~2.5s; full Purple→Start→hwnd can take minutes.
DEFAULT_TTL_S = 15 * 60


def marker_path(base_dir: Optional[str] = None) -> str:
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, MARKER_FILENAME)


def _base_dir_from_bot(bot: Any) -> str:
    base = getattr(bot, "session_backup_dir", None) or getattr(
        bot, "debug_dir", None)
    if base:
        return str(base)
    return os.path.dirname(os.path.abspath(__file__))


def save_auth_relaunch_state(bot: Any) -> str:
    """Write shake/auth counters so a restarted bot2 can re-arm.

    Call before `_close_game` — the process may die during the close sleep.
    """
    base = _base_dir_from_bot(bot)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    path = marker_path(base)
    count = int(getattr(bot, "_auth_relaunch_count", 0) or 0)
    armed = bool(getattr(bot, "_shake_after_relaunch", False))
    used = bool(getattr(bot, "_auth_relaunch_used", False))
    record = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "saved_ts": time.time(),
        "shake_armed": armed,
        "auth_relaunch_count": count,
        "auth_relaunch_used": used,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        log.info("auth relaunch state saved shake=%s count=%d used=%s -> %s",
                 armed, count, used, path)
    except OSError as e:
        log.warning("failed to save auth relaunch state: %r", e)
        return ""
    return path


def load_auth_relaunch_state(bot: Any, ttl_s: float = DEFAULT_TTL_S) -> bool:
    """Restore marker onto bot. Returns True if shake was re-armed."""
    path = marker_path(_base_dir_from_bot(bot))
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError, TypeError) as e:
        log.warning("auth relaunch state unreadable (%r); clearing", e)
        clear_auth_relaunch_state(bot)
        return False

    saved_ts = float(record.get("saved_ts") or 0)
    if saved_ts and (time.time() - saved_ts) > float(ttl_s):
        log.info("auth relaunch state stale (%.0fs > %.0fs TTL); clearing",
                 time.time() - saved_ts, ttl_s)
        clear_auth_relaunch_state(bot)
        return False

    count = int(record.get("auth_relaunch_count") or 0)
    armed = bool(record.get("shake_armed"))
    used = bool(record.get("auth_relaunch_used"))
    if not armed and count <= 0 and not used:
        clear_auth_relaunch_state(bot)
        return False

    bot._auth_relaunch_count = count
    bot._auth_relaunch_used = used
    # Only re-arm shake when the marker explicitly says so (not merely count).
    bot._shake_after_relaunch = armed
    log.info("auth relaunch state restored shake=%s count=%d used=%s from %s",
             armed, count, used, path)
    return armed


def disarm_shake_keep_count(bot: Any) -> None:
    """After boot shake: keep relaunch budget, drop shake arm on disk."""
    bot._shake_after_relaunch = False
    count = int(getattr(bot, "_auth_relaunch_count", 0) or 0)
    used = bool(getattr(bot, "_auth_relaunch_used", False))
    if count <= 0 and not used:
        clear_auth_relaunch_state(bot)
        return
    base = _base_dir_from_bot(bot)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    path = marker_path(base)
    record = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "saved_ts": time.time(),
        "shake_armed": False,
        "auth_relaunch_count": count,
        "auth_relaunch_used": used,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        log.info("auth relaunch shake disarmed (count=%d kept) -> %s",
                 count, path)
    except OSError as e:
        log.warning("failed to disarm auth relaunch shake: %r", e)


def clear_auth_relaunch_state(bot: Any = None,
                              base_dir: Optional[str] = None) -> None:
    """Remove the marker when login finishes or state is invalid."""
    if bot is not None and base_dir is None:
        base_dir = _base_dir_from_bot(bot)
    path = marker_path(base_dir)
    try:
        if os.path.isfile(path):
            os.remove(path)
            log.info("auth relaunch state cleared (%s)", path)
    except OSError as e:
        log.warning("failed to clear auth relaunch state: %r", e)
