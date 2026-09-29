"""Calibrated shop-sell list slot boxes (template-match regions for row 0..6)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from manmabot_v1.paths import USERDATA, VERSION1_ROOT, ensure_userdata
from manmabot_v1.shopping.behaviors import ITEM_ROW_COUNT

SELL_SLOT_KEYS: tuple[str, ...] = tuple(f"row_{i}" for i in range(ITEM_ROW_COUNT))

USERDATA_LAYOUT_PATH = USERDATA / "shop_sell_slot_layout.json"
USERDATA_UI_PREFS_PATH = USERDATA / "shop_sell_ui_prefs.json"
DEBUG_LAYOUT_PATH = (
    VERSION1_ROOT / "debug_tools" / "output" / "shop_sell_slot_layout.json"
)


def layout_search_paths() -> tuple[Path, ...]:
    return (USERDATA_LAYOUT_PATH, DEBUG_LAYOUT_PATH)


def default_sell_slot_layout() -> dict[str, dict[str, float]]:
    """Uniform vertical stack of icon boxes (frame-normalized), shop-list left column."""
    # Seeded near typical Behaviors item_row click UVs; icons sit slightly left of names.
    slots: dict[str, dict[str, float]] = {}
    for i, key in enumerate(SELL_SLOT_KEYS):
        cy = 0.088 + i * 0.0675
        cx = 0.14
        half_w, half_h = 0.028, 0.026
        slots[key] = {
            "x0": max(0.0, cx - half_w),
            "y0": max(0.0, cy - half_h),
            "x1": min(1.0, cx + half_w),
            "y1": min(1.0, cy + half_h),
        }
    return slots


def _parse_slots(data: dict[str, Any]) -> dict[str, dict[str, float]] | None:
    slots = data.get("slots") or {}
    out: dict[str, dict[str, float]] = {}
    for key in SELL_SLOT_KEYS:
        box = slots.get(key)
        if not isinstance(box, dict):
            return None
        try:
            x0, y0 = float(box["x0"]), float(box["y0"])
            x1, y1 = float(box["x1"]), float(box["y1"])
        except (KeyError, TypeError, ValueError):
            return None
        if x1 <= x0 or y1 <= y0:
            return None
        out[key] = {
            "x0": max(0.0, min(1.0, x0)),
            "y0": max(0.0, min(1.0, y0)),
            "x1": max(0.0, min(1.0, x1)),
            "y1": max(0.0, min(1.0, y1)),
        }
    return out


def load_sell_slot_layout(
    path: Optional[Path] = None,
) -> dict[str, dict[str, float]] | None:
    """Load calibrated sell slots, or None if missing/invalid."""
    paths = (path,) if path is not None else layout_search_paths()
    for candidate in paths:
        if candidate is None or not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            parsed = _parse_slots(data)
            if parsed is not None:
                return parsed
        except Exception:
            continue
    return None


def save_sell_slot_layout(
    slots: dict[str, dict[str, float]],
    *,
    frame_w: int,
    frame_h: int,
) -> Path:
    """Write layout to userdata and mirror under debug_tools/output."""
    ensure_userdata()
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "frame_w": int(frame_w),
        "frame_h": int(frame_h),
        "slots": {
            key: {
                "x0": float(slots[key]["x0"]),
                "y0": float(slots[key]["y0"]),
                "x1": float(slots[key]["x1"]),
                "y1": float(slots[key]["y1"]),
            }
            for key in SELL_SLOT_KEYS
            if key in slots
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    USERDATA_LAYOUT_PATH.write_text(text, encoding="utf-8")
    try:
        DEBUG_LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_LAYOUT_PATH.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return USERDATA_LAYOUT_PATH


def slot_key_for_index(index: int) -> str:
    i = max(0, min(ITEM_ROW_COUNT - 1, int(index)))
    return SELL_SLOT_KEYS[i]


def load_last_sell_category(*, default: str = "other") -> str:
    """Last category chosen in Save slot crop (persisted in userdata)."""
    from manmabot_v1.hotbar.item_catalog import SELL_CATEGORIES

    path = USERDATA_UI_PREFS_PATH
    if not path.is_file():
        return default if default in SELL_CATEGORIES else "other"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default if default in SELL_CATEGORIES else "other"
    cat = str((data or {}).get("last_category") or "").strip()
    if cat in SELL_CATEGORIES:
        return cat
    return default if default in SELL_CATEGORIES else "other"


def save_last_sell_category(category: str) -> None:
    """Remember category for the next Save slot crop dialog."""
    from manmabot_v1.hotbar.item_catalog import SELL_CATEGORIES

    cat = str(category or "").strip()
    if cat not in SELL_CATEGORIES:
        return
    ensure_userdata()
    data: dict[str, Any] = {}
    if USERDATA_UI_PREFS_PATH.is_file():
        try:
            loaded = json.loads(USERDATA_UI_PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data["last_category"] = cat
    USERDATA_UI_PREFS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


__all__ = [
    "SELL_SLOT_KEYS",
    "USERDATA_LAYOUT_PATH",
    "USERDATA_UI_PREFS_PATH",
    "DEBUG_LAYOUT_PATH",
    "default_sell_slot_layout",
    "load_sell_slot_layout",
    "save_sell_slot_layout",
    "slot_key_for_index",
    "layout_search_paths",
    "load_last_sell_category",
    "save_last_sell_category",
]
