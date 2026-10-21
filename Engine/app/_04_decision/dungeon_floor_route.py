"""Dungeon floor graph and logical waypoints. No character control.

Taken from the patrol editor's calculator (``floors_entrances.txt`` + A*):

- which floor link joins the current cell to the target floor
- one logical cell per floor (the stair), and the portal cell of each link

Not in this module: clicks, LiveRoute, retries, avoidance, combat, unstick,
cursor checks, gate execution, or patrol files. Callers hand a logical cell
to the existing travel system, or a ``floor`` portal to the existing gate.
"""
from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import yaml

from session.paths import manmabot_root

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
        return self.choice.origin_x + self.nav_x

    @property
    def world_y(self) -> int:
        return self.choice.origin_y + self.nav_y


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
    # Portal used to leave this floor. None on the final floor.
    exit_edge: Optional[PortalEdge] = None


# Existing gate executor (``ActionType.GATE`` / ``run_gate_click``) is the
# world-nav floor ladder. Same-map zone hops and passage links are not that.
GATE_TRANSITION_KIND = "floor"


@dataclass(frozen=True)
class FloorWalk:
    """Logical nav cell on one floor. Not an actual click tile."""

    pack_id: str
    map_id: int
    nav_x: int
    nav_y: int

    @property
    def kind(self) -> str:
        return "walk"

    @property
    def cell(self) -> tuple[int, int]:
        return (self.nav_x, self.nav_y)


@dataclass(frozen=True)
class FloorTransition:
    """One floor link. Only ``kind == floor`` may be handed to the gate executor."""

    kind: str
    from_pack_id: str
    from_map_id: int
    from_nav: tuple[int, int]
    entrance_world: tuple[int, int]
    to_pack_id: str
    to_map_id: int
    landing_world: tuple[int, int]

    @property
    def gate_compatible(self) -> bool:
        return self.kind == GATE_TRANSITION_KIND


FloorStep = Union[FloorWalk, FloorTransition]


