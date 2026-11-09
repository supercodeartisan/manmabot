"""UI dialog open/closed via Engine uidialog_listen."""
from __future__ import annotations

import time
from typing import Any, Optional, Sequence

from app._01_perception.uidialog_listen_reader import (
    UiDialogListenReader,
    shared_uidialog,
)
from app._05_action.uidialog_gate import (
    LABEL_INVENTORY,
    is_open,
    open_labels,
)

LABEL_AMOUNT = "AmountSelector"

__all__ = [
    "LABEL_INVENTORY",
    "LABEL_AMOUNT",
    "read_uidialog",
    "inventory_open",
    "amount_open",
    "wait_open",
    "wait_closed",
    "describe",
]


def read_uidialog(*, reader: Optional[UiDialogListenReader] = None) -> Optional[dict[str, Any]]:
    handle = reader or shared_uidialog()
    if not getattr(handle, "dll_loaded", False):
        return None
    try:
        return handle.snapshot_fresh()
    except Exception:
        return None


def inventory_open(snap: Optional[dict[str, Any]] = None) -> bool:
    return is_open(snap if snap is not None else read_uidialog(), (LABEL_INVENTORY,))


def amount_open(snap: Optional[dict[str, Any]] = None) -> bool:
    return is_open(snap if snap is not None else read_uidialog(), (LABEL_AMOUNT,))


def wait_open(
    labels: Sequence[str],
    *,
    timeout_s: float = 3.0,
    poll_s: float = 0.05,
    force_scan: bool = False,
) -> bool:
    """Wait until any ``labels`` is OPEN.

    ``force_scan=True`` re-runs container discover each poll. Needed for
    short-lived windows (AmountSelector) that are absent from the cached
    instance list until the next ~2s rediscover.
    """
    deadline = time.time() + max(0.0, float(timeout_s))
    handle = shared_uidialog()
    while True:
        snap = None
        if force_scan and getattr(handle, "dll_loaded", False):
            try:
                snap = handle.scan()
            except Exception:
                snap = None
        if snap is None:
            snap = read_uidialog()
        if is_open(snap, labels):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(max(0.01, float(poll_s)))


def wait_closed(
    labels: Sequence[str],
    *,
    timeout_s: float = 3.0,
    poll_s: float = 0.05,
) -> bool:
    deadline = time.time() + max(0.0, float(timeout_s))
    while True:
        snap = read_uidialog()
        if not is_open(snap, labels):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(max(0.01, float(poll_s)))


def describe(snap: Optional[dict[str, Any]] = None) -> str:
    view = snap if snap is not None else read_uidialog()
    if not isinstance(view, dict):
        return "uidialog=unavailable"
    return f"open={open_labels(view)}"
