"""UI dialog open gate + unexpected-window helpers (uidialogmon).

Polls ``PerceptionSensors.capture_uidialog`` until a watched label is OPEN
(timeout default 3s), or lists unexpected open windows for Esc dismiss.
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Optional, Sequence

# Registry labels (UIDLG_WIN_*).
LABEL_NPC_DIALOG = "NPCDialog"
LABEL_NPC_SHOP = "NPCShop"
LABEL_NPC_STORAGE = "NPCStorage"
LABEL_INVENTORY = "Inventory"
LABEL_TALKING_SCROLL = "TalkingScroll"

WATCHED_LABELS: tuple[str, ...] = (
    LABEL_NPC_DIALOG,
    LABEL_NPC_SHOP,
    LABEL_NPC_STORAGE,
    LABEL_INVENTORY,
    LABEL_TALKING_SCROLL,
)

# After NPC click / scroll key: wait this long for OPEN before next input.
UIDIALOG_OPEN_TIMEOUT_S = 3.0
UIDIALOG_POLL_S = 0.05


def open_labels(snap: Optional[dict[str, Any]]) -> list[str]:
    """Labels currently OPEN from a uidialog snapshot."""
    if not isinstance(snap, dict):
        return []
    raw = snap.get("open")
    if isinstance(raw, list):
        out = [str(x) for x in raw if x]
        if out:
            return out
    windows = snap.get("windows")
    if isinstance(windows, dict):
        return [str(k) for k, v in windows.items() if v]
    return []


def is_open(snap: Optional[dict[str, Any]], labels: Sequence[str]) -> bool:
    """True if any of ``labels`` is OPEN."""
    if not labels:
        return False
    want = {str(x) for x in labels}
    return any(lbl in want for lbl in open_labels(snap))


def expected_labels_for_shop_kind(kind: str) -> tuple[str, ...]:
    """Window labels that mean the shop/storage/teleporter dialog is ready."""
    k = str(kind or "").strip().lower()
    if k == "store":
        return (LABEL_NPC_STORAGE, LABEL_NPC_SHOP, LABEL_NPC_DIALOG)
    if k == "teleporter":
        return (LABEL_NPC_DIALOG, LABEL_NPC_SHOP)
    # buy / sell / default merchant UI
    return (LABEL_NPC_SHOP, LABEL_NPC_DIALOG)


def unexpected_open_labels(
    snap: Optional[dict[str, Any]],
    *,
    allowed: Iterable[str] = (),
) -> list[str]:
    """OPEN watched windows not in ``allowed`` (misclick / stray UI)."""
    allow = {str(x) for x in allowed}
    return [lbl for lbl in open_labels(snap) if lbl not in allow]


def read_uidialog_snap() -> Optional[dict[str, Any]]:
    """Fresh uidialog snapshot via shared sensors (None if DLL missing)."""
    try:
        from app._01_perception.sensors import shared_sensors

        return shared_sensors().capture_uidialog()
    except Exception:
        return None


def wait_uidialog_open(
    labels: Sequence[str],
    *,
    timeout_s: float = UIDIALOG_OPEN_TIMEOUT_S,
    poll_s: float = UIDIALOG_POLL_S,
) -> bool:
    """Poll until any of ``labels`` is OPEN, or ``timeout_s`` elapses."""
    if not labels:
        return False
    deadline = time.time() + max(0.0, float(timeout_s))
    interval = max(0.01, float(poll_s))
    while True:
        if is_open(read_uidialog_snap(), labels):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(interval)


__all__ = [
    "LABEL_NPC_DIALOG",
    "LABEL_NPC_SHOP",
    "LABEL_NPC_STORAGE",
    "LABEL_INVENTORY",
    "LABEL_TALKING_SCROLL",
    "WATCHED_LABELS",
    "UIDIALOG_OPEN_TIMEOUT_S",
    "UIDIALOG_POLL_S",
    "open_labels",
    "is_open",
    "expected_labels_for_shop_kind",
    "unexpected_open_labels",
    "read_uidialog_snap",
    "wait_uidialog_open",
]