@dataclass(frozen=True)
class DungeonFloor:
    """One floor of a named complex from ``map_transitions.json``."""

    complex_name: str
    floor: int
    map_id: int
    pack_id: str
    kr: str


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
    allow_entrance: bool = True,
    arrive_on_floor: bool = False,
) -> list[RouteSegment]:
    """Walk start → goal across floor gates. Raises ``RouteError`` when none exists.

    ``arrive_on_floor`` stops on the goal floor's landing cell. The editor
    keeps the default and still paths to the clicked goal tile.
    ``allow_entrance`` may leave through a world entrance. The live bot passes
    False so a floor route stays inside the dungeon graph.
    """
    router = _Router(
        edges if edges is not None else load_portal_edges(),
        arrive_on_floor=arrive_on_floor,
    )
    if start.choice.pack_id == goal.choice.pack_id:
        if arrive_on_floor:
            return [
                router.segment_on(
                    start.choice,
                    (start.nav_x, start.nav_y),
                    (start.nav_x, start.nav_y),
                    goal_name="arrive",
                )
                or RouteSegment(
                    choice=start.choice,
                    path=[(start.nav_x, start.nav_y)],
                )
            ]
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
    if found is None and allow_entrance:
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
    def __init__(self, edges: list[PortalEdge], *, arrive_on_floor: bool = False) -> None:
        self.edges = edges
        self.arrive_on_floor = arrive_on_floor
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
        if len(seen) > _MAX_DEPTH:
            return None
        choice = self.by_kr.get(map_name)
        if choice is None:
            return None
        # The two training-dungeon yards are both 아덴 대륙. A second visit is
        # the next yard, not a loop. Other maps still cannot be re-entered.
        if choice.pack_id != "mainland" and map_name in seen:
            return None
        if map_name == goal_name:
            if self.arrive_on_floor:
                landed = self.segment_on(choice, nav, nav, goal_name="arrive")
                return [landed] if landed is not None else None
            segment = self.segment_on(choice, nav, goal_nav, goal_name="goal")
            return [segment] if segment is not None else None

        options: list[tuple[int, PortalEdge, list[tuple[int, int]]]] = []
        for edge in self._leaving(map_name, allow_entrance=allow_entrance):
            dst = self.by_kr.get(edge.dst_name)
            if dst is None:
                continue
            if edge.dst_name in seen and dst.pack_id != "mainland":
                continue
            gate = self._snap_world(choice, edge.src_xy)
            if gate is None:
                continue
            path = self._path(choice, nav, gate)
            if not path:
                continue
            options.append((len(path), edge, path))
        options.sort(key=lambda item: item[0])
        seen_next = seen if choice.pack_id == "mainland" else seen | {map_name}
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
            return [
                RouteSegment(
                    choice=choice,
                    path=path,
                    clicks=clicks,
                    exit_edge=edge,
                ),
                *rest,
            ]
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
        # Mainland door yards are about a hundred tiles. A walk that is still
        # going after this many cells has left the yard for the open field,
        # and the next door is not there.
        if choice.pack_id == "mainland" and not _yard_reaches(
            terrain, snapped_start, snapped_goal, limit=2000
        ):
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
        # Terrain cells are already one world tile. pixel_scale only groups
        # source pixels; dividing again jumped a one-tile wall.
        nav = (
            int(world[0] - choice.origin_x),
            int(world[1] - choice.origin_y),
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


def _yard_reaches(terrain, start: tuple[int, int], goal: tuple[int, int], *, limit: int) -> bool:
    """True when ``goal`` sits in the same small walk as ``start``.

    Stops after ``limit`` cells. The open mainland is larger than a door yard,
    so a search that hits the limit has not found the next door.
    """
    if start == goal:
        return True
    pending: deque[tuple[int, int]] = deque([start])
    seen = {start}
    while pending:
        current = pending.popleft()
        if len(seen) > limit:
            return False
        for nxt in terrain.neighbors8(current[0], current[1]):
            if nxt in seen:
                continue
            if nxt == goal:
                return True
            seen.add(nxt)
            pending.append(nxt)
    return False


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
    for index, (x, y) in enumerate(hops):
        last = index == len(hops) - 1
        name = final_name if last else f"click_{index + 1}"
        clicks.append(
            ClickPoint(
                nav_x=x,
                nav_y=y,
                world_x=choice.origin_x + x,
                world_y=choice.origin_y + y,
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


def choice_for_pack(pack_id: str) -> Optional[MapChoice]:
    key = str(pack_id or "").strip()
    if not key:
        return None
    for choice in list_engine_maps():
        if choice.pack_id == key:
            return choice
    return None


def _path_jumps(path: list[tuple[int, int]]) -> bool:
    """True when two path cells are not neighbors. That is a same-floor zone hop."""
    for left, right in zip(path, path[1:]):
        if max(abs(left[0] - right[0]), abs(left[1] - right[1])) > 1:
            return True
    return False


def steps_from_segments(segments: list[RouteSegment]) -> list[FloorStep]:
    """One WALK to that floor's stair, then one TRANSITION per floor link.

    The 3-tile clicks between here and the stair belong to existing travel.
    Walks on the destination floor are omitted. Arrival is the confirmed
    map change, after which the existing patrol file for that floor is used.
    """
    if len(segments) < 2:
        return []
    steps: list[FloorStep] = []
    for index, segment in enumerate(segments[:-1]):
        if _path_jumps(segment.path):
            raise RouteError(
                f"{segment.choice.pack_id} 경로는 같은 층 구역 이동이라 "
                "기존 게이트로 실행할 수 없습니다."
            )
        edge = segment.exit_edge
        kind = "" if edge is None else edge.kind
        if edge is None or kind != GATE_TRANSITION_KIND:
            raise RouteError(
                f"{segment.choice.pack_id} 층 전환 종류 {kind or 'none'} 는 "
                "기존 게이트 실행과 맞지 않습니다."
            )
        nxt = segments[index + 1]
        try:
            from_map = int(segment.choice.raw_map)
            to_map = int(nxt.choice.raw_map)
        except (TypeError, ValueError) as exc:
            raise RouteError("층 맵 번호가 없습니다.") from exc
        if not segment.clicks:
            raise RouteError(f"{segment.choice.pack_id} 이동 좌표가 없습니다.")
        last = segment.clicks[-1]
        steps.append(
            FloorWalk(
                pack_id=segment.choice.pack_id,
                map_id=from_map,
                nav_x=int(last.nav_x),
                nav_y=int(last.nav_y),
            )
        )
        steps.append(
            FloorTransition(
                kind=kind,
                from_pack_id=segment.choice.pack_id,
                from_map_id=from_map,
                from_nav=(int(last.nav_x), int(last.nav_y)),
                entrance_world=(int(edge.src_xy[0]), int(edge.src_xy[1])),
                to_pack_id=nxt.choice.pack_id,
                to_map_id=to_map,
                landing_world=(int(edge.dst_xy[0]), int(edge.dst_xy[1])),
            )
        )
    return steps


def plan_floor_steps(start: PickedPoint, goal_pack_id: str) -> list[FloorStep]:
    """Steps from ``start`` onto ``goal_pack_id``. Empty when already on that floor."""
    goal_choice = choice_for_pack(goal_pack_id)
    if goal_choice is None:
        raise RouteError(f"맵 자료가 없습니다: {goal_pack_id}")
    if start.choice.pack_id == goal_choice.pack_id:
        return []
    goal = PickedPoint(choice=goal_choice, nav_x=0, nav_y=0)
    segments = plan_floor_route(
        start,
        goal,
        allow_entrance=False,
        arrive_on_floor=True,
    )
    return steps_from_segments(segments)


_FLOORS: dict[str, tuple[DungeonFloor, ...]] | None = None
_ENTRANCES: dict[str, frozenset[int]] | None = None


def _load_complexes() -> None:
    """Named dungeon complexes and the floors a ground entrance actually opens."""
    global _FLOORS, _ENTRANCES
    if _FLOORS is not None and _ENTRANCES is not None:
        return
    path = manmabot_root() / "data" / "world" / "map_transitions.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    from app._04_decision.world_nav import pack_ids

    groups: dict[str, list[DungeonFloor]] = {}
    for rec in (raw.get("maps") or {}).values():
        if not isinstance(rec, dict) or rec.get("pc_clone") or not rec.get("is_dungeon"):
            continue
        floor_no = rec.get("floor")
        complex_name = str(rec.get("complex") or "").strip()
        if not complex_name or not isinstance(floor_no, int):
            continue
        try:
            map_id = int(rec.get("mapId"))
        except (TypeError, ValueError):
            continue
        pack_id = pack_ids.map_id_to_pack_id(map_id)
        if not pack_id:
            continue
        groups.setdefault(complex_name, []).append(
            DungeonFloor(
                complex_name=complex_name,
                floor=int(floor_no),
                map_id=map_id,
                pack_id=str(pack_id),
                kr=str(rec.get("kr") or ""),
            )
        )
    entrances: dict[str, set[int]] = {}
    for edge in raw.get("edges") or []:
        if not isinstance(edge, dict) or str(edge.get("kind") or "") != "ground_enter":
            continue
        dest = edge.get("to") if isinstance(edge.get("to"), dict) else {}
        if dest.get("pc_clone"):
            continue
        complex_name = str(dest.get("complex") or "").strip()
        floor_no = dest.get("floor")
        if complex_name and isinstance(floor_no, int):
            entrances.setdefault(complex_name, set()).add(int(floor_no))
    _FLOORS = {
        name: tuple(sorted(rows, key=lambda row: (row.floor, row.map_id)))
        for name, rows in groups.items()
    }
    _ENTRANCES = {name: frozenset(nums) for name, nums in entrances.items()}


def floor_of_pack(pack_id: str) -> Optional[DungeonFloor]:
    """Floor record for ``pack_id``, from the complex list. None if it is not listed."""
    _load_complexes()
    assert _FLOORS is not None
    key = str(pack_id or "").strip()
    if not key:
        return None
    for rows in _FLOORS.values():
        for row in rows:
            if row.pack_id == key:
                return row
    return None


def floors_in_complex(complex_name: str) -> tuple[DungeonFloor, ...]:
    _load_complexes()
    assert _FLOORS is not None
    return _FLOORS.get(str(complex_name or ""), ())


def entrance_floor(complex_name: str) -> Optional[DungeonFloor]:
    """Shallowest floor a ``ground_enter`` edge opens for this complex."""
    _load_complexes()
    assert _ENTRANCES is not None
    nums = _ENTRANCES.get(str(complex_name or ""), frozenset())
    if not nums:
        return None
    want = min(nums)
    for row in floors_in_complex(complex_name):
        if row.floor == want:
            return row
    return None


def same_dungeon_family(current_pack: str, target_pack: str) -> bool:
    """True only when both packs are listed floors of the same complex."""
    current = floor_of_pack(current_pack)
    target = floor_of_pack(target_pack)
    if current is None or target is None:
        return False
    return current.complex_name == target.complex_name


# Own field door. World nav walks to that floor's ground_enter and the
# usual gate clicks it. These floors are not climbed from another floor.
_DIRECT_FIELD_DOOR_PACKS = frozenset(
    {
        "windawood_castle_dungeon_F2",
        "ant_cave_dungeon_F2",
        "ant_cave_dungeon_F3",
        "ant_cave_dungeon_F4",
        "ant_cave_dungeon_F5",
        "ant_cave_dungeon_F6",
        "ant_cave_dungeon_F7",
        "ant_cave_dungeon_F8",
    }
)


def is_direct_field_door_map(map_id: int) -> bool:
    """True when this map is entered at its own field door, not by a stair."""
    try:
        target = int(map_id)
    except (TypeError, ValueError):
        return False
    for pack_id in _DIRECT_FIELD_DOOR_PACKS:
        row = floor_of_pack(pack_id)
        if row is not None and int(row.map_id) == target:
            return True
    return False


def needs_floor_route(target_pack: str) -> bool:
    """True when the scheduled floor is deeper than that complex's entrance floor.

    Packs in ``_DIRECT_FIELD_DOOR_PACKS`` keep the world-nav goal on their own
    map. The mainland ground enter is the door, the same way talking island
    dungeon floor 1 is entered.
    """
    key = str(target_pack or "").strip()
    if key in _DIRECT_FIELD_DOOR_PACKS:
        return False
    target = floor_of_pack(key)
    if target is None:
        return False
    door = entrance_floor(target.complex_name)
    if door is None:
        return False
    return target.pack_id != door.pack_id


def world_nav_entrance_map_id(target_pack: str) -> Optional[int]:
    """Map id world nav should stop on. None keeps the caller's existing goal."""
    if not needs_floor_route(target_pack):
        return None
    target = floor_of_pack(target_pack)
    if target is None:
        return None
    door = entrance_floor(target.complex_name)
    if door is None:
        return None
    return int(door.map_id)


def routine_target_pack(blackboard: object) -> str:
    """Scheduled hunt pack. The routine row wins over a stale ``HUNT_MAP_ID``."""
    from app._04_decision.player_mode import HUNT_MAP_ID
    from app._04_decision.world_nav.hooks import SCRATCH_ROUTINE

    scratch = getattr(blackboard, "scratch", None)
    cursor = scratch.get(SCRATCH_ROUTINE) if isinstance(scratch, dict) else None
    active = cursor.active() if cursor is not None and hasattr(cursor, "active") else None
    if isinstance(active, dict):
        pack_id = str(active.get("map_id") or "").strip()
        if pack_id:
            return pack_id
    return str(HUNT_MAP_ID or "").strip()


def inside_target_dungeon(blackboard: object) -> bool:
    """Live pack is a listed floor of the scheduled complex, and the goal is deeper."""
    from app._03_world.space.map_pack import get_active_map_pack

    pack = get_active_map_pack()
    if pack is None:
        return False
    target = routine_target_pack(blackboard)
    return needs_floor_route(target) and same_dungeon_family(str(pack.id), target)


def arrived_on_hunt_floor(live_pack_id: str, target_pack: str) -> bool:
    """Entrance-floor schedules arrive with world nav. Deeper floors do not."""
    if not needs_floor_route(target_pack):
        return True
    return str(live_pack_id or "") == str(target_pack or "")


SCRATCH_DUNGEON_FLOOR_ROUTE = "dungeon_floor_route"
PURPOSE_DUNGEON_FLOOR = "dungeon_floor"


@dataclass
class FloorRouteSession:
    """One calculated route. Index advances only when a step is really finished."""

    target_pack: str
    complex_name: str
    steps: list[FloorStep]
    index: int = 0
    phase: str = ""
    walk_cell: Optional[tuple[int, int]] = None
    expect_map_id: Optional[int] = None
    gate_seen: bool = False
    gate_ok: bool = False
    gate_map_id: Optional[int] = None
    gate_error: str = ""
    gate_sidestep_done: bool = False
    gate_sidestep_sent: bool = False
    gate_sidestep_waits: int = 0
    gate_sidestep_from: Optional[tuple[int, int]] = None
    replans: int = 0
    fail_reason: str = ""

    def current(self) -> Optional[FloorStep]:
        if 0 <= self.index < len(self.steps):
            return self.steps[self.index]
        return None

    def note_gate(self, ok: bool, map_id: Optional[int], error: str = "") -> None:
        """Record the existing gate executor's result. Does not advance the route."""
        self.gate_seen = True
        self.gate_ok = bool(ok)
        self.gate_map_id = None if map_id is None else int(map_id)
        self.gate_error = str(error or "")

    def fail(self, reason: str) -> None:
        self.phase = "failed"
        self.fail_reason = str(reason or "dungeon floor route unavailable")
