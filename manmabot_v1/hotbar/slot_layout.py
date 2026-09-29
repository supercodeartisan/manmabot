"""Calibrated F5–F12 hotbar slot layout (shared by matcher + inspector)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from manmabot_v1.paths import USERDATA, VERSION1_ROOT, ensure_userdata
from manmabot_v1.spell_defaults import SKILL_KEYS

SLOT_KEYS = tuple(k.upper() for k in SKILL_KEYS)

# Canonical path used by the live bot / IconMatcher.
USERDATA_LAYOUT_PATH = USERDATA / "hotbar_slot_layout.json"
# Inspector also mirrors here for debug snapshots.
DEBUG_LAYOUT_PATH = VERSION1_ROOT / "debug_tools" / "output" / "hotbar_slot_layout.json"


def layout_search_paths() -> tuple[Path, ...]:
    return (USERDATA_LAYOUT_PATH, DEBUG_LAYOUT_PATH)


def default_slot_layout(
    frame_w: int = 0,
    frame_h: int = 0,
    *,
    hotbar_region: tuple[float, float, float, float] | None = None,
) -> dict[str, dict[str, float]]:
    """Uniform 2×4 grid inside the hotbar crop, as frame-normalized boxes."""
    from manmabot_v1.hotbar.icon_matcher import REGION

    x0_r, x1_r, y0_r, y1_r = hotbar_region or REGION["hotbar"]
    rows, cols = 2, 4
    slots: dict[str, dict[str, float]] = {}
    for r in range(rows):
        for c in range(cols):
            key = f"F{5 + r * cols + c}"
            slots[key] = {
                "x0": x0_r + (x1_r - x0_r) * (c / cols),
                "y0": y0_r + (y1_r - y0_r) * (r / rows),
                "x1": x0_r + (x1_r - x0_r) * ((c + 1) / cols),
                "y1": y0_r + (y1_r - y0_r) * ((r + 1) / rows),
            }
    return slots


def _parse_slots(data: dict[str, Any]) -> dict[str, dict[str, float]] | None:
    slots = data.get("slots") or {}
    out: dict[str, dict[str, float]] = {}
    for key in SLOT_KEYS:
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


def load_slot_layout(path: Path | None = None) -> dict[str, dict[str, float]] | None:
    """Load calibrated slots, or None if missing/invalid.

    Prefer ``userdata/hotbar_slot_layout.json``, then the debug_tools copy.
    """
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


def save_slot_layout(
    slots: dict[str, dict[str, float]],
    *,
    frame_w: int,
    frame_h: int,
) -> Path:
    """Write layout to userdata (live bot) and mirror under debug_tools/output."""
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
            for key in SLOT_KEYS
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


def slots_bounding_region(
    slots: dict[str, dict[str, float]],
    *,
    pad: float = 0.01,
) -> tuple[float, float, float, float]:
    """Normalized (x0, x1, y0, y1) covering all slots."""
    xs0 = [b["x0"] for b in slots.values()]
    xs1 = [b["x1"] for b in slots.values()]
    ys0 = [b["y0"] for b in slots.values()]
    ys1 = [b["y1"] for b in slots.values()]
    return (
        max(0.0, min(xs0) - pad),
        min(1.0, max(xs1) + pad),
        max(0.0, min(ys0) - pad),
        min(1.0, max(ys1) + pad),
    )


def fkey_for_point(
    nx: float,
    ny: float,
    slots: dict[str, dict[str, float]],
) -> str | None:
    """Return F-key whose calibrated box contains normalized point (nx, ny)."""
    for key in SLOT_KEYS:
        box = slots.get(key)
        if box is None:
            continue
        if box["x0"] <= nx <= box["x1"] and box["y0"] <= ny <= box["y1"]:
            return key
    return None


__all__ = [
    "SLOT_KEYS",
    "USERDATA_LAYOUT_PATH",
    "DEBUG_LAYOUT_PATH",
    "default_slot_layout",
    "load_slot_layout",
    "save_slot_layout",
    "slots_bounding_region",
    "fkey_for_point",
    "layout_search_paths",
]
