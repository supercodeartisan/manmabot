"""Chain dungeon floors with the patrol editor's A* and floors_entrances.txt.

One floor is ``find_path`` from the standing tile to the next gate.
The next floor starts at that gate's landing tile. Click points stored
for each floor are the mouse hops along that A* line.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from session.paths import TOOLS_USERDATA_DIR, ensure_userdata, manmabot_root

_PAIR = re.compile(
    r"^(?P<src>.+?)\s+"
    r"(?:(?P<sf>\d+F)\s+)?"
    r"A?\((?P<sx>\d+),(?P<sy>\d+)\)\s+->\s+"
    r"(?P<dst>.+?)\s+"
    r"(?:(?P<df>\d+F)\s+)?"
    r"B?\((?P<dx>\d+),(?P<dy>\d+)\)\s*$"
)
_SKIP_DIRS = {"dungeons", "_legacy_dungeons", "obstacle_tiles_raw", "new"}
_SNAP_RADIUS = 8
_MAX_DEPTH = 12
_MAX_ZONE_HOPS = 6


class RouteError(Exception):
    """Start and goal cannot be joined with the floor graph and walk grids."""


@dataclass(frozen=True)
class MapChoice:
    pack_id: str
    kr: str
    en: str
    raw_map: str
    origin_x: int
    origin_y: int
    pixel_scale: int
    nav_path: Path

    @property
    def label(self) -> str:
        title = self.kr or self.en or self.pack_id
        if title == self.pack_id:
            return self.pack_id
        return f"{title}   {self.pack_id}"


@dataclass(frozen=True)
class PickedPoint:
    choice: MapChoice
    nav_x: int
    nav_y: int

    @property
    def world_x(self) -> int:
        return self.choice.origin_x + self.nav_x * self.choice.pixel_scale

    @property
    def world_y(self) -> int:
        return self.choice.origin_y + self.nav_y * self.choice.pixel_scale


@dataclass(frozen=True)
class PortalEdge:
    src_name: str
    src_xy: tuple[int, int]
    dst_name: str
    dst_xy: tuple[int, int]
    kind: str  # floor | passage | zone | entrance


@dataclass
class ClickPoint:
    nav_x: int
    nav_y: int
    world_x: int
    world_y: int
    name: str


@dataclass
class RouteSegment:
    choice: MapChoice
    path: list[tuple[int, int]]
    clicks: list[ClickPoint] = field(default_factory=list)


def choice_for_raw_map(map_id: int) -> Optional[MapChoice]:
    """Pack whose ``meta.yaml`` ``raw_map`` is this live MapSubsystem mapId."""
    key = str(int(map_id))
    for choice in list_engine_maps():
        if choice.raw_map == key:
            return choice
    return None


def floors_entrances_path() -> Path:
    return manmabot_root() / "analysis" / "lc930" / "dungeon" / "floors_entrances.txt"


_MAP_CACHE: list[MapChoice] | None = None


def list_engine_maps() -> list[MapChoice]:
    """Packs under ``Engine/data/maps`` that have ``meta.yaml`` and ``nav.png``."""
    global _MAP_CACHE
    if _MAP_CACHE is not None:
        return _MAP_CACHE
    root = manmabot_root() / "data" / "maps"
    names = _kr_by_raw_map()
    found: list[MapChoice] = []
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name in _SKIP_DIRS or child.name.startswith("_"):
            continue
        meta_path = child / "meta.yaml"
        nav = child / "nav.png"
        if not meta_path.is_file() or not nav.is_file():
            continue
        doc = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            continue
        raw = str(doc.get("raw_map") or "").strip()
        rec = names.get(raw) or {}
        found.append(
            MapChoice(
                pack_id=str(doc.get("id") or child.name),
                kr=str(rec.get("kr") or ""),
                en=str(rec.get("en") or doc.get("name") or ""),
                raw_map=raw,
                origin_x=int(doc.get("origin_x") or 0),
                origin_y=int(doc.get("origin_y") or 0),
                pixel_scale=max(1, int(doc.get("pixel_scale") or 1)),
                nav_path=nav.resolve(),
            )
        )
    found.sort(key=lambda m: (m.kr or m.en or m.pack_id, m.pack_id))
    _MAP_CACHE = found
    return found


def load_portal_edges(path: Path | None = None) -> list[PortalEdge]:
    text = (path or floors_entrances_path()).read_text(encoding="utf-8")
    kind = ""
    edges: list[PortalEdge] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# [던전 입구]"):
            kind = "entrance"
            continue
        if stripped.startswith("# [층별 전환지점]"):
            kind = "floor"
            continue
        if stripped.startswith("# [같은층 구역간 링크]"):
            kind = "zone"
            continue
        if stripped.startswith("# [던전↔지하통로"):
            kind = "passage"
            continue
        if not kind or stripped.startswith("#") or stripped.startswith("===="):
            continue
        match = _PAIR.match(stripped)
        if not match:
            continue
        edges.append(
            PortalEdge(
                src_name=match.group("src").strip(),
                src_xy=(int(match.group("sx")), int(match.group("sy"))),
                dst_name=match.group("dst").strip(),
                dst_xy=(int(match.group("dx")), int(match.group("dy"))),
                kind=kind,
            )
        )
    return edges


def plan_floor_route(
    start: PickedPoint,
    goal: PickedPoint,
    *,
    edges: list[PortalEdge] | None = None,
) -> list[RouteSegment]:
    """Walk start → goal across floor gates. Raises ``RouteError`` when none exists."""
    router = _Router(edges if edges is not None else load_portal_edges())
    if start.choice.pack_id == goal.choice.pack_id:
        segment = router.segment_on(
            start.choice,
            (start.nav_x, start.nav_y),
            (goal.nav_x, goal.nav_y),
            goal_name="goal",
        )
        if segment is None:
            raise RouteError(
                f"{start.choice.label} 안에서 출발점과 도착점이 걸어서 이어지지 않습니다."
            )
        return [segment]

    start_name = start.choice.kr
    goal_name = goal.choice.kr
    if not start_name or not goal_name:
        raise RouteError("선택한 맵에 층 전환 자료의 한글 맵 이름이 없습니다.")

    found = router.search(
        start_name,
        (start.nav_x, start.nav_y),
        goal_name,
        (goal.nav_x, goal.nav_y),
        allow_entrance=False,
    )
    if found is None:
        found = router.search(
            start_name,
            (start.nav_x, start.nav_y),
            goal_name,
            (goal.nav_x, goal.nav_y),
            allow_entrance=True,
        )
    if not found:
        raise RouteError(
            f"{start.choice.label} 에서 {goal.choice.label} 까지 "
            "이어지는 층 전환 길을 찾지 못했습니다."
        )
    return found


def save_route(segments: list[RouteSegment]) -> list[Path]:
    """Write each floor's click points as patrol waypoints, plus one route file."""
    from settings.dungeon_assets import save_patrol_overlay

    ensure_userdata()
    written: list[Path] = []
    route_segments: list[dict] = []
    for segment in segments:
        points = [(c.nav_x, c.nav_y) for c in segment.clicks]
        names = [c.name for c in segment.clicks]
        if points:
            written.append(save_patrol_overlay(segment.choice.pack_id, points, names))
        route_segments.append(
            {
                "pack_id": segment.choice.pack_id,
                "kr": segment.choice.kr,
                "path_steps": max(0, len(segment.path) - 1),
                "clicks": [
                    {
                        "x": c.nav_x,
                        "y": c.nav_y,
                        "world_x": c.world_x,
                        "world_y": c.world_y,
                        "name": c.name,
                    }
                    for c in segment.clicks
                ],
            }
        )
    route_path = TOOLS_USERDATA_DIR / "dungeon_floor_route.yaml"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(
        yaml.safe_dump(
            {"segments": route_segments},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    written.append(route_path)
    return written


def _kr_by_raw_map() -> dict[str, dict]:
    path = manmabot_root() / "data" / "world" / "map_transitions.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for key, rec in (raw.get("maps") or {}).items():
        if not isinstance(rec, dict) or rec.get("pc_clone"):
            continue
        mid = str(rec.get("mapId", key))
        prev = out.get(mid)
        if prev is None or (not prev.get("kr") and rec.get("kr")):
            out[mid] = rec
    return out


class _Router:
    def __init__(self, edges: list[PortalEdge]) -> None:
        self.edges = edges
        self.by_kr: dict[str, MapChoice] = {}
        for choice in list_engine_maps():
            if choice.kr and choice.kr not in self.by_kr:
                self.by_kr[choice.kr] = choice
        self._terrain: dict[str, object] = {}
        self._paths: dict[tuple, list[tuple[int, int]]] = {}

    def search(
        self,
        map_name: str,
        nav: tuple[int, int],
        goal_name: str,
        goal_nav: tuple[int, int],
        *,
        allow_entrance: bool,
    ) -> Optional[list[RouteSegment]]:
        return self._walk(
            map_name,
            nav,
            goal_name,
            goal_nav,
            allow_entrance=allow_entrance,
            seen=frozenset(),
        )

    def _walk(
        self,
        map_name: str,
        nav: tuple[int, int],
        goal_name: str,
        goal_nav: tuple[int, int],
        *,
        allow_entrance: bool,
        seen: frozenset[str],
    ) -> Optional[list[RouteSegment]]:
        if map_name in seen or len(seen) > _MAX_DEPTH:
            return None
        choice = self.by_kr.get(map_name)
        if choice is None:
            return None
        if map_name == goal_name:
            segment = self.segment_on(choice, nav, goal_nav, goal_name="goal")
            return [segment] if segment is not None else None

        options: list[tuple[int, PortalEdge, list[tuple[int, int]]]] = []
        for edge in self._leaving(map_name, allow_entrance=allow_entrance):
            if edge.dst_name in seen or edge.dst_name not in self.by_kr:
                continue
            gate = self._snap_world(choice, edge.src_xy)
            if gate is None:
                continue
            path = self._path(choice, nav, gate)
            if not path:
                continue
            options.append((len(path), edge, path))
        options.sort(key=lambda item: item[0])
        seen_next = seen | {map_name}
        for _cost, edge, path in options:
            landing_choice = self.by_kr[edge.dst_name]
            landing = self._snap_world(landing_choice, edge.dst_xy)
            if landing is None:
                continue
            rest = self._walk(
                edge.dst_name,
                landing,
                goal_name,
                goal_nav,
                allow_entrance=allow_entrance,
                seen=seen_next,
            )
            if rest is None:
                continue
            clicks = _clicks_for(choice, path, final_name=f"gate_{edge.dst_name}")
            return [RouteSegment(choice=choice, path=path, clicks=clicks), *rest]
        return None

    def segment_on(
        self,
        choice: MapChoice,
        start: tuple[int, int],
        goal: tuple[int, int],
        *,
        goal_name: str,
    ) -> Optional[RouteSegment]:
        path = self._path(choice, start, goal)
        if not path:
            return None
        return RouteSegment(
            choice=choice,
            path=path,
            clicks=_clicks_for(choice, path, final_name=goal_name),
        )

    def _leaving(self, map_name: str, *, allow_entrance: bool) -> list[PortalEdge]:
        kinds = {"floor", "passage"}
        if allow_entrance:
            kinds.add("entrance")
        return [
            edge
            for edge in self.edges
            if edge.src_name == map_name
            and edge.dst_name != map_name
            and edge.kind in kinds
        ]

    def _zone_edges(self, map_name: str) -> list[PortalEdge]:
        return [
            edge
            for edge in self.edges
            if edge.kind == "zone"
            and edge.src_name == map_name
            and edge.dst_name == map_name
        ]

    def _path(
        self,
        choice: MapChoice,
        start: tuple[int, int],
        goal: tuple[int, int],
    ) -> list[tuple[int, int]]:
        direct = self._find_cached(choice, start, goal)
        if direct:
            return direct
        return self._through_zones(choice, start, goal)

    def _through_zones(
        self,
        choice: MapChoice,
        start: tuple[int, int],
        goal: tuple[int, int],
    ) -> list[tuple[int, int]]:
        zones = self._zone_edges(choice.kr)
        if not zones:
            return []
        # Standing tile, path so far, unused zone indexes.
        queue: list[tuple[tuple[int, int], list[tuple[int, int]], frozenset[int]]] = [
            (start, [], frozenset())
        ]
        seen_pos = {start}
        while queue:
            pos, so_far, used = queue.pop(0)
            if len(used) > _MAX_ZONE_HOPS:
                continue
            for index, edge in enumerate(zones):
                if index in used:
                    continue
                gate = self._snap_world(choice, edge.src_xy)
                landing = self._snap_world(choice, edge.dst_xy)
                if gate is None or landing is None:
                    continue
                to_gate = self._find_cached(choice, pos, gate)
                if not to_gate:
                    continue
                after = _join(so_far, to_gate)
                to_goal = self._find_cached(choice, landing, goal)
                if to_goal:
                    hopped = _join(after, [(landing[0], landing[1])])
                    return _join(hopped, to_goal)
                if landing not in seen_pos:
                    seen_pos.add(landing)
                    queue.append((landing, _join(after, [landing]), used | {index}))
        return []

    def _find_cached(
        self,
        choice: MapChoice,
        start: tuple[int, int],
        goal: tuple[int, int],
    ) -> list[tuple[int, int]]:
        key = (choice.pack_id, start, goal)
        cached = self._paths.get(key)
        if cached is not None:
            return cached
        terrain = self._terrain_for(choice)
        if terrain is None:
            self._paths[key] = []
            return []
        snapped_start = _snap(terrain, start)
        snapped_goal = _snap(terrain, goal)
        if snapped_start is None or snapped_goal is None:
            self._paths[key] = []
            return []
        from app._04_decision.pathfinding import find_path

        path = [(int(x), int(y)) for x, y in find_path(terrain, snapped_start, snapped_goal)]
        self._paths[key] = path
        return path

    def _terrain_for(self, choice: MapChoice):
        cached = self._terrain.get(choice.pack_id)
        if cached is not None:
            return cached
        terrain = _terrain_from_nav(choice.nav_path, choice.pixel_scale)
        self._terrain[choice.pack_id] = terrain
        return terrain

    def _snap_world(
        self,
        choice: MapChoice,
        world: tuple[int, int],
    ) -> Optional[tuple[int, int]]:
        scale = choice.pixel_scale
        nav = (
            int(world[0] - choice.origin_x) // scale,
            int(world[1] - choice.origin_y) // scale,
        )
        terrain = self._terrain_for(choice)
        if terrain is None:
            return None
        return _snap(terrain, nav)


def _terrain_from_nav(path: Path, pixel_scale: int):
    """Same white-tile grid the patrol editor builds from a map image."""
    from PIL import Image

    from app._03_world.space.terrain_map import TerrainMap

    image = Image.open(path).convert("RGB")
    import numpy as np

    pixels = np.asarray(image, dtype=np.uint8)
    walkable = (
        (pixels[:, :, 0] == 255)
        & (pixels[:, :, 1] == 255)
        & (pixels[:, :, 2] == 255)
    )
    ps = max(1, int(pixel_scale))
    if ps > 1:
        height, width = walkable.shape
        th, tw = height // ps, width // ps
        if th < 1 or tw < 1:
            return None
        blocks = walkable[: th * ps, : tw * ps].reshape(th, ps, tw, ps)
        walkable = blocks.mean(axis=(1, 3)) >= 0.5
    return TerrainMap.from_array(walkable)


def _snap(terrain, tile: tuple[int, int]) -> Optional[tuple[int, int]]:
    from app._03_world.space.world_coords import tile_chebyshev

    x, y = int(tile[0]), int(tile[1])
    if terrain.is_walkable(x, y):
        return (x, y)
    best = None
    best_d = None
    for dy in range(-_SNAP_RADIUS, _SNAP_RADIUS + 1):
        for dx in range(-_SNAP_RADIUS, _SNAP_RADIUS + 1):
            nx, ny = x + dx, y + dy
            if not terrain.is_walkable(nx, ny):
                continue
            dist = tile_chebyshev(x, y, nx, ny)
            if best_d is None or dist < best_d:
                best_d = dist
                best = (nx, ny)
    return best


def _join(
    left: list[tuple[int, int]],
    right: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if not left:
        return list(right)
    if not right:
        return list(left)
    if left[-1] == right[0]:
        return left + right[1:]
    return left + right


def _clicks_for(
    choice: MapChoice,
    path: list[tuple[int, int]],
    *,
    final_name: str,
) -> list[ClickPoint]:
    hops = _mouse_hops(path)
    clicks: list[ClickPoint] = []
    scale = choice.pixel_scale
    for index, (x, y) in enumerate(hops):
        last = index == len(hops) - 1
        name = final_name if last else f"click_{index + 1}"
        clicks.append(
            ClickPoint(
                nav_x=x,
                nav_y=y,
                world_x=choice.origin_x + x * scale,
                world_y=choice.origin_y + y * scale,
                name=name,
            )
        )
    return clicks


def _mouse_hops(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Click tiles along an A* polyline, using the dungeon hop limit."""
    if len(path) < 2:
        return list(path)
    from app._02_state.geometry import WorldOrigin
    from app._04_decision.dungeon import dungeon_max_hop_tiles
    from app._04_decision.pathfinding import select_click_waypoint

    # Terrain is not passed: the editor path is already on walkable tiles,
    # and the click test without a terrain uses the same slack rule.
    hop = dungeon_max_hop_tiles()
    clicks: list[tuple[int, int]] = []
    index = 0
    guard = 0
    while index < len(path) - 1 and guard < len(path) * 2:
        guard += 1
        origin = WorldOrigin(int(path[index][0]), int(path[index][1]))
        picked = select_click_waypoint(
            path[index:],
            origin,
            max_hop=hop,
        )
        if picked is None:
            index += 1
            clicks.append(path[index])
            continue
        clicks.append((int(picked[0]), int(picked[1])))
        nxt = next(
            (k for k in range(index + 1, len(path)) if path[k] == picked),
            None,
        )
        if nxt is None or nxt <= index:
            index += 1
        else:
            index = nxt
    if not clicks or clicks[-1] != path[-1]:
        clicks.append(path[-1])
    out: list[tuple[int, int]] = []
    for tile in clicks:
        if not out or out[-1] != tile:
            out.append(tile)
    return out
