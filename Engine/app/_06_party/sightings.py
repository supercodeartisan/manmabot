"""Monsters a member saw, and the one order the party shares.

A ``track_id`` belongs to one client. The wire carries map, species, guid
when one exists, and the tile. Each client matches that against monsters on
its own screen. Two of the same species too close to tell apart are not
attacked. The leader never receives a click for a monster it cannot see.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

SIGHTING = "sighting"
FOCUS = "party_focus"
UNKNOWN = "unknown"
# Same species with no guid, this close, is one monster. Closer than this
# to a second one of that species is ambiguous.
MATCH_TILES = 3
# Victim at or under this percent is the party-first target. Not measured.
DANGER_HP = 40

_bands = ("dying", "attacking", "engaged", "fresh")


def sighting_message(
    *,
    who: str,
    map_id: int,
    species: str,
    x: int,
    y: int,
    guid: str = "",
    victim: str = "",
    can_attack: bool = False,
    engaged: bool = False,
    victim_hp: Optional[int] = None,
    role: str = "member",
    detour: bool = False,
) -> dict[str, Any]:
    """Member → leader. ``victim`` empty means not attacking a party member.

    ``unknown`` means someone is being hit and this client cannot tell who.
    ``detour`` means reaching it would turn the party around or cross a wall.
    """
    body: dict[str, Any] = {
        "type": SIGHTING,
        "from": str(who or "").strip(),
        "map_id": int(map_id),
        "species": str(species or "").strip(),
        "x": int(x),
        "y": int(y),
        "guid": str(guid or "").strip(),
        "victim": str(victim or "").strip(),
        "can_attack": bool(can_attack),
        "engaged": bool(engaged),
        "role": str(role or "member").strip() or "member",
        "detour": bool(detour),
    }
    if victim_hp is not None:
        body["victim_hp"] = int(victim_hp)
    return body


def focus_message(order: Optional["Focus"]) -> dict[str, Any]:
    """Leader → members. ``clear`` drops the shared target."""
    if order is None:
        return {"type": FOCUS, "from": "leader", "clear": True}
    body: dict[str, Any] = {
        "type": FOCUS,
        "from": "leader",
        "clear": False,
        "map_id": int(order.map_id),
        "species": order.species,
        "guid": order.guid,
        "x": int(order.x),
        "y": int(order.y),
        "support": order.support,
        "leader_species": order.leader_species,
        "leader_guid": order.leader_guid,
        "leader_x": int(order.leader_x),
        "leader_y": int(order.leader_y),
        "hold_advance": bool(order.hold_advance),
        "regroup": bool(order.regroup),
        "band": order.band,
    }
    return body


class Focus:
    """Who peels, and what the leader keeps hitting."""

    def __init__(
        self,
        *,
        map_id: int,
        species: str,
        guid: str,
        x: int,
        y: int,
        support: str,
        leader_species: str,
        leader_guid: str,
        leader_x: int,
        leader_y: int,
        hold_advance: bool,
        regroup: bool,
        band: str,
    ) -> None:
        self.map_id = int(map_id)
        self.species = species
        self.guid = guid
        self.x = int(x)
        self.y = int(y)
        self.support = support
        self.leader_species = leader_species
        self.leader_guid = leader_guid
        self.leader_x = int(leader_x)
        self.leader_y = int(leader_y)
        self.hold_advance = bool(hold_advance)
        self.regroup = bool(regroup)
        self.band = band

    def key(self) -> tuple:
        return (
            self.map_id,
            self.species,
            self.guid,
            self.x,
            self.y,
            self.support,
            self.leader_species,
            self.leader_guid,
            self.hold_advance,
            self.regroup,
            self.band,
        )


def _cheb(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def _band(rows: Sequence[dict[str, Any]]) -> str:
    victims = [
        row for row in rows
        if str(row.get("victim") or "") not in ("", UNKNOWN)
    ]
    if any(int(row.get("victim_hp") if row.get("victim_hp") is not None else 100) <= DANGER_HP for row in victims):
        return "dying"
    if victims or any(str(row.get("victim") or "") == UNKNOWN for row in rows):
        return "attacking"
    if any(bool(row.get("engaged")) for row in rows):
        return "engaged"
    return "fresh"


def _group_key(row: dict[str, Any]) -> tuple:
    guid = str(row.get("guid") or "").strip()
    if guid:
        return ("guid", int(row.get("map_id") or 0), guid)
    return (
        "tile",
        int(row.get("map_id") or 0),
        str(row.get("species") or "").casefold(),
        int(row.get("x") or 0),
        int(row.get("y") or 0),
    )


def _same_loose(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if int(a.get("map_id") or 0) != int(b.get("map_id") or 0):
        return False
    ga = str(a.get("guid") or "").strip()
    gb = str(b.get("guid") or "").strip()
    if ga and gb:
        return ga == gb
    if str(a.get("species") or "").casefold() != str(b.get("species") or "").casefold():
        return False
    return _cheb(int(a.get("x") or 0), int(a.get("y") or 0), int(b.get("x") or 0), int(b.get("y") or 0)) <= MATCH_TILES


def cluster_sightings(rows: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Reports of one monster. A guid never merges with a different guid."""
    groups: list[list[dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not str(row.get("species") or "").strip():
            continue
        placed = False
        for group in groups:
            if _same_loose(group[0], row):
                group.append(row)
                placed = True
                break
        if not placed:
            groups.append([row])
    return groups


def choose_focus(
    rows: Sequence[dict[str, Any]],
    *,
    mode: str = "moving",
    current: Optional[dict[str, Any]] = None,
) -> Optional[Focus]:
    """Shared order. Same band keeps ``current`` so a nearer idle mob does not steal it.

    Fresh mobs are ignored while anything is already fighting the party.
    A fresh mob that would turn the party around (``detour``) is ignored.
    """
    groups = cluster_sightings(rows)
    if not groups:
        return None
    ranked = [(_bands.index(_band(group)), group) for group in groups]
    ranked.sort(key=lambda item: item[0])
    best_band = ranked[0][0]
    contenders = [group for band, group in ranked if band == best_band]
    if best_band >= _bands.index("fresh"):
        contenders = [
            group for group in contenders
            if not all(bool(row.get("detour")) for row in group)
        ]
        if not contenders:
            return None
        # Do not open a new fight while one is already in progress.
        if any(band < _bands.index("fresh") for band, _group in ranked):
            return None
    chosen = contenders[0]
    if current is not None:
        for group in contenders:
            if any(_same_loose(current, row) for row in group):
                chosen = group
                break
    sample = chosen[0]
    victim = ""
    victim_hp = None
    for row in chosen:
        name = str(row.get("victim") or "")
        if name and name != UNKNOWN:
            victim = name
            if row.get("victim_hp") is not None:
                victim_hp = int(row.get("victim_hp"))
            break
    support = ""
    for row in chosen:
        if not bool(row.get("can_attack")):
            continue
        who = str(row.get("who") or row.get("from") or "")
        if not who or who == victim:
            continue
        if str(row.get("role") or "") == "mage":
            continue
        support = who
        break
    band = _bands[best_band]
    dying = band == "dying"
    turret = str(mode) == "turret"
    hold = (not turret) and dying
    regroup = turret and dying
    leader_sees = any(
        str(row.get("role") or "") == "leader" for row in chosen
    )
    leader_row = sample if dying and leader_sees else (current if current is not None else sample)
    return Focus(
        map_id=int(sample.get("map_id") or 0),
        species=str(sample.get("species") or ""),
        guid=str(sample.get("guid") or ""),
        x=int(sample.get("x") or 0),
        y=int(sample.get("y") or 0),
        support=support,
        leader_species=str(leader_row.get("species") or ""),
        leader_guid=str(leader_row.get("guid") or ""),
        leader_x=int(leader_row.get("x") or 0),
        leader_y=int(leader_row.get("y") or 0),
        hold_advance=hold,
        regroup=regroup,
        band=band,
    )


def resolve_local(
    spec: Optional[dict[str, Any]],
    monsters: Sequence[Any],
    *,
    origin: Any = None,
) -> Optional[Any]:
    """The one local monster matching ``spec``, or None.

    None means unseen, or two of the same species too close to separate.
    Callers must not click a stored tile when this returns None.
    """
    if not isinstance(spec, dict) or bool(spec.get("clear")):
        return None
    species = str(spec.get("species") or spec.get("leader_species") or "").casefold()
    guid = str(spec.get("guid") or spec.get("leader_guid") or "").strip()
    try:
        x = int(spec.get("x") if spec.get("species") else spec.get("leader_x"))
        y = int(spec.get("y") if spec.get("species") else spec.get("leader_y"))
    except (TypeError, ValueError):
        return None
    hits = []
    for obj in monsters:
        if obj is None:
            continue
        obj_guid = str(getattr(obj, "guid", "") or "").strip()
        obj_species = str(
            getattr(obj, "species_name", None) or getattr(obj, "species", "") or ""
        ).casefold()
        if guid and obj_guid and obj_guid == guid:
            hits.append(obj)
            continue
        if species and obj_species != species:
            continue
        tile = _obj_tile(obj, origin)
        if tile is None:
            continue
        if _cheb(tile[0], tile[1], x, y) <= MATCH_TILES:
            hits.append(obj)
    if len(hits) != 1:
        return None
    return hits[0]


def _obj_tile(obj: Any, origin: Any) -> Optional[tuple[int, int]]:
    tile = getattr(obj, "tile", None)
    if isinstance(tile, tuple) and len(tile) >= 2:
        return int(tile[0]), int(tile[1])
    if getattr(obj, "world_cx", None) is not None and getattr(obj, "world_cy", None) is not None:
        try:
            return int(obj.world_cx), int(obj.world_cy)
        except (TypeError, ValueError):
            return None
    pos = getattr(obj, "position", None)
    if pos is not None and hasattr(pos, "x"):
        return int(pos.x), int(pos.y)
    if origin is not None and hasattr(obj, "rx"):
        return int(origin.x) + int(getattr(obj, "rx")), int(origin.y) + int(getattr(obj, "ry"))
    return None


def client_action(
    *,
    role: str,
    name: str,
    focus: Optional[Focus],
    local: Sequence[Any],
    attacked: bool,
) -> tuple[str, Optional[Any]]:
    """What this client does with the shared order and its own screen.

    A mage who is being hit heals before any focus click. A monster that is
    not on this screen is not clicked, including by the leader.
    """
    if attacked and str(role) == "mage":
        return "heal", None
    if focus is None:
        return "none", None
    if str(role) == "leader":
        spec = {
            "species": focus.leader_species,
            "guid": focus.leader_guid,
            "x": focus.leader_x,
            "y": focus.leader_y,
            "map_id": focus.map_id,
        }
        found = resolve_local(spec, local)
        if found is None:
            return "ignore", None
        return "attack", found
    if str(role) == "mage":
        return "heal" if attacked else "none", None
    if focus.support and focus.support != str(name):
        return "keep", None
    spec = {
        "species": focus.species,
        "guid": focus.guid,
        "x": focus.x,
        "y": focus.y,
        "map_id": focus.map_id,
    }
    found = resolve_local(spec, local)
    if found is None:
        return "hold", None
    return "attack", found


class SightingBook:
    """Leader-side pile of the latest report per member. Not a click list."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.order: Optional[Focus] = None
        self._sent: Optional[tuple] = None

    def clear(self) -> None:
        self.rows.clear()
        self.order = None
        self._sent = None

    def note(self, body: dict[str, Any]) -> None:
        if str(body.get("type") or "") != SIGHTING:
            return
        who = str(body.get("from") or body.get("who") or "").strip()
        if not who:
            return
        import time

        stamped = time.monotonic()
        key = who.casefold()
        mobs = body.get("mobs")
        if isinstance(mobs, list):
            rows = []
            for mob in mobs:
                if not isinstance(mob, dict):
                    continue
                row = dict(mob)
                row["who"] = who
                row["from"] = who
                row["map_id"] = int(body.get("map_id") or row.get("map_id") or 0)
                row["_at"] = stamped
                rows.append(row)
            self.rows[key] = rows
            return
        row = dict(body)
        row["who"] = who
        row["_at"] = stamped
        self.rows[key] = [row]

    def decide(self, *, mode: str, current: Optional[dict[str, Any]] = None) -> Optional[Focus]:
        flat: list[dict[str, Any]] = []
        for rows in self.rows.values():
            if isinstance(rows, list):
                flat.extend(row for row in rows if isinstance(row, dict))
            elif isinstance(rows, dict):
                flat.append(rows)
        self.order = choose_focus(flat, mode=mode, current=current)
        return self.order

    @property
    def hold_advance(self) -> bool:
        return bool(self.order is not None and self.order.hold_advance)

    def take_message(self) -> Optional[dict[str, Any]]:
        """A frame when the order changed, else None."""
        order = self.order
        key = None if order is None else order.key()
        if key == self._sent:
            return None
        self._sent = key
        return focus_message(order)


# How often a member repeats its screen. Not measured.
SIGHTING_EVERY_S = 0.4
# A monster inside this many tiles is "I can attack it now". Not measured.
SIGHT_ATTACK_TILES = 10


def _behind(origin: Any, tile: tuple[int, int], heading: Optional[tuple[int, int]]) -> bool:
    if origin is None or heading is None or not hasattr(origin, "x"):
        return False
    hx, hy = int(heading[0]), int(heading[1])
    if hx == 0 and hy == 0:
        return False
    dx = int(tile[0]) - int(origin.x)
    dy = int(tile[1]) - int(origin.y)
    return dx * hx + dy * hy < 0


def sightings_message(who: str, map_id: int, mobs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One frame replacing this member's previous reports. No track ids."""
    clean = []
    for mob in mobs:
        if not isinstance(mob, dict):
            continue
        row = {k: v for k, v in mob.items() if k != "track_id"}
        clean.append(row)
    return {
        "type": SIGHTING,
        "from": str(who or "").strip(),
        "map_id": int(map_id),
        "mobs": clean,
    }


def sightings_from_monsters(
    monsters: Sequence[Any],
    *,
    who: str,
    map_id: int,
    origin: Any = None,
    role: str = "member",
    self_hp: Optional[int] = None,
    heading: Optional[tuple[int, int]] = None,
) -> dict[str, Any]:
    """What this client can see. ``attacked_me`` names this character as the victim.

    A monster with no tile is omitted. With a march heading, a monster behind
    the party is marked ``detour`` unless it is already hitting someone.
    """
    mobs = []
    for obj in list(monsters or [])[:8]:
        species = str(
            getattr(obj, "species_name", None) or getattr(obj, "species", "") or ""
        ).strip()
        tile = _obj_tile(obj, origin)
        if not species or tile is None:
            continue
        attacked = bool(getattr(obj, "attacked_me", False) or getattr(obj, "force_attacks_me", False))
        near = False
        if origin is not None and hasattr(origin, "x"):
            near = _cheb(tile[0], tile[1], int(origin.x), int(origin.y)) <= SIGHT_ATTACK_TILES
        guid = str(getattr(obj, "memory_guid", None) or getattr(obj, "guid", "") or "").strip()
        row: dict[str, Any] = {
            "species": species,
            "guid": guid,
            "x": tile[0],
            "y": tile[1],
            "victim": who if attacked else "",
            "can_attack": near or attacked,
            "engaged": attacked,
            "role": role,
            "detour": _behind(origin, tile, heading) and not attacked,
        }
        if attacked and self_hp is not None:
            row["victim_hp"] = int(self_hp)
        mobs.append(row)
    return sightings_message(who, map_id, mobs)


book = SightingBook()


__all__ = [
    "DANGER_HP",
    "FOCUS",
    "MATCH_TILES",
    "SIGHTING",
    "UNKNOWN",
    "Focus",
    "SightingBook",
    "book",
    "choose_focus",
    "client_action",
    "cluster_sightings",
    "focus_message",
    "resolve_local",
    "sighting_message",
    "sightings_from_monsters",
    "sightings_message",
]
