"""Live-bot logging: one ``manmabot`` logger, session file + optional UI.

Call :func:`configure` once from ``main`` (or Version 1) after the operator
prompts. Layers use :func:`get_logger` with a short channel name
(``session``, ``decision``, ``nav``, ``memory``, ``capture``, ``loop``,
``action``, ``combat``, ``shop``, ``hp``). Scripts and tests keep their own
``print``s.

When ``ui_sink`` is set (V1 schedule/debug log panel), every INFO+ record is
also forwarded there so the on-screen log mirrors the session file.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = "manmabot"

_SESSION_PATH: Optional[Path] = None
_UI_SINK: Optional[Callable[[str], None]] = None

logging.getLogger(ROOT).addHandler(logging.NullHandler())


class _ChannelFilter(logging.Filter):
    """Expose ``record.channel`` as the name without the ``manmabot.`` prefix."""

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        if name == ROOT:
            record.channel = "bot"
        elif name.startswith(ROOT + "."):
            record.channel = name[len(ROOT) + 1 :]
        else:
            record.channel = name
        return True


class _UiSinkHandler(logging.Handler):
    """Forward formatted lines to the operator log panel (thread-safe sink)."""

    def __init__(self, sink: Callable[[str], None], level: int = logging.INFO) -> None:
        super().__init__(level)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._sink(msg)
        except Exception:
            self.handleError(record)


def get_logger(channel: str = "") -> logging.Logger:
    """Return ``manmabot`` or ``manmabot.<channel>``."""
    key = str(channel or "").strip()
    if not key:
        return logging.getLogger(ROOT)
    return logging.getLogger(f"{ROOT}.{key}")


def event(channel: str, msg: str, *args: object) -> None:
    """INFO event for a short channel (decision / combat / loot / …).

    Prefer this for branch outcomes so the Diagnostics panel and session
    file stay aligned. Avoid per-tick spam for unchanged IDLE.
    """
    get_logger(channel).info(msg, *args)


def session_path() -> Optional[Path]:
    """Path of the session file created by the last :func:`configure`."""
    return _SESSION_PATH


def _clear_owned_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if not getattr(handler, "_manmabot", False):
            continue
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def configure(
    *,
    log_dir: Path | str = "logs",
    console: bool = True,
    level: str = "INFO",
    ui_sink: Callable[[str], None] | None = None,
) -> Path:
    """Attach a session file (and optional stdout / UI) to ``manmabot``.

    Idempotent: a second call closes previous owned handlers and opens a new
    file. Returns the session log path.

    ``ui_sink`` receives the same formatted line as the file (without a trailing
    newline). Pass ``BotController._on_log`` (not ``.log``) to avoid recursion
    through the session channel.
    """
    global _SESSION_PATH, _UI_SINK
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"bot-{time.strftime('%Y%m%d-%H%M%S')}.log"

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
    # Shorter line for the on-screen panel (time + channel + message).
    ui_formatter = logging.Formatter(
        "%(asctime)s  [%(channel)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    channel = _ChannelFilter()

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(numeric)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(channel)
    file_handler._manmabot = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    if console and sys.stdout is not None:
        stream = logging.StreamHandler(sys.stdout)
        stream.setLevel(numeric)
        stream.setFormatter(formatter)
        stream.addFilter(channel)
        stream._manmabot = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    _UI_SINK = ui_sink
    if ui_sink is not None:
        ui_handler = _UiSinkHandler(ui_sink, level=numeric)
        ui_handler.setFormatter(ui_formatter)
        ui_handler.addFilter(channel)
        ui_handler._manmabot = True  # type: ignore[attr-defined]
        root.addHandler(ui_handler)

    _SESSION_PATH = path
    return path


def reset() -> None:
    """Drop owned handlers (tests). Does not delete log files."""
    global _SESSION_PATH, _UI_SINK
    root = logging.getLogger(ROOT)
    _clear_owned_handlers(root)
    root.propagate = True
    _SESSION_PATH = None
    _UI_SINK = None


__all__ = [
    "ROOT",
    "get_logger",
    "event",
    "configure",
    "reset",
    "session_path",
]
