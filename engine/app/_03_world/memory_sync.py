"""Apply analysis-memory snapshots to GameState + navigation origin."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional, TYPE_CHECKING

from app._03_world.constants import LOCAL_PLAYER_TRACK_ID
from app._03_world.player import (
    InventoryState,
    PlayerState,
    StatusEffect,
    memory_weight_ready,
)
from app._03_world.world_coords import WorldOrigin

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world.gamestate import GameState
    from app._04_decision.blackboard import Blackboard

# Talking Island corner of nav.png in raw game coordinates
# (defaults; prefer maps/<id>/meta.yaml via map_pack).
DEFAULT_MAP_ORIGIN_X = 32256
DEFAULT_MAP_ORIGIN_Y = 32704
# Raw LC world is ~30k; nav.png / area YAML tiles are small (a few hundred).
_RAW_GAME_ABS_MIN = 10_000

_map_origin_x: int = DEFAULT_MAP_ORIGIN_X
_map_origin_y: int = DEFAULT_MAP_ORIGIN_Y


def configure_map_origin(config: Optional[dict[str, Any]] = None) -> tuple[int, int]:
    """Load ``navigation.map_origin_x/y`` (Talking Island ↔ nav.png)."""
    global _map_origin_x, _map_origin_y
    section = (config or {}).get("navigation") or {}
    _map_origin_x = int(section.get("map_origin_x", DEFAULT_MAP_ORIGIN_X))
    _map_origin_y = int(section.get("map_origin_y", DEFAULT_MAP_ORIGIN_Y))
    return _map_origin_x, _map_origin_y


def get_map_origin() -> tuple[int, int]:
    return _map_origin_x, _map_origin_y


def _looks_like_raw_game(x: int, y: int) -> bool:
    """True for LC world coords (~32k); False for nav.png / area-YAML tiles."""
    return abs(x) >= _RAW_GAME_ABS_MIN or abs(y) >= _RAW_GAME_ABS_MIN


def game_to_nav(
    game_x: float | int,
    game_y: float | int,
    *,
    origin: Optional[tuple[int, int]] = None,
) -> tuple[int, int]:
    """Player/world coords → Talking Island nav.png tiles.

    Area YAML and live memory may already be relative to the island origin.
    Only subtract ``map_origin`` when the values look like raw LC world (~32k).
    """
    gx, gy = int(game_x), int(game_y)
    if not _looks_like_raw_game(gx, gy):
        return gx, gy
    ox, oy = origin if origin is not None else get_map_origin()
    return gx - ox, gy - oy


def nav_to_game(
    nav_x: int,
    nav_y: int,
    *,
    origin: Optional[tuple[int, int]] = None,
) -> tuple[int, int]:
    ox, oy = origin if origin is not None else get_map_origin()
    return nav_x + ox, nav_y + oy


def _player_poisoned_flag(raw: dict[str, Any], base: PlayerState) -> bool:
    for key in ("poisoned", "isPoisoned", "is_poisoned", "poison"):
        if key in raw:
            return bool(raw.get(key))
    return bool(getattr(base, "poisoned", False))


def player_from_snapshot(
    snapshot: dict[str, Any],
    *,
    base: Optional[PlayerState] = None,
) -> PlayerState:
    """Build / update PlayerState from a monitor ``player`` (+ buffs) block."""
    raw = snapshot.get("player") or {}
    hp = _first_opt_int(raw, "hp")
    max_hp = _first_opt_int(raw, "maxHp", "max_hp")
    mp = _first_opt_int(raw, "mp")
    max_mp = _first_opt_int(raw, "maxMp", "max_mp")
    level = _first_opt_int(raw, "level", "lv")
    exp_pct = float(raw.get("expPct") or 0.0)

    buffs: list[StatusEffect] = []
    for b in snapshot.get("buffs") or []:
        if not isinstance(b, dict):
            continue
        buffs.append(
            StatusEffect(
                name=str(b.get("id", "")),
                duration=float(b.get("remain") or 0.0),
                value=float(b.get("stacks") or 0.0),
            )
        )

    if base is None:
        from app._03_world.battle_area import player_screen_position
        from app._03_world.enums import CharacterType
        from app._03_world.objects import Position

        pos = player_screen_position()
        base = PlayerState(
            track_id=LOCAL_PLAYER_TRACK_ID,
            position=Position(x=pos.x, y=pos.y),
            character_type=CharacterType.MAGE,
        )

    inv = base.inventory
    weight = raw.get("weight")
    max_weight = raw.get("maxWeight")
    try:
        weight_n = float(weight) if weight is not None else float(getattr(base, "weight", 0.0) or 0.0)
    except (TypeError, ValueError):
        weight_n = float(getattr(base, "weight", 0.0) or 0.0)
    try:
        max_weight_n = float(max_weight) if max_weight is not None else float(getattr(base, "max_weight", 0.0) or 0.0)
    except (TypeError, ValueError):
        max_weight_n = float(getattr(base, "max_weight", 0.0) or 0.0)
    weight_ratio = float(getattr(inv, "weight_ratio", 0.0) or 0.0)
    if max_weight_n > 0:
        weight_ratio = max(0.0, min(1.0, weight_n / max_weight_n))
    inventory = InventoryState(
        hp_potion=inv.hp_potion,
        mp_potion=inv.mp_potion,
        weight_ratio=weight_ratio,
        items=list(inv.items),
        arrows=getattr(inv, "arrows", 0),
        silver_arrows=getattr(inv, "silver_arrows", 0),
        depoison=getattr(inv, "depoison", 0),
        adena=getattr(inv, "adena", 0),
        bag_ready=bool(getattr(inv, "bag_ready", False)),
        bag_updated_at=float(getattr(inv, "bag_updated_at", 0.0) or 0.0),
    )

    if hp is None:
        hp = base.hp
    if max_hp is None:
        max_hp = base.max_hp
    if mp is None:
        mp = base.mp
    if max_mp is None:
        max_mp = base.max_mp
    if level is None:
        level = base.level

    hp_ratio = float(getattr(base, "hp_ratio", 1.0) or 1.0)
    if hp is not None and max_hp is not None and max_hp > 0:
        hp_ratio = max(0.0, min(1.0, hp / max_hp))
    mp_ratio = float(getattr(base, "mp_ratio", 1.0) or 1.0)
    if mp is not None and max_mp is not None and max_mp > 0:
        mp_ratio = max(0.0, min(1.0, mp / max_mp))

    return replace(
        base,
        hp=hp,
        max_hp=max_hp,
        mp=mp,
        max_mp=max_mp,
        level=level,
        hp_ratio=hp_ratio,
        mp_ratio=mp_ratio,
        exp_percent=exp_pct,
        weight=weight_n,
        max_weight=max_weight_n,
        zone=str(raw.get("zone") or "") or base.zone,
        alive=True if hp is None else hp > 0,
        buffs=buffs if snapshot.get("buffs") else list(base.buffs),
        poisoned=_player_poisoned_flag(raw, base),
        inventory=inventory,
    )


def player_game_xy_from_snapshot(snapshot: dict[str, Any]) -> Optional[tuple[int, int]]:
    """Raw LC world tile from print_state ``player.x/y`` or monitor ``pos``."""
    raw = snapshot.get("player") if isinstance(snapshot, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        gx, gy = int(raw["x"]), int(raw["y"])
        if gx != 0 or gy != 0:
            return gx, gy
    except (KeyError, TypeError, ValueError):
        pass
    pos = raw.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        try:
            gx, gy = int(pos[0]), int(pos[1])
        except (TypeError, ValueError):
            return None
        if gx != 0 or gy != 0:
            return gx, gy
    return None


def world_origin_from_snapshot(
    snapshot: dict[str, Any],
    *,
    origin: Optional[tuple[int, int]] = None,
) -> Optional[WorldOrigin]:
    """Nav-tile WorldOrigin from print_state or monitor player coords.

    ``(0, 0)`` is treated as unset (monitor not ready) so we do not stamp
    ``(-map_origin_x, -map_origin_y)`` onto the blackboard.
    """
    xy = player_game_xy_from_snapshot(snapshot)
    if xy is None:
        return None
    nx, ny = game_to_nav(xy[0], xy[1], origin=origin)
    return WorldOrigin(x=nx, y=ny)


def _ascii(value: Any) -> str:
    """Hershey preview fonts are Latin-only; replace other glyphs."""
    return str(value).encode("ascii", "replace").decode("ascii")


def _count(block: Any) -> int:
    if isinstance(block, list):
        return len(block)
    return 0


def _dash(value: Any) -> str:
    return "-" if value is None else str(value)


def format_snapshot_preview_lines(
    snapshot: dict[str, Any] | None,
    *,
    nav: Optional[WorldOrigin] = None,
) -> list[str]:
    """HUD lines for every field the memory monitor snapshot carries."""
    if not snapshot or not snapshot.get("player"):
        return ["memory: none"]

    raw = snapshot.get("player") or {}
    hp = raw.get("hp")
    max_hp = raw.get("maxHp")
    if max_hp is None:
        max_hp = raw.get("max_hp")
    mp = raw.get("mp")
    max_mp = raw.get("maxMp")
    if max_mp is None:
        max_mp = raw.get("max_mp")
    sp = raw.get("sp")
    level = raw.get("level")
    exp_pct = float(raw.get("expPct") or 0.0)
    pos = raw.get("pos")
    stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}

    hp_s = f"{hp}/{max_hp}" if max_hp not in (None, "") else _dash(hp)
    mp_s = f"{mp}/{max_mp}" if max_mp not in (None, "") else _dash(mp)
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        pos_s = ",".join(str(int(v)) for v in pos[:3])
    else:
        pos_s = "-"
    nav_s = f"({int(nav.x)},{int(nav.y)})" if nav is not None else "-"

    frame = snapshot.get("frame")
    ts = snapshot.get("ts")
    head = "memory: live"
    if frame is not None:
        head += f"  frame={frame}"
    if ts is not None:
        try:
            head += f"  ts={float(ts):.3f}"
        except (TypeError, ValueError):
            head += f"  ts={ts}"

    lines = [
        head,
        (
            f"mem: HP {hp_s}  MP {mp_s}  SP {sp}  Lv {level}  "
            f"EXP {exp_pct:.4f}%"
        ),
        f"mem: pos=({pos_s})  nav={nav_s}  classId={raw.get('classId')}",
        (
            f"mem: zone={_ascii(raw.get('zone') or '-')}  "
            f"online={raw.get('online')}  gm={raw.get('isGm')}  "
            f"chaotic={raw.get('isChaotic')}  tickMs={raw.get('tickMs')}"
        ),
    ]
    if stats:
        lines.append(
            "mem: stats "
            + " ".join(
                f"{k}={stats[k]}"
                for k in ("str", "dex", "con", "int", "wis", "cha")
                if k in stats
            )
        )
    extras = []
    if raw.get("weight") is not None or raw.get("maxWeight") is not None:
        extras.append(f"wt={_dash(raw.get('weight'))}/{_dash(raw.get('maxWeight'))}")
    if raw.get("food") is not None:
        extras.append(f"food={raw.get('food')}")
    if raw.get("lawful") is not None:
        extras.append(f"lawful={raw.get('lawful')}")
    if raw.get("ac") is not None:
        extras.append(f"ac={raw.get('ac')}")
    if extras:
        lines.append("mem: " + "  ".join(extras))
    n_buffs = _count(snapshot.get("buffs"))
    n_items = _count(snapshot.get("items"))
    n_skills = _count(snapshot.get("skills"))
    n_party = _count(snapshot.get("party"))
    n_ent = _count(snapshot.get("entities"))
    lines.append(
        f"mem: buffs={n_buffs}  items={n_items}  skills={n_skills}  "
        f"party={n_party}  entities={n_ent}"
    )
    return lines


def apply_snapshot(
    game_state: "GameState",
    blackboard: Optional["Blackboard"],
    snapshot: dict[str, Any],
) -> bool:
    """Write vitals into GameState and absolute nav tile into blackboard.

    Returns True when a player block was applied.
    """
    if not snapshot.get("player"):
        return False
    game_state.set_player(player_from_snapshot(snapshot, base=game_state.player))
    game_state.last_memory_snapshot = snapshot
    if blackboard is not None:
        wo = world_origin_from_snapshot(snapshot)
        if wo is not None:
            blackboard.world_origin = wo
    return True


def _opt_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_opt_int(raw: dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        if key in raw and raw.get(key) is not None:
            return _opt_int(raw.get(key))
    return None


def apply_print_state_vitals(
    game_state: "GameState",
    snapshot: dict[str, Any],
) -> bool:
    """Write print_state HP/MP/level onto GameState without wiping monitor extras."""
    raw = snapshot.get("player") if isinstance(snapshot, dict) else None
    if not isinstance(raw, dict):
        return False
    if raw.get("hp") is None and raw.get("mp") is None:
        return False
    game_state.set_player(player_from_snapshot(snapshot, base=game_state.player))
    return True


__all__ = [
    "DEFAULT_MAP_ORIGIN_X",
    "DEFAULT_MAP_ORIGIN_Y",
    "configure_map_origin",
    "get_map_origin",
    "game_to_nav",
    "nav_to_game",
    "player_from_snapshot",
    "apply_print_state_vitals",
    "memory_weight_ready",
    "player_game_xy_from_snapshot",
    "world_origin_from_snapshot",
    "format_snapshot_preview_lines",
    "apply_snapshot",
]
