"""Debug \"Navigation show\" map: pack terrain + live player / nav overlays.

Heavy work (terrain load, marker paint) stays off the bot thread and off the
Tk main thread. Callers submit snapshots to :class:`NavShowRenderWorker`.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

__all__ = [
    "NavShowRenderWorker",
    "nav_show_content_stamp",
    "player_on_blocked_tile",
    "render_nav_show_image",
]

_terrain_lock = threading.Lock()
_terrain_cache: dict[str, tuple[float, Any, Any]] = {}  # map_id -> (mtime, base_rgb, walkable)

_MARKER_COLORS = {
    "origin": (34, 211, 238),
    "goal": (132, 204, 22),
    "waypoint": (250, 204, 21),
    "plan_from": (251, 146, 60),
    "plan_to": (249, 115, 22),
    "gate_from": (244, 114, 182),
    "gate_to": (236, 72, 153),
    "scroll_to": (167, 139, 250),
}


def _xy_pair(value: Any) -> Optional[tuple[int, int]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    if isinstance(value, Mapping):
        try:
            return int(value["x"]), int(value["y"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _display_map_id(snapshot: Mapping[str, Any] | None) -> str:
    snap = snapshot or {}
    nav = snap.get("navigation") or {}
    overview = snap.get("overview") or {}
    for key in ("display_map", "live_pack"):
        value = str(nav.get(key) or "").strip()
        if value:
            return value
    return str(overview.get("map") or "talking_island")


def nav_show_content_stamp(snapshot: Mapping[str, Any] | None) -> tuple:
    """Cheap fingerprint: skip re-render when nav geometry is unchanged."""
    snap = snapshot or {}
    overview = snap.get("overview") or {}
    nav = snap.get("navigation") or {}
    path = nav.get("path") or []
    path_tail = ()
    if isinstance(path, list) and path:
        last = path[-1]
        if isinstance(last, (list, tuple)) and len(last) >= 2:
            path_tail = (last[0], last[1])
    map_id = _display_map_id(snap)
    terrain_mtime = 0.0
    try:
        pack = _pack_for_map(map_id)
        terrain_mtime = float(Path(pack.terrain_path).stat().st_mtime)
    except Exception:
        terrain_mtime = 0.0
    world_nav = nav.get("world_nav") if isinstance(nav.get("world_nav"), Mapping) else {}
    markers = nav.get("plan_markers") or []
    marker_tail = ()
    if isinstance(markers, list) and markers:
        last = markers[-1]
        if isinstance(last, Mapping):
            marker_tail = (last.get("kind"), tuple(last.get("xy") or ()))
    gate_warn = nav.get("gate_warn") if isinstance(nav.get("gate_warn"), Mapping) else {}
    return (
        map_id,
        terrain_mtime,
        nav.get("live_map_id"),
        tuple(nav.get("live_origin_xy") or nav.get("origin_xy") or ()),
        tuple(nav.get("goal_xy") or ()),
        tuple(nav.get("waypoint_xy") or ()),
        nav.get("path_len"),
        path_tail,
        nav.get("travel_purpose"),
        nav.get("travel_hop_active"),
        nav.get("enter_farm_detour"),
        tuple(overview.get("farms") or ()),
        world_nav.get("phase"),
        world_nav.get("step_i"),
        world_nav.get("steps_n"),
        marker_tail,
        gate_warn.get("message"),
        gate_warn.get("to_map"),
    )


def _pack_for_map(map_id: str):
    from app._03_world.space.map_pack import load_map_pack, resolve_maps_dir
    from session.paths import manmabot_root

    mid = str(map_id or "").strip() or "talking_island"
    maps_dir = resolve_maps_dir({"navigation": {"maps_dir": "data/maps"}})
    if maps_dir is None:
        maps_dir = manmabot_root() / "data" / "maps"
    return load_map_pack(maps_dir, mid)


def _load_base_layers(map_id: str) -> tuple[Any, Any] | None:
    """Return ``(base_rgb_image, walkable_bool_array)`` cached per pack mtime.

    Display uses the pack ``nav.png`` pixels (so the UI matches the live pack).
    Walkability still comes from :class:`TerrainMap`.
    """
    import numpy as np
    from PIL import Image

    try:
        pack = _pack_for_map(map_id)
    except Exception:
        return None
    path = Path(pack.terrain_path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(pack.id)
    with _terrain_lock:
        hit = _terrain_cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1], hit[2]

    try:
        from app._03_world.space.terrain_map import TerrainMap

        terrain = TerrainMap.from_png(path, pixel_scale=max(1, int(pack.pixel_scale)))
        walk = np.asarray(terrain.walkable, dtype=bool)
        image = Image.open(path).convert("RGB")
        # Keep display size aligned with walkable tile grid when pixel_scale > 1.
        scale = max(1, int(pack.pixel_scale))
        if scale > 1:
            tw, th = terrain.width, terrain.height
            image = image.resize(
                (tw, th), getattr(Image, "Resampling", Image).NEAREST
            )
        elif image.size != (terrain.width, terrain.height):
            image = image.resize(
                (terrain.width, terrain.height),
                getattr(Image, "Resampling", Image).NEAREST,
            )
    except Exception:
        return None

    with _terrain_lock:
        _terrain_cache[key] = (mtime, image, walk)
    return image, walk


def _farm_rects(map_id: str) -> list[tuple[int, int, int, int, str]]:
    try:
        import yaml

        pack = _pack_for_map(map_id)
        path = pack.farm_areas_path
        if path is None or not Path(path).is_file():
            return []
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        areas = data.get("areas") or []
    except Exception:
        return []
    out: list[tuple[int, int, int, int, str]] = []
    for item in areas:
        if not isinstance(item, Mapping):
            continue
        try:
            x0, y0 = int(item["x0"]), int(item["y0"])
            x1, y1 = int(item["x1"]), int(item["y1"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append((x0, y0, x1, y1, str(item.get("name") or "")))
    return out


def player_on_blocked_tile(
    map_id: str,
    origin: Any,
    *,
    allow_load: bool = False,
) -> bool:
    """True when origin is off-map or on a blocked tile.

    ``allow_load=False`` only consults the terrain cache (UI-safe). The render
    worker warms the cache with ``allow_load=True`` / ``render_nav_show_image``.
    """
    xy = _xy_pair(origin)
    if xy is None:
        return False
    key = str(map_id or "").strip() or "talking_island"
    with _terrain_lock:
        hit = _terrain_cache.get(key)
    if hit is None:
        if not allow_load:
            return False
        layers = _load_base_layers(map_id)
        if layers is None:
            return False
        _base, walk = layers
    else:
        _base, walk = hit[1], hit[2]
    x, y = xy
    h, w = walk.shape
    if x < 0 or y < 0 or x >= w or y >= h:
        return True
    return not bool(walk[y, x])


def _put_px(px, width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < width and 0 <= y < height:
        px[x, y] = color


def _draw_marker(
    draw,
    px,
    width: int,
    height: int,
    x: int,
    y: int,
    color: tuple[int, int, int],
    *,
    size: int = 5,
) -> None:
    """Visible cross + ring (1px dots are invisible on large maps)."""
    r = max(3, int(size))
    for dx in range(-r, r + 1):
        _put_px(px, width, height, x + dx, y, color)
        _put_px(px, width, height, x, y + dx, color)
    box = [x - r, y - r, x + r, y + r]
    try:
        draw.ellipse(box, outline=color)
    except Exception:
        pass


def _draw_path_line(
    draw,
    path: list[tuple[int, int]],
    color: tuple[int, int, int],
    *,
    width: int = 2,
) -> None:
    if len(path) < 2:
        for pt in path:
            draw.point(pt, fill=color)
        return
    step = 1 if len(path) <= 1200 else max(1, len(path) // 1200)
    pts = path[::step]
    if pts[-1] != path[-1]:
        pts.append(path[-1])
    try:
        draw.line(pts, fill=color, width=max(1, int(width)))
    except Exception:
        for pt in pts:
            draw.point(pt, fill=color)


def _hud_lines(nav: Mapping[str, Any], map_id: str) -> list[str]:
    live_id = nav.get("live_map_id")
    pack = str(nav.get("live_pack") or map_id)
    abs_xy = _xy_pair(nav.get("live_abs_xy"))
    origin = _xy_pair(nav.get("live_origin_xy") or nav.get("origin_xy"))
    lines = [f"map {pack}"]
    if live_id is not None:
        lines[0] = f"map {pack}  (id={live_id})"
    if abs_xy is not None:
        lines.append(f"abs ({abs_xy[0]},{abs_xy[1]})")
    if origin is not None:
        lines.append(f"nav ({origin[0]},{origin[1]})")
    world_nav = nav.get("world_nav") if isinstance(nav.get("world_nav"), Mapping) else None
    if world_nav:
        lines.append(
            f"plan {world_nav.get('phase') or '-'} "
            f"step {int(world_nav.get('step_i') or 0) + 1}/"
            f"{int(world_nav.get('steps_n') or 0)}"
        )
        reason = str(world_nav.get("reason") or "").strip()
        if reason:
            lines.append(reason[:48])
    elif nav.get("travel_purpose"):
        lines.append(f"hop {nav.get('travel_purpose')}")
        if nav.get("path_len"):
            lines.append(f"path_len {nav.get('path_len')}")
    gate_warn = nav.get("gate_warn") if isinstance(nav.get("gate_warn"), Mapping) else None
    if gate_warn and gate_warn.get("message"):
        lines.append(f"WARN GATE {str(gate_warn.get('message'))[:56]}")
        fm = gate_warn.get("from_map")
        tm = gate_warn.get("to_map")
        if fm is not None or tm is not None:
            lines.append(f"WARN map {fm} -> {tm}")
    return lines


def render_nav_show_image(
    snapshot: Mapping[str, Any] | None,
    *,
    max_width: int = 4096,
    max_height: int = 4096,
):
    """Build an RGB map image for Navigation show. Safe for worker threads."""
    from PIL import Image, ImageDraw

    snap = dict(snapshot or {})
    overview = dict(snap.get("overview") or {})
    nav = dict(snap.get("navigation") or {})
    map_id = _display_map_id(snap)
    layers = _load_base_layers(map_id)
    if layers is None:
        return None
    base, _walk = layers
    image = base.copy()
    draw = ImageDraw.Draw(image)
    px = image.load()
    width, height = image.size

    selected = set(str(n) for n in (overview.get("farms") or []))
    for x0, y0, x1, y1, name in _farm_rects(map_id):
        color = (34, 197, 94) if (not selected or name in selected) else (55, 65, 81)
        draw.rectangle([x0, y0, x1, y1], outline=color)

    path_pts: list[tuple[int, int]] = []
    path = nav.get("path") or []
    if isinstance(path, list):
        for item in path:
            pt = _xy_pair(item)
            if pt is not None:
                path_pts.append(pt)
    if path_pts:
        _draw_path_line(draw, path_pts, (59, 130, 246), width=2)

    for marker in list(nav.get("plan_markers") or []):
        if not isinstance(marker, Mapping):
            continue
        pt = _xy_pair(marker.get("xy"))
        if pt is None:
            continue
        kind = str(marker.get("kind") or "plan_to")
        color = _MARKER_COLORS.get(kind, (249, 115, 22))
        size = 6 if marker.get("active") else 4
        _draw_marker(draw, px, width, height, pt[0], pt[1], color, size=size)

    for key, kind in (
        ("goal_xy", "goal"),
        ("waypoint_xy", "waypoint"),
        ("origin_xy", "origin"),
        ("live_origin_xy", "origin"),
    ):
        pt = _xy_pair(nav.get(key))
        if pt is None:
            continue
        size = 7 if kind == "origin" else 5
        _draw_marker(
            draw,
            px,
            width,
            height,
            pt[0],
            pt[1],
            _MARKER_COLORS[kind],
            size=size,
        )

    # Corner HUD: current map + live pose + plan step.
    hud = _hud_lines(nav, map_id)
    if hud:
        pad = 6
        line_h = 14
        box_h = pad * 2 + line_h * len(hud)
        box_w = min(width - 8, max(160, 8 + max(len(s) for s in hud) * 7))
        warn = any(s.startswith("WARN") for s in hud)
        draw.rectangle(
            [4, 4, 4 + box_w, 4 + box_h],
            fill=(127, 29, 29) if warn else (17, 24, 39),
        )
        y = 4 + pad
        for line in hud:
            color = (254, 226, 226) if line.startswith("WARN") else (226, 232, 240)
            draw.text((4 + pad, y), line, fill=color)
            y += line_h

    w, h = image.size
    if w > max_width or h > max_height:
        image.thumbnail(
            (max_width, max_height), getattr(Image, "Resampling", Image).NEAREST
        )
    return image


class NavShowRenderWorker:
    """Single dedicated daemon thread; latest job wins (drops stale)."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._pending: Optional[tuple[int, dict, tuple]] = None
        self._on_done: Callable[[int, tuple, Any, bool], None] | None = None
        self._stop = False
        self._thread = threading.Thread(
            target=self._loop, name="nav-show-render", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def submit(
        self,
        *,
        seq: int,
        snapshot: Mapping[str, Any],
        stamp: tuple,
        on_done: Callable[[int, tuple, Any, bool], None],
    ) -> None:
        """Queue render. ``on_done(seq, stamp, image|None, failed)`` from worker."""
        with self._cond:
            self._pending = (int(seq), dict(snapshot), stamp)
            self._on_done = on_done
            self._cond.notify()

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._stop and self._pending is None:
                    self._cond.wait(timeout=0.5)
                if self._stop:
                    return
                job = self._pending
                on_done = self._on_done
                self._pending = None
            if job is None or on_done is None:
                continue
            seq, snap, stamp = job
            failed = False
            image = None
            try:
                image = render_nav_show_image(snap)
                if image is None:
                    failed = True
            except Exception:
                failed = True
                image = None
            try:
                on_done(seq, stamp, image, failed)
            except Exception:
                pass
            time.sleep(0.001)
