"""Mainland region overlay for the map editor.

``map4_boundaries.tsv`` is in game-world coordinates. The mainland pack
stores nav tiles relative to ``origin_x/y``. The tint covers only the
large fields (켄트, 하이네, 오렌, 오크 숲, and the rest of
``_MAIN_REGIONS``). 오렌 includes the snow wall. 화룡의 둥지 is drawn
from its own rectangle. Village footprints use the surrounding field
color, and their names are not drawn.

The walkability image is left unchanged. This overlay is drawn on top
while an area is being edited.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from i18n.localized_names import mainland_region_display

HAIRLINE = 4
FILL_ALPHA = 72

# Large fields that get a tint and a name.
_MAIN_REGIONS = frozenset({
    "글루디오",
    "켄트",
    "윈다우드",
    "은기사 지역",
    "기란",
    "아덴",
    "하이네",
    "오렌",
    "요정 숲",
    "오크 숲",
    "용의 계곡",
    "화룡의 둥지",
})
# 오렌 is the town field plus the snow wall. The wind-dragon nest,
# Elmore battlefield, and border fortress stay outside it.
_REGION_FOLD = {
    "기란 추가": "기란",
    "오렌 추가": "오렌",
    "오렌 설벽": "오렌",
}
# Drawn from their own rectangle. They have no thin border of their own.
_NAMED_RECTS = frozenset({"화룡의 둥지"})


def _vote_name(name: str) -> str:
    """Region name used when assigning land. Unknown names stay themselves."""
    return _REGION_FOLD.get(name, name)


def _main_region(name: str) -> str:
    folded = _vote_name(name)
    return folded if folded in _MAIN_REGIONS else ""


def _village_label(name_a: str, name_b: str) -> str:
    for name in (name_b, name_a):
        if str(name).endswith("마을"):
            return name
    return ""


def _area_name(name_a: str, name_b: str) -> str:
    """Main field a village rectangle sits in, when the row names it."""
    for name in (name_a, name_b):
        if str(name).endswith("마을"):
            continue
        main = _main_region(name)
        if main:
            return main
    return ""


_BUTTON = {
    "ko": "지역 경계",
    "zh": "区域边界",
    "en": "Region borders",
}


def region_button_text(language: str) -> str:
    code = str(language or "en").lower()
    if code.startswith("ko"):
        return _BUTTON["ko"]
    if code.startswith("zh"):
        return _BUTTON["zh"]
    return _BUTTON["en"]


def _find_tsv(pack_root: Path) -> Path | None:
    from session.paths import app_root

    candidates = (
        Path(pack_root) / "map4_boundaries.tsv",
        app_root() / "map4_boundaries.tsv",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _hsl_to_rgb(hue: float, sat: float, light: float) -> tuple[int, int, int]:
    c = (1 - abs(2 * light - 1)) * sat
    hp = (hue % 360.0) / 60.0
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
    m = light - c / 2
    return (
        int(round((r + m) * 255)),
        int(round((g + m) * 255)),
        int(round((b + m) * 255)),
    )


def _color_for(index: int, total: int, alpha: int) -> tuple[int, int, int, int]:
    hue = (index * 137.508) % 360.0
    r, g, b = _hsl_to_rgb(hue, 0.46, 0.62)
    return r, g, b, alpha


@dataclass(frozen=True)
class _Place:
    name: str
    parent: str
    x0: int
    y0: int
    x1: int
    y1: int
    rgba: tuple[int, int, int, int]

    @property
    def area(self) -> int:
        return max(0, self.x1 - self.x0) * max(0, self.y1 - self.y0)


@dataclass(frozen=True)
class _RegionLabel:
    name: str
    cx: float
    cy: float
    x0: int
    y0: int
    x1: int
    y1: int


class MainlandRegionOverlay:
    def __init__(
        self,
        *,
        image: QImage,
        names: list[str],
        label_grid,
        borders: list[tuple[float, float, float, float]],
        places: list[_Place],
        regions: list[_RegionLabel],
        pixels=None,
        language: str = "ko",
    ) -> None:
        self.image = image
        self._pixels = pixels
        self.language = language
        self._names = names
        self._grid = label_grid
        self.borders = borders
        self.places = places
        self.regions = regions
        self._label_cache: dict[str, str] = {}

    def region_at(self, tx: int, ty: int) -> str:
        grid = self._grid
        if grid is None:
            return ""
        gh, gw = grid.shape
        if not (0 <= ty < gh and 0 <= tx < gw):
            return ""
        idx = int(grid[ty, tx])
        if idx <= 0 or idx >= len(self._names):
            return ""
        return self._names[idx]

    def place_at(self, tx: int, ty: int) -> _Place | None:
        hit: _Place | None = None
        best = 10**12
        for place in self.places:
            if place.x0 <= tx < place.x1 and place.y0 <= ty < place.y1:
                if place.area < best:
                    best = place.area
                    hit = place
        return hit

    def hover_text(self, tx: int, ty: int) -> str:
        place = self.place_at(tx, ty)
        region = self.region_at(tx, ty)
        if place is not None and not region:
            region = place.parent
        place_name = "" if place is None else place.name
        if place_name and region and place_name != region:
            return f"{self._label(region)} · {self._label(place_name)}"
        return self._label(place_name or region)

    def _label(self, name: str) -> str:
        cached = self._label_cache.get(name)
        if cached is None:
            cached = mainland_region_display(name, self.language)
            self._label_cache[name] = cached
        return cached

    def paint(
        self,
        painter: QPainter,
        *,
        origin: tuple[float, float],
        scale: float,
        pixel_scale: int,
        tile_to_canvas,
        view_w: int,
        view_h: int,
        hover_tile: tuple[int, int] | None = None,
        pointer: tuple[float, float] | None = None,
    ) -> None:
        ox, oy = origin
        ps = max(1, int(pixel_scale))
        tile_px = ps * scale
        draw_visible_image(
            painter, self.image, ox, oy, tile_px, view_w, view_h
        )
        hover_place = None
        hover_region = ""
        if hover_tile is not None:
            hover_place = self.place_at(hover_tile[0], hover_tile[1])
            hover_region = self.region_at(hover_tile[0], hover_tile[1])
            if hover_place is not None and not hover_region:
                hover_region = hover_place.parent

        if tile_px >= 1.35:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 248, 220, 210), 1.25))
            for x0, y0, x1, y1 in self.borders:
                ax0, ay0 = tile_to_canvas(x0, y0)
                ax1, ay1 = tile_to_canvas(x1, y1)
                if max(ax0, ax1) < 0 or min(ax0, ax1) > view_w:
                    continue
                if max(ay0, ay1) < 0 or min(ay0, ay1) > view_h:
                    continue
                painter.drawLine(QPointF(ax0, ay0), QPointF(ax1, ay1))

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = painter.clipBoundingRect()
        if not clip.isValid() or clip.isEmpty():
            clip = QRectF(0, 0, view_w, view_h)
        taken: list[QRectF] = []
        place_font = QFont("", 9)
        region_font = QFont("", 11, QFont.Weight.DemiBold)
        for place in self.places:
            cx, cy = tile_to_canvas(
                (place.x0 + place.x1) / 2.0,
                (place.y0 + place.y1) / 2.0,
            )
            if cx < clip.left() - 40 or cy < clip.top() - 20 or cx > clip.right() + 40 or cy > clip.bottom() + 20:
                continue
            hot = hover_place is not None and (
                place.x0 == hover_place.x0 and place.y0 == hover_place.y0
            )
            painter.setFont(place_font)
            _place_label(
                painter,
                taken,
                clip,
                cx,
                cy,
                self._label(place.name),
                fill=QColor(15, 23, 42, 230 if hot else 188),
                outline=QColor(255, 248, 220, 240) if hot else None,
                center=True,
                force=True,
            )
        painter.setFont(region_font)
        hot_label: tuple[float, float, str] | None = None
        for region in self.regions:
            cx, cy = tile_to_canvas(region.cx, region.cy)
            hot = bool(hover_region) and region.name == hover_region
            if hot:
                hot_label = (cx, cy, region.name)
                continue
            if cx < clip.left() - 40 or cy < clip.top() - 20 or cx > clip.right() + 40 or cy > clip.bottom() + 20:
                continue
            _place_label(
                painter,
                taken,
                clip,
                cx,
                cy,
                self._label(region.name),
                fill=QColor(15, 23, 42, 150),
                center=True,
                force=True,
            )
        if hot_label is not None:
            cx, cy, name = hot_label
            painter.setFont(region_font)
            _place_label(
                painter,
                taken,
                clip,
                cx,
                cy,
                self._label(name),
                fill=QColor(15, 23, 42, 235),
                center=True,
                outline=QColor(255, 248, 220, 240),
                force=True,
            )
        if pointer is not None and (hover_region or hover_place is not None):
            place_name = "" if hover_place is None else hover_place.name
            if place_name and hover_region and place_name != hover_region:
                caption = f"{self._label(hover_region)}  ·  {self._label(place_name)}"
            else:
                caption = self._label(place_name or hover_region)
            painter.setFont(place_font)
            _chip(painter, pointer[0], pointer[1], caption, view_w, view_h)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)


def draw_visible_image(
    painter: QPainter,
    image: QImage,
    ox: float,
    oy: float,
    scale: float,
    view_w: int,
    view_h: int,
) -> None:
    """Blit only the part of ``image`` inside the current clip (or the canvas)."""
    if image.isNull() or scale <= 1e-6:
        return
    clip = painter.clipBoundingRect()
    if not clip.isValid() or clip.isEmpty():
        clip = QRectF(0, 0, view_w, view_h)
    iw, ih = image.width(), image.height()
    sx0 = max(0, int((clip.left() - ox) / scale))
    sy0 = max(0, int((clip.top() - oy) / scale))
    sx1 = min(iw, int((clip.right() - ox) / scale) + 2)
    sy1 = min(ih, int((clip.bottom() - oy) / scale) + 2)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    painter.drawImage(
        QRectF(
            ox + sx0 * scale,
            oy + sy0 * scale,
            (sx1 - sx0) * scale,
            (sy1 - sy0) * scale,
        ),
        image,
        QRectF(float(sx0), float(sy0), float(sx1 - sx0), float(sy1 - sy0)),
    )


def _fits(rect: QRectF, taken: list[QRectF], clip: QRectF) -> bool:
    if not rect.intersects(clip):
        return False
    return not any(rect.intersects(other) for other in taken)


def _place_label(
    painter: QPainter,
    taken: list[QRectF],
    clip: QRectF,
    x: float,
    y: float,
    text: str,
    *,
    fill: QColor,
    center: bool = False,
    outline: QColor | None = None,
    force: bool = False,
) -> None:
    if not text:
        return
    metrics = painter.fontMetrics()
    width = metrics.horizontalAdvance(text) + 14
    height = max(18, metrics.height() + 4)
    rect = (
        QRectF(x - width / 2, y - height / 2, width, height)
        if center
        else QRectF(x, y, width, height)
    )
    if not force and not _fits(rect, taken, clip):
        return
    painter.setPen(Qt.PenStyle.NoPen if outline is None else QPen(outline, 1.4))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, 7, 7)
    painter.setPen(QColor(255, 251, 235))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    taken.append(rect)


def _chip(
    painter: QPainter,
    x: float,
    y: float,
    text: str,
    view_w: int,
    view_h: int,
) -> None:
    if not text:
        return
    metrics = painter.fontMetrics()
    width = metrics.horizontalAdvance(text) + 16
    height = max(22, metrics.height() + 8)
    left = min(max(8.0, x + 16), max(8.0, view_w - width - 8))
    top = min(max(8.0, y + 18), max(8.0, view_h - height - 8))
    rect = QRectF(left, top, width, height)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(15, 23, 42, 228))
    painter.drawRoundedRect(rect, 8, 8)
    painter.setPen(QColor(255, 251, 235))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


def _box(row: dict[str, str]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (
        int(row["x_min"]),
        int(row["y_min"]),
        int(row["x_max"]),
        int(row["y_max"]),
    )
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return x0, y0, x1, y1


def _is_border(box: tuple[int, int, int, int]) -> bool:
    return min(box[2] - box[0], box[3] - box[1]) <= HAIRLINE


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def build_mainland_overlay(pack, language: str | None = None) -> MainlandRegionOverlay | None:
    """Build the overlay for the mainland pack, or return None."""
    if pack is None or str(getattr(pack, "id", "")) != "mainland":
        return None
    tsv = _find_tsv(Path(pack.root))
    terrain = Path(pack.terrain_path)
    if tsv is None or not terrain.is_file():
        return None
    try:
        import numpy as np
        from PIL import Image
        from scipy import ndimage
    except Exception:
        return None

    origin_x = int(pack.origin_x)
    origin_y = int(pack.origin_y)
    pixel_scale = max(1, int(pack.pixel_scale))
    rows = _load_rows(tsv)
    nav_l = np.asarray(Image.open(terrain).convert("L"))
    gh, gw = nav_l.shape[0] // pixel_scale, nav_l.shape[1] // pixel_scale
    if gh < 2 or gw < 2:
        return None
    land = nav_l[: gh * pixel_scale, : gw * pixel_scale]
    land = land.reshape(gh, pixel_scale, gw, pixel_scale).mean(axis=(1, 3)) > 40

    borders: list[tuple[float, float, float, float]] = []
    blocked = np.zeros((gh, gw), dtype=bool)
    thin: list[tuple[tuple[int, int, int, int], str, str]] = []
    village_fills: list[tuple[int, int, int, int, str]] = []
    seam_fills: list[tuple[int, int, int, int, str]] = []
    named_fills: list[tuple[int, int, int, int, str]] = []
    for row in rows:
        box = _box(row)
        nx0 = box[0] - origin_x
        ny0 = box[1] - origin_y
        nx1 = box[2] - origin_x
        ny1 = box[3] - origin_y
        # Every boundary stroke stays blocked. Leaving the thick walls out
        # merges 켄트, 하이네, and 오렌 into their neighbors.
        ix0 = max(0, min(gw, nx0))
        iy0 = max(0, min(gh, ny0))
        ix1 = max(0, min(gw, nx1 if nx1 > nx0 else nx0 + 1))
        iy1 = max(0, min(gh, ny1 if ny1 > ny0 else ny0 + 1))
        if ix1 > ix0 and iy1 > iy0:
            blocked[iy0:iy1, ix0:ix1] = True
        if not _is_border(box):
            if ix1 > ix0 and iy1 > iy0:
                named = next(
                    (name for name in (row["nameA"], row["nameB"]) if name in _NAMED_RECTS),
                    "",
                )
                if named:
                    named_fills.append((ix0, iy0, ix1, iy1, named))
                elif _village_label(row["nameA"], row["nameB"]):
                    village_fills.append(
                        (ix0, iy0, ix1, iy1, _area_name(row["nameA"], row["nameB"]))
                    )
                else:
                    side_a = _main_region(row["nameA"])
                    side_b = _main_region(row["nameB"])
                    if side_a and side_a == side_b:
                        seam_fills.append((ix0, iy0, ix1, iy1, side_a))
                        thin.append((box, row["nameA"], row["nameB"]))
            continue
        thin.append((box, row["nameA"], row["nameB"]))
        side_a = _main_region(row["nameA"])
        side_b = _main_region(row["nameB"])
        if not side_a or not side_b or side_a == side_b:
            continue
        if (box[3] - box[1]) <= (box[2] - box[0]):
            mid = (ny0 + ny1) / 2.0
            borders.append((float(nx0), mid, float(nx1), mid))
        else:
            mid = (nx0 + nx1) / 2.0
            borders.append((mid, float(ny0), mid, float(ny1)))

    open_land = land & ~blocked
    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=int)
    components, count = ndimage.label(open_land, structure=structure)

    def first_land(wx: int, wy: int, dx: int, dy: int) -> int:
        # Thick walls can be wider than a hairline, so search past them.
        for _ in range(200):
            wx += dx
            wy += dy
            ix, iy = wx - origin_x, wy - origin_y
            if not (0 <= iy < gh and 0 <= ix < gw):
                return 0
            comp_id = int(components[iy, ix])
            if comp_id:
                return comp_id
        return 0

    from collections import Counter, defaultdict

    votes: dict[int, Counter[str]] = defaultdict(Counter)
    for box, name_a, name_b in thin:
        x0, y0, x1, y1 = box
        weight = max(x1 - x0, y1 - y0, 1)
        mx = (x0 + max(x0, x1 - 1)) // 2
        my = (y0 + max(y0, y1 - 1)) // 2
        if (y1 - y0) <= (x1 - x0):
            sides = (
                first_land(mx, min(y0, y1), 0, -1),
                first_land(mx, max(y0, y1) - 1, 0, 1),
            )
        else:
            sides = (
                first_land(min(x0, x1), my, -1, 0),
                first_land(max(x0, x1) - 1, my, 1, 0),
            )
        raw_names = (name_a,) if name_a == name_b else (name_a, name_b)
        names = tuple(dict.fromkeys(_vote_name(name) for name in raw_names if name))
        for comp_id in sides:
            if not comp_id:
                continue
            for name in names:
                votes[comp_id][name] += weight

    name_of: dict[int, str] = {}
    for comp_id, tally in votes.items():
        ranking = tally.most_common(2)
        if len(ranking) == 1 or ranking[0][1] > ranking[1][1]:
            name_of[comp_id] = ranking[0][0]

    territory_names = sorted(
        (set(name_of.values()) & _MAIN_REGIONS) | _NAMED_RECTS
    )
    total = max(1, len(territory_names))
    palette = {
        name: _color_for(i, total, FILL_ALPHA) for i, name in enumerate(territory_names)
    }

    names = [""] + territory_names
    ids = {name: i + 1 for i, name in enumerate(territory_names)}
    grid = np.zeros((gh, gw), dtype=np.int16)
    for comp_id, name in name_of.items():
        idx = ids.get(name)
        if idx:
            grid[components == comp_id] = idx

    overlay = np.zeros((gh, gw, 4), dtype=np.uint8)
    for name, idx in ids.items():
        overlay[grid == idx] = palette[name]

    def nearby_area(ix0: int, iy0: int, ix1: int, iy1: int) -> str:
        pad = 12
        sx0, sy0 = max(0, ix0 - pad), max(0, iy0 - pad)
        sx1, sy1 = min(gw, ix1 + pad), min(gh, iy1 + pad)
        sample = grid[sy0:sy1, sx0:sx1].copy()
        sample[
            max(0, iy0 - sy0) : max(0, iy1 - sy0),
            max(0, ix0 - sx0) : max(0, ix1 - sx0),
        ] = 0
        found = sample[sample > 0]
        if found.size == 0:
            return ""
        idx = int(np.bincount(found).argmax())
        if idx <= 0 or idx >= len(names):
            return ""
        return names[idx]

    def paint_box(ix0: int, iy0: int, ix1: int, iy1: int, area: str) -> None:
        if area not in palette or ix1 <= ix0 or iy1 <= iy0:
            return
        ys, xs = np.where(land[iy0:iy1, ix0:ix1])
        if ys.size == 0:
            return
        overlay[iy0 + ys, ix0 + xs] = palette[area]
        grid[iy0 + ys, ix0 + xs] = ids[area]

    for ix0, iy0, ix1, iy1, area in seam_fills:
        paint_box(ix0, iy0, ix1, iy1, area)
    for ix0, iy0, ix1, iy1, area in named_fills:
        paint_box(ix0, iy0, ix1, iy1, area)
    for ix0, iy0, ix1, iy1, parent in village_fills:
        paint_box(ix0, iy0, ix1, iy1, parent or nearby_area(ix0, iy0, ix1, iy1))

    regions: list[_RegionLabel] = []
    for name in territory_names:
        idx = ids[name]
        ys, xs = np.where(grid == idx)
        if xs.size == 0:
            continue
        regions.append(
            _RegionLabel(
                name=name,
                cx=float(xs.mean() + 0.5),
                cy=float(ys.mean() + 0.5),
                x0=int(xs.min()),
                y0=int(ys.min()),
                x1=int(xs.max() + 1),
                y1=int(ys.max() + 1),
            )
        )
    regions.sort(key=lambda item: (item.x1 - item.x0) * (item.y1 - item.y0), reverse=True)

    image = QImage(
        overlay.data,
        gw,
        gh,
        gw * 4,
        QImage.Format.Format_RGBA8888,
    ).copy()
    return MainlandRegionOverlay(
        image=image,
        names=names,
        label_grid=grid,
        borders=borders,
        places=[],
        regions=regions,
        pixels=overlay,
        language=str(language or "ko"),
    )
