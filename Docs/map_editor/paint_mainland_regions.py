"""Paint every map4 region onto a copy of the mainland nav image.

Live walkability stays ``Engine/data/maps/mainland/nav.png``.
The colored copy is written under ``Docs/map_editor``.

Thin rows are the shared borders. Their enclosed land is filled per region
name. Thicker rows are the rectangle areas (towns, castles, nests, strips)
and are filled on top, each name-pair in its own light color.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
TSV = ROOT / "map4_boundaries.tsv"
SRC = ROOT / "Engine" / "data" / "maps" / "mainland" / "nav.png"
OUT_DIR = ROOT / "Docs" / "map_editor"
OUT_PNG = OUT_DIR / "mainland_region_overlay.png"
OUT_LEGEND = OUT_DIR / "mainland_region_overlay_legend.json"

ORIGIN_X = 32448
ORIGIN_Y = 32128
PIXEL_SCALE = 4
HAIRLINE = 4
FILL_ALPHA = 88


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    c = (1 - abs(2 * l - 1)) * s
    hp = (h % 360.0) / 60.0
    x = c * (1 - abs(hp % 2 - 1))
    if hp < 1:
        r, g, b = c, x, 0.0
    elif hp < 2:
        r, g, b = x, c, 0.0
    elif hp < 3:
        r, g, b = 0.0, c, x
    elif hp < 4:
        r, g, b = 0.0, x, c
    elif hp < 5:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    m = l - c / 2
    return (int(round((r + m) * 255)), int(round((g + m) * 255)), int(round((b + m) * 255)))


def _color(index: int, total: int) -> tuple[int, int, int, int]:
    hue = (index * 360.0 / max(1, total)) % 360.0
    r, g, b = _hsl_to_rgb(hue, 0.48, 0.58)
    return (r, g, b, FILL_ALPHA)


def _box(row: dict[str, str]) -> tuple[int, int, int, int]:
    return (
        int(row["x_min"]),
        int(row["y_min"]),
        int(row["x_max"]),
        int(row["y_max"]),
    )


def _area(box: tuple[int, int, int, int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _load_rows() -> list[dict[str, str]]:
    with TSV.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _label_land(rows: list[dict[str, str]], nav_l: np.ndarray) -> tuple[np.ndarray, dict[int, str]]:
    gh, gw = nav_l.shape[0] // PIXEL_SCALE, nav_l.shape[1] // PIXEL_SCALE
    land = nav_l.reshape(gh, PIXEL_SCALE, gw, PIXEL_SCALE).mean(axis=(1, 3)) > 40
    blocked = np.zeros((gh, gw), dtype=bool)
    thin: list[tuple[tuple[int, int, int, int], str, str]] = []
    for row in rows:
        box = _box(row)
        w, h = box[2] - box[0], box[3] - box[1]
        ix0 = max(0, min(gw, box[0] - ORIGIN_X))
        iy0 = max(0, min(gh, box[1] - ORIGIN_Y))
        ix1 = max(0, min(gw, (box[2] if box[2] > box[0] else box[0] + 1) - ORIGIN_X))
        iy1 = max(0, min(gh, (box[3] if box[3] > box[1] else box[1] + 1) - ORIGIN_Y))
        if ix1 > ix0 and iy1 > iy0:
            blocked[iy0:iy1, ix0:ix1] = True
        if min(max(w, 0), max(h, 0)) <= HAIRLINE:
            thin.append((box, row["nameA"], row["nameB"]))

    open_land = land & ~blocked
    labels = np.zeros((gh, gw), dtype=np.int32)
    comp = 0
    for y in range(gh):
        for x in range(gw):
            if not open_land[y, x] or labels[y, x]:
                continue
            comp += 1
            q = deque([(y, x)])
            labels[y, x] = comp
            while q:
                cy, cx = q.popleft()
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if (
                        0 <= ny < gh
                        and 0 <= nx < gw
                        and open_land[ny, nx]
                        and labels[ny, nx] == 0
                    ):
                        labels[ny, nx] = comp
                        q.append((ny, nx))

    def sides(box: tuple[int, int, int, int]) -> tuple[int, int]:
        x0, y0, x1, y1 = box
        mx, my = (max(x0, x1 - 1) + x0) // 2, (max(y0, y1 - 1) + y0) // 2

        def first_land(dx: int, dy: int, ox: int, oy: int) -> int:
            wx, wy = ox, oy
            for _ in range(40):
                wx += dx
                wy += dy
                ix, iy = wx - ORIGIN_X, wy - ORIGIN_Y
                if not (0 <= iy < gh and 0 <= ix < gw):
                    return 0
                comp_id = int(labels[iy, ix])
                if comp_id:
                    return comp_id
            return 0

        if (y1 - y0) <= (x1 - x0):
            return (first_land(0, -1, mx, min(y0, y1)), first_land(0, 1, mx, max(y0, y1) - 1))
        return (first_land(-1, 0, min(x0, x1), my), first_land(1, 0, max(x0, x1) - 1, my))

    votes: dict[int, Counter[str]] = defaultdict(Counter)
    for box, name_a, name_b in thin:
        weight = max(box[2] - box[0], box[3] - box[1], 1)
        c1, c2 = sides(box)
        names = (name_a,) if name_a == name_b else (name_a, name_b)
        for comp_id in (c1, c2):
            if not comp_id:
                continue
            for name in names:
                votes[comp_id][name] += weight

    name_of: dict[int, str] = {}
    for comp_id, tally in votes.items():
        ranking = tally.most_common(2)
        if len(ranking) == 1 or ranking[0][1] > ranking[1][1]:
            name_of[comp_id] = ranking[0][0]
    return labels, name_of


def main() -> None:
    rows = _load_rows()
    nav = Image.open(SRC).convert("RGB")
    nav_l = np.asarray(Image.open(SRC).convert("L"))
    labels, name_of = _label_land(rows, nav_l)

    territory_names = sorted(set(name_of.values()))
    pair_keys = sorted({(row["nameA"], row["nameB"]) for row in rows if _area(_box(row)) > HAIRLINE * HAIRLINE or min(_box(row)[2] - _box(row)[0], _box(row)[3] - _box(row)[1]) > HAIRLINE})
    # Colors: territories and rectangle-pairs share one palette, pairs offset
    # so a town does not reuse its parent field color.
    palette_names = territory_names + [f"{a} | {b}" for a, b in pair_keys]
    total = len(palette_names)
    palette = {name: _color(i, total) for i, name in enumerate(palette_names)}

    gh, gw = labels.shape
    index = np.zeros((gh, gw), dtype=np.int16)
    territory_ids = {name: i + 1 for i, name in enumerate(territory_names)}
    for comp, name in name_of.items():
        index[labels == comp] = territory_ids[name]
    index_img = np.repeat(np.repeat(index, PIXEL_SCALE, axis=0), PIXEL_SCALE, axis=1)

    overlay = np.zeros((nav_l.shape[0], nav_l.shape[1], 4), dtype=np.uint8)
    for name, idx in territory_ids.items():
        overlay[index_img == idx] = palette[name]

    overlay_im = Image.fromarray(overlay, mode="RGBA")
    draw = ImageDraw.Draw(overlay_im)
    paints: list[dict] = []
    for row in rows:
        box = _box(row)
        w, h = box[2] - box[0], box[3] - box[1]
        if min(max(w, 0), max(h, 0)) <= HAIRLINE:
            continue
        paints.append(
            {
                "name_a": row["nameA"],
                "name_b": row["nameB"],
                "label": f"{row['nameA']} | {row['nameB']}",
                "world": list(box),
                "area": _area(box),
                "rgba": list(palette[f"{row['nameA']} | {row['nameB']}"]),
            }
        )
    paints.sort(key=lambda item: item["area"], reverse=True)
    img_w, img_h = nav.size
    for item in paints:
        x0, y0, x1, y1 = item["world"]
        px0, py0 = (x0 - ORIGIN_X) * PIXEL_SCALE, (y0 - ORIGIN_Y) * PIXEL_SCALE
        px1, py1 = (x1 - ORIGIN_X) * PIXEL_SCALE, (y1 - ORIGIN_Y) * PIXEL_SCALE
        left, top = max(0, px0), max(0, py0)
        right, bottom = min(img_w - 1, px1 - 1), min(img_h - 1, py1 - 1)
        if right < left or bottom < top:
            item["pixels"] = None
            continue
        draw.rectangle((left, top, right, bottom), fill=tuple(item["rgba"]))
        item["pixels"] = [left, top, right + 1, bottom + 1]

    composed = Image.alpha_composite(nav.convert("RGBA"), overlay_im).convert("RGB")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    composed.save(OUT_PNG, optimize=True)

    territories = []
    for name in territory_names:
        cells = int((index == territory_ids[name]).sum())
        territories.append(
            {
                "name": name,
                "land_cells": cells,
                "rgba": list(palette[name]),
            }
        )
    legend = {
        "source_image": "Engine/data/maps/mainland/nav.png",
        "output_image": "Docs/map_editor/mainland_region_overlay.png",
        "origin_xy": [ORIGIN_X, ORIGIN_Y],
        "pixel_scale": PIXEL_SCALE,
        "fill_alpha": FILL_ALPHA,
        "note": (
            "Copy of mainland nav.png. Enclosed land of every bordered region "
            "is filled, then every thicker TSV rectangle is filled on top."
        ),
        "territories": territories,
        "rectangles": paints,
    }
    OUT_LEGEND.write_text(json.dumps(legend, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"territories {len(territories)} rectangles {len(paints)} -> {OUT_PNG} {composed.size}"
    )


if __name__ == "__main__":
    main()
