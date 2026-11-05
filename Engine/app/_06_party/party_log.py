"""Dedicated party session log — ``Engine/logs/party-YYYYMMDD-HHMMSS.log``.

Separate from the main ``bot-*.log``. Channels (short names in the file):

- ``setup``   — leader leave / ``/초대`` roster
- ``session`` — gate, wait, farm-start, role
- ``member``  — follow / assist / hold decisions
- ``join``    — other-map world-nav / talking-scroll
- ``socket``  — WebSocket frames (and local chat notes)

Call :func:`configure` when party is enabled at bot Start; :func:`reset` on stop.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

ROOT = "manmabot.party"

_SESSION_PATH: Optional[Path] = None

logging.getLogger(ROOT).addHandler(logging.NullHandler())


class _ChannelFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name == ROOT:
            record.channel = "party"
        elif name.startswith(ROOT + "."):
            record.channel = name[len(ROOT) + 1 :]
        else:
            record.channel = name
        return True


def get_logger(channel: str = "") -> logging.Logger:
    """Return ``manmabot.party`` or ``manmabot.party.<channel>``."""
    key = str(channel or "").strip()
    if not key:
        return logging.getLogger(ROOT)
    return logging.getLogger(f"{ROOT}.{key}")


def event(channel: str, msg: str, *args: object) -> None:
    """INFO line on a party channel (setup / session / member / join / socket)."""
    get_logger(channel).info(msg, *args)


def session_path() -> Optional[Path]:
    return _SESSION_PATH


def active() -> bool:
    return _SESSION_PATH is not None


def _clear_owned_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if not getattr(handler, "_party_log", False):
            continue
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def configure(
    *,
    log_dir: Path | str = "logs",
    level: str = "INFO",
    role: str = "",
) -> Path:
    """Open a new ``party-*.log``. Idempotent — replaces the previous file handler."""
    global _SESSION_PATH
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"party-{time.strftime('%Y%m%d-%H%M%S')}.log"

    numeric = getattr(logging, str(level).upper(), None)
    if not isinstance(numeric, int):
        numeric = logging.INFO

    root = logging.getLogger(ROOT)
    root.setLevel(numeric)
    _clear_owned_handlers(root)
    root.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d  %(levelname)-5s  %(channel)-10s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    channel = _ChannelFilter()
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(numeric)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(channel)
    file_handler._party_log = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    _SESSION_PATH = path
    role_txt = str(role or "").strip() or "—"
    get_logger("session").info(
        "party log open role=%s file=%s",
        role_txt,
        path.name,
    )
    return path


def reset() -> None:
    """Drop the party file handler (bot Stop / tests). Does not delete files."""
    global _SESSION_PATH
    root = logging.getLogger(ROOT)
    if _SESSION_PATH is not None:
        try:
            get_logger("session").info("party log close file=%s", _SESSION_PATH.name)
        except Exception:
            pass
    _clear_owned_handlers(root)
    root.propagate = True
    _SESSION_PATH = None


__all__ = [
    "ROOT",
    "active",
    "configure",
    "event",
    "get_logger",
    "reset",
    "session_path",
]
