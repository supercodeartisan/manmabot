"""Load calibrated 8x4 slot + scroll points; scale to the live 4:3 content."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app._05_action.content_crop import ContentRect, compute_43_crop

ROWS = 8
COLS = 4


def default_grid_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "Engine" / "data" / "supply" / "inventory_grid.json"


@dataclass(frozen=True)
class SupplyGrid:
    """Client-pixel centers for the inventory grid and scrollbar arrows."""

    slots: list[tuple[int, int]]  # row-major 32
    scroll_up: tuple[int, int]
    scroll_down: tuple[int, int]
    ref_width: int
    ref_height: int

    def slot_xy(self, list_index_1based: int) -> tuple[int, int]:
        idx = int(list_index_1based) - 1
        if idx < 0 or idx >= len(self.slots):
            raise IndexError(f"list_index out of range: {list_index_1based}")
        return self.slots[idx]


def _content_uv(x: float, y: float, rect: ContentRect) -> tuple[float, float]:
    return (float(x) - rect.left) / rect.width, (float(y) - rect.top) / rect.height


def _from_uv(u: float, v: float, rect: ContentRect) -> tuple[int, int]:
    return (
        int(round(rect.left + u * rect.width)),
        int(round(rect.top + v * rect.height)),
    )


def load_grid(path: Optional[Path] = None) -> dict:
    target = Path(path or default_grid_path())
    return json.loads(target.read_text(encoding="utf-8"))


def scale_grid_to_client(
    client_w: int,
    client_h: int,
    *,
    path: Optional[Path] = None,
) -> SupplyGrid:
    """Map reference screenshot pixels onto the live client via 4:3 crop UV."""
    data = load_grid(path)
    ref_w = int(data.get("image_width") or 0)
    ref_h = int(data.get("image_height") or 0)
    if ref_w <= 0 or ref_h <= 0:
        raise ValueError("inventory_grid.json missing image_width/height")
    ref_rect = compute_43_crop(ref_w, ref_h)
    live_rect = compute_43_crop(int(client_w), int(client_h))

    slots: list[tuple[int, int]] = []
    raw_slots = data.get("slots") or []
    if len(raw_slots) != ROWS * COLS:
        raise ValueError(f"expected {ROWS * COLS} slots, got {len(raw_slots)}")
    by_row: dict[int, list[dict]] = {}
    for row in raw_slots:
        by_row.setdefault(int(row["row"]), []).append(row)
    for r in range(1, ROWS + 1):
        cells = sorted(by_row.get(r, []), key=lambda s: int(s["x"]))
        if len(cells) != COLS:
            raise ValueError(f"row {r} needs {COLS} cells")
        for cell in cells:
            u, v = _content_uv(int(cell["x"]), int(cell["y"]), ref_rect)
            slots.append(_from_uv(u, v, live_rect))

    up = data.get("scroll_up_position") or [0, 0]
    down = data.get("scroll_down_position") or [0, 0]
    uu, uv = _content_uv(int(up[0]), int(up[1]), ref_rect)
    du, dv = _content_uv(int(down[0]), int(down[1]), ref_rect)
    return SupplyGrid(
        slots=slots,
        scroll_up=_from_uv(uu, uv, live_rect),
        scroll_down=_from_uv(du, dv, live_rect),
        ref_width=ref_w,
        ref_height=ref_h,
    )
