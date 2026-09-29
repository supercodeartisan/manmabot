"""Small nav-map overview for the Farms tab (not the full editor)."""
from __future__ import annotations

from typing import Iterable

from PIL import Image, ImageDraw

from manmabot_v1.map_previews import open_real_map_image
from manmabot_v1.probes import (
    farms_yaml_path,
    is_dungeon_map_id,
    load_map_pack_safe,
    load_selected_farm_rects,
)

_FILL = (56, 189, 248, 90)
_OUTLINE = (56, 189, 248, 255)


def render_farm_overview(
    map_id: str,
    selected: Iterable[str],
    max_w: int,
    max_h: int,
) -> tuple[Image.Image, bool]:
    """Fit the art map into ``max_w`` x ``max_h`` and overlay checked farm rects.

    Returns ``(image, missing)``. ``missing`` is True when ``images/real_maps``
    has no file for this map — the image is then a dark placeholder.
    """
    max_w = max(1, int(max_w))
    max_h = max(1, int(max_h))
    pack = load_map_pack_safe(map_id)
    if pack is None:
        return Image.new("RGB", (max_w, max_h), (28, 28, 28)), True
    try:
        base = open_real_map_image(map_id)
        if base is None:
            return Image.new("RGB", (max_w, max_h), (28, 28, 28)), True
    except Exception:
        return Image.new("RGB", (max_w, max_h), (28, 28, 28)), True

    iw, ih = base.size
    scale = min(max_w / max(iw, 1), max_h / max(ih, 1))
    dw = max(1, int(round(iw * scale)))
    dh = max(1, int(round(ih * scale)))
    shown = base.resize((dw, dh), Image.Resampling.BILINEAR)

    if is_dungeon_map_id(pack.id):
        return shown, False

    names = [str(n) for n in selected if str(n).strip()]
    if not names:
        return shown, False

    path = farms_yaml_path(pack.id)
    if path is None or not path.is_file():
        return shown, False

    try:
        rects = load_selected_farm_rects(names, pack.id)
    except Exception:
        return shown, False

    ps = max(1, int(getattr(pack, "pixel_scale", 1) or 1))
    overlay = Image.new("RGBA", shown.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for item in rects:
        if not isinstance(item, dict):
            continue
        try:
            x0 = int(item["x0"])
            y0 = int(item["y0"])
            x1 = int(item["x1"])
            y1 = int(item["y1"])
        except (KeyError, TypeError, ValueError):
            continue
        px0 = int(x0 * ps * scale)
        py0 = int(y0 * ps * scale)
        px1 = int((x1 + 1) * ps * scale) - 1
        py1 = int((y1 + 1) * ps * scale) - 1
        if px1 < px0:
            px0, px1 = px1, px0
        if py1 < py0:
            py0, py1 = py1, py0
        draw.rectangle([px0, py0, px1, py1], fill=_FILL, outline=_OUTLINE, width=2)

    out = Image.alpha_composite(shown.convert("RGBA"), overlay).convert("RGB")
    return out, False
